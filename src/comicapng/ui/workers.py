"""Reusable cancellable Qt thread-pool worker."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from comicapng.core.exceptions import OperationCancelledError

LOGGER = logging.getLogger(__name__)


class WorkerSignals(QObject):
    progress = Signal(int, int)
    result = Signal(object)
    error = Signal(str, str)
    canceled = Signal()
    finished = Signal()


class Worker(QRunnable):
    """Run a callable receiving a cancellation event and progress callback."""

    def __init__(self, function: Callable[[Event, Callable[[int, int], None]], Any]) -> None:
        super().__init__()
        self.function = function
        self.cancel_event = Event()
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.cancel_event.set()

    @staticmethod
    def _emit(signal, *values: object) -> None:
        try:
            signal.emit(*values)
        except RuntimeError:
            LOGGER.debug("Worker signal receiver was already destroyed")

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(
                self.cancel_event,
                lambda current, total: self._emit(self.signals.progress, current, total),
            )
        except OperationCancelledError:
            self._emit(self.signals.canceled)
        except Exception as exc:
            LOGGER.exception("Background operation failed")
            self._emit(self.signals.error, type(exc).__name__, str(exc))
        else:
            self._emit(self.signals.result, result)
        finally:
            self._emit(self.signals.finished)
