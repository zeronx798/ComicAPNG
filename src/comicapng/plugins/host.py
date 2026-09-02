"""JSON-lines Plugin Host for source work outside the Qt GUI process."""

from __future__ import annotations

import importlib
import json
import logging
import socket
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from typing import Any

from platformdirs import user_log_path

from .api import SourceChapter, SourcePlugin
from .discovery import DiscoveredPlugin, discover_plugins
from .errors import PluginError, PluginErrorCode, PluginOperationError
from .validation import validate_materialized_chapter, validate_materialized_file

LOGGER = logging.getLogger(__name__)
ASYNC_OPERATIONS = frozenset(
    {
        "plugin.health",
        "plugin.list",
        "source.search",
        "source.get_comic",
        "source.get_chapters",
        "source.materialize_cover",
        "source.materialize_chapter",
    }
)
CONTROL_OPERATIONS = frozenset({"source.cancel", "plugin.shutdown"})


def _configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    try:
        directory = user_log_path("ComicAPNG", appauthor=False)
        directory.mkdir(parents=True, exist_ok=True)
        destination: Path | None = directory / "plugin-host.log"
    except OSError:
        destination = None
    logging.basicConfig(
        filename=str(destination) if destination is not None else None,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PluginOperationError(
            PluginError(PluginErrorCode.INVALID_REQUEST, f"{name} must be an object")
        )
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PluginOperationError(
            PluginError(PluginErrorCode.INVALID_REQUEST, f"{name} must not be empty")
        )
    return value.strip()


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise PluginOperationError(
            PluginError(PluginErrorCode.INVALID_REQUEST, f"{name} must be a positive integer")
        )
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise PluginOperationError(
            PluginError(PluginErrorCode.INVALID_REQUEST, f"{name} must be a positive integer")
        ) from exc
    if result < 1:
        raise PluginOperationError(
            PluginError(PluginErrorCode.INVALID_REQUEST, f"{name} must be a positive integer")
        )
    return result


class PluginRegistry:
    def __init__(self) -> None:
        self.discovered = {
            item.manifest.plugin_id: item for item in discover_plugins()
        }
        self.instances: dict[str, SourcePlugin] = {}
        self.lock = Lock()

    def list_manifests(self) -> list[dict[str, Any]]:
        return [
            {
                **item.manifest.to_dict(),
                "compatible": item.compatible,
                "validation_error": item.validation_error,
            }
            for item in self.discovered.values()
        ]

    def descriptor(self, plugin_id: str) -> DiscoveredPlugin:
        try:
            return self.discovered[plugin_id]
        except KeyError as exc:
            raise PluginOperationError(
                PluginError(PluginErrorCode.NOT_FOUND, "The requested plugin is not installed")
            ) from exc

    def load(self, plugin_id: str) -> SourcePlugin:
        descriptor = self.descriptor(plugin_id)
        if not descriptor.compatible:
            raise PluginOperationError(
                PluginError(
                    PluginErrorCode.INCOMPATIBLE_API,
                    descriptor.validation_error or "The plugin API is incompatible",
                )
            )
        with self.lock:
            existing = self.instances.get(plugin_id)
            if existing is not None:
                return existing
            module_name, factory_name = descriptor.manifest.entrypoint.split(":", 1)
            module = importlib.import_module(module_name)
            factory = getattr(module, factory_name)
            instance = factory()
            if getattr(instance, "plugin_id", None) != plugin_id:
                raise PluginOperationError(
                    PluginError(
                        PluginErrorCode.INVALID_SOURCE_DATA,
                        "The plugin entrypoint returned an object with the wrong plugin ID",
                    )
                )
            self.instances[plugin_id] = instance
            return instance


class HostRuntime:
    def __init__(self, output) -> None:
        self.output = output
        self.output_lock = Lock()
        self.registry = PluginRegistry()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="source-plugin")
        self.cancellations: dict[str, Event] = {}
        self.cancellation_lock = Lock()
        self.running = True

    def send(self, message: dict[str, Any]) -> None:
        encoded = json.dumps(message, ensure_ascii=True, separators=(",", ":"))
        with self.output_lock:
            self.output.write(encoded + "\n")
            self.output.flush()

    def submit(self, request_id: str, operation: str, payload: dict[str, Any]) -> None:
        cancel_event = Event()
        with self.cancellation_lock:
            self.cancellations[request_id] = cancel_event
        future = self.executor.submit(
            self._execute,
            request_id,
            operation,
            payload,
            cancel_event,
        )
        future.add_done_callback(
            lambda completed, rid=request_id: self._complete(rid, completed)
        )

    def _execute(
        self,
        request_id: str,
        operation: str,
        payload: dict[str, Any],
        cancel_event: Event,
    ) -> Any:
        plugin_id = str(payload.get("plugin_id", ""))
        task_id = str(payload.get("task_id", request_id))
        LOGGER.info("plugin_id=%s task_id=%s operation=%s started", plugin_id, task_id, operation)
        if cancel_event.is_set():
            raise PluginOperationError(
                PluginError(PluginErrorCode.CANCELLED, "The plugin operation was cancelled")
            )
        result = self._dispatch(request_id, operation, payload, cancel_event)
        if cancel_event.is_set():
            raise PluginOperationError(
                PluginError(PluginErrorCode.CANCELLED, "The plugin operation was cancelled")
            )
        LOGGER.info("plugin_id=%s task_id=%s operation=%s completed", plugin_id, task_id, operation)
        return result

    def _dispatch(
        self,
        request_id: str,
        operation: str,
        payload: dict[str, Any],
        cancel_event: Event,
    ) -> Any:
        if operation == "plugin.list":
            return {"plugins": self.registry.list_manifests()}

        plugin_id = _text(payload.get("plugin_id"), "plugin_id")
        if operation == "plugin.health":
            try:
                plugin = self.registry.load(plugin_id)
                result = _object(plugin.health(), "health result")
            except (ImportError, ModuleNotFoundError) as exc:
                return {
                    "available": False,
                    "message": "A required plugin dependency could not be imported",
                    "dependency_version": None,
                    "error_code": PluginErrorCode.DEPENDENCY_UNAVAILABLE.value,
                    "technical_type": type(exc).__name__,
                }
            return result

        plugin = self.registry.load(plugin_id)
        if operation == "source.search":
            query = _text(payload.get("query"), "query")
            page = _positive_integer(payload.get("page"), "page")
            return plugin.search(query, page).to_dict()
        if operation == "source.get_comic":
            return plugin.get_comic(_text(payload.get("source_id"), "source_id")).to_dict()
        if operation == "source.get_chapters":
            chapters = plugin.get_chapters(_text(payload.get("comic_id"), "comic_id"))
            return {"items": [chapter.to_dict() for chapter in chapters]}
        if operation == "source.materialize_cover":
            destination = self._destination(payload)
            task_id = _text(payload.get("task_id", request_id), "task_id")
            path = plugin.materialize_cover(
                _text(payload.get("comic_id"), "comic_id"),
                destination,
                task_id=task_id,
                cancel_event=cancel_event,
            )
            return {"local_path": str(validate_materialized_file(path, destination))}
        if operation == "source.materialize_chapter":
            try:
                chapter = SourceChapter.from_dict(payload.get("chapter"))
            except ValueError as exc:
                raise PluginOperationError(
                    PluginError(PluginErrorCode.INVALID_REQUEST, str(exc))
                ) from exc
            if chapter.plugin_id != plugin_id:
                raise PluginOperationError(
                    PluginError(PluginErrorCode.INVALID_REQUEST, "Chapter plugin ID does not match")
                )
            destination = self._destination(payload)
            include_cover = payload.get("include_cover", False)
            if not isinstance(include_cover, bool):
                raise PluginOperationError(
                    PluginError(PluginErrorCode.INVALID_REQUEST, "include_cover must be a boolean")
                )
            task_id = _text(payload.get("task_id", request_id), "task_id")

            def progress(current: int, total: int) -> None:
                self.send(
                    {
                        "request_id": request_id,
                        "event": "progress",
                        "progress": {"current": int(current), "total": int(total)},
                    }
                )

            result = plugin.materialize_chapter(
                chapter,
                destination,
                include_cover=include_cover,
                task_id=task_id,
                cancel_event=cancel_event,
                progress=progress,
            )
            return validate_materialized_chapter(result, destination).to_dict()
        raise PluginOperationError(
            PluginError(PluginErrorCode.INVALID_REQUEST, "The requested operation is not allowed")
        )

    @staticmethod
    def _destination(payload: dict[str, Any]) -> Path:
        destination_text = _text(payload.get("destination"), "destination")
        destination = Path(destination_text)
        if not destination.is_absolute():
            raise PluginOperationError(
                PluginError(
                    PluginErrorCode.INVALID_REQUEST,
                    "The materialization destination must be an absolute path",
                )
            )
        destination.mkdir(parents=True, exist_ok=True)
        return destination.resolve(strict=True)

    def _complete(self, request_id: str, future: Future[Any]) -> None:
        with self.cancellation_lock:
            self.cancellations.pop(request_id, None)
        try:
            result = future.result()
        except PluginOperationError as exc:
            self.send(
                {
                    "request_id": request_id,
                    "success": False,
                    "result": None,
                    "error": exc.error.to_dict(),
                }
            )
        except (ImportError, ModuleNotFoundError) as exc:
            LOGGER.exception("Plugin dependency import failed")
            error = PluginError(
                PluginErrorCode.DEPENDENCY_UNAVAILABLE,
                "A required plugin dependency is unavailable",
                type(exc).__name__,
            )
            self.send(
                {"request_id": request_id, "success": False, "result": None, "error": error.to_dict()}
            )
        except Exception as exc:
            LOGGER.exception("Plugin operation failed")
            error = PluginError(
                PluginErrorCode.INTERNAL_PLUGIN_ERROR,
                "The source plugin could not complete the operation",
                type(exc).__name__,
            )
            self.send(
                {"request_id": request_id, "success": False, "result": None, "error": error.to_dict()}
            )
        else:
            self.send(
                {"request_id": request_id, "success": True, "result": result, "error": None}
            )

    def cancel(self, request_id: str, payload: dict[str, Any]) -> None:
        target = _text(payload.get("request_id"), "request_id")
        with self.cancellation_lock:
            event = self.cancellations.get(target)
        if event is not None:
            event.set()
        self.send(
            {
                "request_id": request_id,
                "success": True,
                "result": {"accepted": event is not None},
                "error": None,
            }
        )

    def shutdown(self, request_id: str) -> None:
        with self.cancellation_lock:
            for event in self.cancellations.values():
                event.set()
        self.send(
            {"request_id": request_id, "success": True, "result": {"stopping": True}, "error": None}
        )
        self.running = False
        self.executor.shutdown(wait=False, cancel_futures=True)


def _socket_streams(arguments: list[str]):
    try:
        port_index = arguments.index("--connect-port")
        token_index = arguments.index("--connect-token")
        port = int(arguments[port_index + 1])
        token = arguments[token_index + 1]
    except (ValueError, IndexError):
        return None
    connection = socket.create_connection(("127.0.0.1", port), timeout=10.0)
    connection.settimeout(None)
    reader = connection.makefile("r", encoding="utf-8", errors="strict", newline="\n")
    writer = connection.makefile("w", encoding="utf-8", errors="strict", newline="\n")
    writer.write(
        json.dumps({"event": "hello", "token": token}, ensure_ascii=True, separators=(",", ":"))
        + "\n"
    )
    writer.flush()
    return connection, reader, writer


def main(arguments: list[str] | None = None) -> int:
    _configure_logging()
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    streams = _socket_streams(arguments)
    connection = None
    if streams is None:
        protocol_input = sys.stdin
        protocol_output = sys.stdout
        if protocol_input is None or protocol_output is None:
            return 2
    else:
        connection, protocol_input, protocol_output = streams
    sys.stdout = sys.stderr
    runtime = HostRuntime(protocol_output)
    try:
        for line in protocol_input:
            if not runtime.running:
                break
            request: object = None
            try:
                request = json.loads(line)
                data = _object(request, "request")
                request_id = _text(data.get("request_id"), "request_id")
                operation = _text(data.get("operation"), "operation")
                payload = _object(data.get("payload", {}), "payload")
                if operation in ASYNC_OPERATIONS:
                    runtime.submit(request_id, operation, payload)
                elif operation == "source.cancel":
                    runtime.cancel(request_id, payload)
                elif operation == "plugin.shutdown":
                    runtime.shutdown(request_id)
                else:
                    raise PluginOperationError(
                        PluginError(
                            PluginErrorCode.INVALID_REQUEST,
                            "The requested operation is not allowed",
                        )
                    )
            except PluginOperationError as exc:
                fallback_id = (
                    request.get("request_id", "invalid")
                    if isinstance(request, dict)
                    else "invalid"
                )
                runtime.send(
                    {
                        "request_id": str(fallback_id),
                        "success": False,
                        "result": None,
                        "error": exc.error.to_dict(),
                    }
                )
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                error = PluginError(
                    PluginErrorCode.INVALID_REQUEST,
                    "The IPC request is invalid",
                    str(exc),
                )
                runtime.send(
                    {
                        "request_id": "invalid",
                        "success": False,
                        "result": None,
                        "error": error.to_dict(),
                    }
                )
            if not runtime.running:
                break
    finally:
        if streams is not None:
            protocol_input.close()
            protocol_output.close()
        if connection is not None:
            connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
