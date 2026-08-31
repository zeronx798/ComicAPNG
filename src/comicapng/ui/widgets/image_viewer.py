"""Zoomable single- or dual-page comic image view."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from comicapng.ui.theme import BACKGROUND


class ImageViewer(QGraphicsView):
    page_wheel = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setBackgroundBrush(QBrush(QColor(BACKGROUND)))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self._mode = "fit_page"
        self._manual_scale = 1.0

    @property
    def fit_mode(self) -> str:
        return self._mode

    def set_images(self, images: list[QImage]) -> None:
        self._scene.clear()
        x_position = 0.0
        maximum_height = 0.0
        gap = 18.0
        for image in images:
            pixmap = QPixmap.fromImage(image)
            item = QGraphicsPixmapItem(pixmap)
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            item.setPos(QPointF(x_position, 0.0))
            self._scene.addItem(item)
            x_position += pixmap.width() + gap
            maximum_height = max(maximum_height, float(pixmap.height()))
        if images:
            x_position -= gap
        self._scene.setSceneRect(QRectF(0.0, 0.0, max(1.0, x_position), max(1.0, maximum_height)))
        self._apply_view_mode()

    def clear_images(self) -> None:
        self._scene.clear()

    def set_background_color(self, color_name: str) -> None:
        color = QColor(color_name)
        if color.isValid():
            self.setBackgroundBrush(QBrush(color))

    def fit_page(self) -> None:
        self._mode = "fit_page"
        self._apply_view_mode()

    def fit_width(self) -> None:
        self._mode = "fit_width"
        self._apply_view_mode()

    def actual_size(self) -> None:
        self._mode = "actual"
        self._manual_scale = 1.0
        self.resetTransform()
        self.centerOn(self._scene.sceneRect().center())

    def zoom_in(self) -> None:
        self._set_manual_zoom(1.2)

    def zoom_out(self) -> None:
        self._set_manual_zoom(1 / 1.2)

    def _set_manual_zoom(self, factor: float) -> None:
        current = self.transform().m11()
        target = max(0.05, min(20.0, current * factor))
        if current <= 0:
            return
        self._mode = "manual"
        self.scale(target / current, target / current)

    def _apply_view_mode(self) -> None:
        bounds = self._scene.sceneRect()
        if bounds.isEmpty():
            return
        self.resetTransform()
        if self._mode == "fit_page":
            self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        elif self._mode == "fit_width":
            width = max(1, self.viewport().width() - 8)
            scale = width / max(1.0, bounds.width())
            self.scale(scale, scale)
            self.centerOn(bounds.center())
        elif self._mode == "actual":
            self.centerOn(bounds.center())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._mode in {"fit_page", "fit_width"}:
            self._apply_view_mode()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
            return
        can_scroll = self.verticalScrollBar().maximum() > 0 and self._mode in {"actual", "manual"}
        if can_scroll:
            super().wheelEvent(event)
            return
        direction = 1 if event.angleDelta().y() < 0 else -1
        self.page_wheel.emit(direction)
        event.accept()
