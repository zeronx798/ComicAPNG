"""GUI-side synchronous client for the isolated Plugin Host process."""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4

from platformdirs import user_cache_path

from .errors import PluginCallError, PluginError, PluginErrorCode

ProgressCallback = Callable[[int, int], None]
CANCEL_GRACE_SECONDS = 2.0


class PluginHostClient:
    """Own one lazily started host and route explicit request/response messages."""

    def __init__(self, command: tuple[str, ...] | None = None) -> None:
        self.command = command or self.default_command()
        self.process: subprocess.Popen[str] | None = None
        self.connection: socket.socket | None = None
        self.reader_stream = None
        self.writer_stream = None
        self.reader: Thread | None = None
        self.pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self.pending_lock = Lock()
        self.write_lock = Lock()
        self.lifecycle_lock = Lock()

    @staticmethod
    def default_command() -> tuple[str, ...]:
        if getattr(sys, "frozen", False):
            return (sys.executable, "--plugin-host")
        return (sys.executable, "-m", "comicapng.plugins.host")

    def _start(self) -> None:
        with self.lifecycle_lock:
            if self.process is not None and self.process.poll() is None:
                return
            workdir = user_cache_path("ComicAPNG", appauthor=False) / "plugin-host"
            workdir.mkdir(parents=True, exist_ok=True)
            environment = os.environ.copy()
            environment["PYTHONUNBUFFERED"] = "1"
            environment["PYTHONIOENCODING"] = "utf-8"
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            token = uuid4().hex
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                listener.settimeout(10.0)
                port = listener.getsockname()[1]
                command = (
                    *self.command,
                    "--connect-port",
                    str(port),
                    "--connect-token",
                    token,
                )
                self.process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=workdir,
                    env=environment,
                    creationflags=creationflags,
                )
                try:
                    connection, address = listener.accept()
                except (TimeoutError, OSError) as exc:
                    process = self.process
                    self.process = None
                    if process is not None and process.poll() is None:
                        process.terminate()
                    raise PluginCallError(
                        PluginError(
                            PluginErrorCode.SOURCE_UNAVAILABLE,
                            "The Plugin Host could not establish its IPC connection",
                        )
                    ) from exc
            if address[0] != "127.0.0.1":
                connection.close()
                process = self.process
                self.process = None
                if process is not None and process.poll() is None:
                    process.terminate()
                raise PluginCallError(
                    PluginError(
                        PluginErrorCode.SOURCE_UNAVAILABLE,
                        "The Plugin Host IPC peer is invalid",
                    )
                )
            connection.settimeout(10.0)
            reader_stream = connection.makefile("r", encoding="utf-8", errors="strict", newline="\n")
            writer_stream = connection.makefile("w", encoding="utf-8", errors="strict", newline="\n")
            try:
                hello = json.loads(reader_stream.readline())
            except (json.JSONDecodeError, OSError, UnicodeError) as exc:
                reader_stream.close()
                writer_stream.close()
                connection.close()
                process = self.process
                self.process = None
                if process is not None and process.poll() is None:
                    process.terminate()
                raise PluginCallError(
                    PluginError(
                        PluginErrorCode.SOURCE_UNAVAILABLE,
                        "The Plugin Host returned an invalid IPC greeting",
                    )
                ) from exc
            if not isinstance(hello, dict) or hello.get("token") != token:
                reader_stream.close()
                writer_stream.close()
                connection.close()
                process = self.process
                self.process = None
                if process is not None and process.poll() is None:
                    process.terminate()
                raise PluginCallError(
                    PluginError(
                        PluginErrorCode.SOURCE_UNAVAILABLE,
                        "The Plugin Host IPC greeting could not be authenticated",
                    )
                )
            connection.settimeout(None)
            self.connection = connection
            self.reader_stream = reader_stream
            self.writer_stream = writer_stream
            process = self.process
            self.reader = Thread(
                target=self._read_messages,
                args=(process, reader_stream),
                daemon=True,
                name="plugin-host-reader",
            )
            self.reader.start()

    def _read_messages(self, process: subprocess.Popen[str] | None, reader_stream) -> None:
        if process is None:
            return
        try:
            for line in reader_stream:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("request_id")
                if not isinstance(request_id, str):
                    continue
                with self.pending_lock:
                    destination = self.pending.get(request_id)
                if destination is not None:
                    destination.put(message)
        finally:
            if self.process is process:
                failure = {
                    "event": "host_closed",
                    "message": "The Plugin Host process stopped unexpectedly",
                }
                with self.pending_lock:
                    destinations = list(self.pending.values())
                for destination in destinations:
                    destination.put(failure)

    def _send(self, request: dict[str, Any]) -> None:
        self._start()
        process = self.process
        writer_stream = self.writer_stream
        if process is None or writer_stream is None or process.poll() is not None:
            raise PluginCallError(
                PluginError(PluginErrorCode.SOURCE_UNAVAILABLE, "The Plugin Host is unavailable")
            )
        encoded = json.dumps(request, ensure_ascii=True, separators=(",", ":"))
        try:
            with self.write_lock:
                writer_stream.write(encoded + "\n")
                writer_stream.flush()
        except (BrokenPipeError, OSError) as exc:
            raise PluginCallError(
                PluginError(PluginErrorCode.SOURCE_UNAVAILABLE, "The Plugin Host is unavailable")
            ) from exc

    def request(
        self,
        operation: str,
        payload: dict[str, Any] | None = None,
        *,
        cancel_event: Event | None = None,
        progress: ProgressCallback | None = None,
        timeout: float | None = 120.0,
    ) -> Any:
        request_id = uuid4().hex
        destination: queue.Queue[dict[str, Any]] = queue.Queue()
        with self.pending_lock:
            self.pending[request_id] = destination
        started = time.monotonic()
        cancellation_started: float | None = None
        try:
            self._send(
                {
                    "request_id": request_id,
                    "operation": operation,
                    "payload": payload or {},
                }
            )
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    if cancellation_started is None:
                        cancellation_started = time.monotonic()
                        self._send_cancel(request_id)
                    elif time.monotonic() - cancellation_started >= CANCEL_GRACE_SECONDS:
                        self._terminate()
                        raise PluginCallError(
                            PluginError(
                                PluginErrorCode.CANCELLED,
                                "The plugin operation was cancelled",
                            )
                        )
                if timeout is not None and time.monotonic() - started >= timeout:
                    self._terminate()
                    raise PluginCallError(
                        PluginError(
                            PluginErrorCode.SOURCE_UNAVAILABLE,
                            "The Plugin Host did not respond in time",
                            retryable=True,
                        )
                    )
                try:
                    message = destination.get(timeout=0.1)
                except queue.Empty:
                    continue
                if message.get("event") == "progress":
                    value = message.get("progress")
                    if progress is not None and isinstance(value, dict):
                        progress(int(value.get("current", 0)), int(value.get("total", 0)))
                    continue
                if message.get("event") == "host_closed":
                    raise PluginCallError(
                        PluginError(
                            PluginErrorCode.SOURCE_UNAVAILABLE,
                            str(message.get("message", "The Plugin Host stopped")),
                        )
                    )
                if message.get("success") is True:
                    return message.get("result")
                try:
                    error = PluginError.from_dict(message.get("error"))
                except ValueError as exc:
                    raise PluginCallError(
                        PluginError(
                            PluginErrorCode.INTERNAL_PLUGIN_ERROR,
                            "The Plugin Host returned an invalid error response",
                        )
                    ) from exc
                raise PluginCallError(error)
        finally:
            with self.pending_lock:
                self.pending.pop(request_id, None)

    def _send_cancel(self, target_request_id: str) -> None:
        try:
            self._send(
                {
                    "request_id": uuid4().hex,
                    "operation": "source.cancel",
                    "payload": {"request_id": target_request_id},
                }
            )
        except PluginCallError:
            self._terminate()

    def _terminate(self) -> None:
        with self.lifecycle_lock:
            process = self.process
            self.process = None
            connection = self.connection
            self.connection = None
            reader_stream = self.reader_stream
            self.reader_stream = None
            writer_stream = self.writer_stream
            self.writer_stream = None
        if process is None:
            return
        for stream in (reader_stream, writer_stream):
            if stream is not None:
                with suppress(OSError):
                    stream.close()
        if connection is not None:
            with suppress(OSError):
                connection.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                self._send(
                    {
                        "request_id": uuid4().hex,
                        "operation": "plugin.shutdown",
                        "payload": {},
                    }
                )
                process.wait(timeout=0.5)
            except (PluginCallError, subprocess.TimeoutExpired):
                pass
        self._terminate()

    def __enter__(self) -> PluginHostClient:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()
