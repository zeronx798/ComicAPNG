"""Seconds-based editor for millisecond duration values."""

from __future__ import annotations

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QDoubleSpinBox, QWidget

MILLISECONDS_PER_SECOND = 1000
MINIMUM_DURATION_MS = 1
MAXIMUM_DURATION_MS = 600_000


class DurationSpinBox(QDoubleSpinBox):
    """Display three-decimal seconds while preserving integer milliseconds."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLocale(QLocale.c())
        self.setDecimals(3)
        self.setRange(
            MINIMUM_DURATION_MS / MILLISECONDS_PER_SECOND,
            MAXIMUM_DURATION_MS / MILLISECONDS_PER_SECOND,
        )
        self.setSingleStep(1.0)

    def set_milliseconds(self, duration_ms: int) -> None:
        self.setValue(duration_ms / MILLISECONDS_PER_SECOND)

    def milliseconds(self) -> int:
        return round(self.value() * MILLISECONDS_PER_SECOND)
