"""Creator thumbnail list with selection, reordering, and file drops."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget


class ThumbnailView(QListWidget):
    paths_dropped = Signal(list)
    order_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Snap)
        self.setWrapping(True)
        self.setSpacing(10)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setUniformItemSizes(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls() and event.source() is not self:
            paths = [
                Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()
            ]
            if paths:
                self.paths_dropped.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)
        QTimer.singleShot(0, self.order_changed.emit)
