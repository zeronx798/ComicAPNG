"""Creator thumbnail list with selection, reordering, and file drops."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget

INTERNAL_PAGE_MOVE_MIME = "application/x-comicapng-page-move"


class ThumbnailView(QListWidget):
    paths_dropped = Signal(list)
    pages_move_requested = Signal(list, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        # Snap enables icon dragging, but internal drops are translated into an
        # explicit model move instead of letting visual positions own ordering.
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

    def startDrag(self, _supported_actions) -> None:
        selected = self.selectedIndexes()
        if not selected:
            return
        mime_data = self.model().mimeData(selected)
        if mime_data is None:
            return
        mime_data.setData(INTERNAL_PAGE_MOVE_MIME, QByteArray(b"1"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        item = self.currentItem() or self.selectedItems()[0]
        pixmap = item.icon().pixmap(self.iconSize())
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().center())
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(INTERNAL_PAGE_MOVE_MIME):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(INTERNAL_PAGE_MOVE_MIME):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def drop_insertion_boundary(self, position: QPoint) -> int:
        """Return a row boundary in the current visual, row-major layout."""
        if self.count() == 0:
            return 0
        target = self.indexAt(position)
        if target.isValid():
            rectangle = self.visualRect(target)
            if self.flow() == QListView.Flow.LeftToRight:
                return target.row() + int(position.x() >= rectangle.center().x())
            return target.row() + int(position.y() >= rectangle.center().y())

        rectangles = [self.visualItemRect(self.item(row)) for row in range(self.count())]
        groups: list[list[int]] = []
        if self.flow() == QListView.Flow.LeftToRight:
            for row, rectangle in enumerate(rectangles):
                if (
                    not groups
                    or abs(
                        rectangle.center().y() - rectangles[groups[-1][0]].center().y()
                    )
                    > 2
                ):
                    groups.append([row])
                else:
                    groups[-1].append(row)
            for group in groups:
                group_top = min(rectangles[row].top() for row in group)
                group_bottom = max(rectangles[row].bottom() for row in group)
                if position.y() < group_top:
                    return group[0]
                if position.y() <= group_bottom:
                    for row in group:
                        if position.x() < rectangles[row].center().x():
                            return row
                    return group[-1] + 1
        else:
            for row, rectangle in enumerate(rectangles):
                if (
                    not groups
                    or abs(
                        rectangle.center().x() - rectangles[groups[-1][0]].center().x()
                    )
                    > 2
                ):
                    groups.append([row])
                else:
                    groups[-1].append(row)
            for group in groups:
                group_left = min(rectangles[row].left() for row in group)
                group_right = max(rectangles[row].right() for row in group)
                if position.x() < group_left:
                    return group[0]
                if position.x() <= group_right:
                    for row in group:
                        if position.y() < rectangles[row].center().y():
                            return row
                    return group[-1] + 1
        return self.count()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasFormat(INTERNAL_PAGE_MOVE_MIME):
            source_rows = sorted({index.row() for index in self.selectedIndexes()})
            if source_rows:
                boundary = self.drop_insertion_boundary(event.position().toPoint())
                target_index = boundary - sum(row < boundary for row in source_rows)
                target_index = max(0, min(target_index, self.count() - len(source_rows)))
                self.pages_move_requested.emit(source_rows, target_index)
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
        if event.mimeData().hasUrls():
            paths = [
                Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()
            ]
            if paths:
                self.paths_dropped.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)
