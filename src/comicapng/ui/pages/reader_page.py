"""Manual APNG comic reader workflow."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PIL import Image
from PySide6.QtCore import QPoint, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from comicapng.core.apng_reader import ApngDocument, FrameCache
from comicapng.core.exceptions import OperationCancelledError
from comicapng.i18n import I18n
from comicapng.services.reader_state import ReaderStateStore, book_fingerprint
from comicapng.services.settings import AppSettings
from comicapng.services.thumbnail_cache import ThumbnailCache
from comicapng.ui.dialogs.error_dialog import show_error
from comicapng.ui.dialogs.metadata_dialog import MetadataViewerDialog
from comicapng.ui.icons import icon, muted_icon
from comicapng.ui.theme import BACKGROUND
from comicapng.ui.widgets.image_viewer import ImageViewer
from comicapng.ui.workers import Worker


def _pil_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    result = QImage(
        data,
        rgba.width,
        rgba.height,
        rgba.width * 4,
        QImage.Format.Format_RGBA8888,
    ).copy()
    if rgba is not image:
        rgba.close()
    return result


class ReaderPage(QWidget):
    status_message = Signal(str)
    fullscreen_toggle_requested = Signal()
    fullscreen_exit_requested = Signal()
    book_opened = Signal(str)

    def __init__(
        self,
        i18n: I18n,
        settings: AppSettings,
        thumbnail_cache: ThumbnailCache,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.settings = settings
        self.reader_state = ReaderStateStore(settings)
        self.thumbnail_cache = thumbnail_cache
        self.thread_pool = QThreadPool.globalInstance()
        self.document: ApngDocument | None = None
        self.frame_cache: FrameCache | None = None
        self.identity = ""
        self.current_index = 0
        self._open_worker: Worker | None = None
        self._request_token = 0
        self._thumbnail_pending: set[int] = set()
        self._thumbnail_loaded: set[int] = set()
        self.setAcceptDrops(True)
        self._build_ui()
        stored_mode = str(self.settings.value("reader/mode", "single"))
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(stored_mode)))
        self._install_shortcuts()
        self._update_actions()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(12, 8, 12, 8)
        self.open_button = QPushButton(icon("open"), self.i18n.tr("reader.open"))
        self.open_button.clicked.connect(self._choose_file)
        self.metadata_button = QPushButton(icon("metadata"), self.i18n.tr("metadata.view"))
        self.metadata_button.clicked.connect(self._view_metadata)
        top_bar.addWidget(self.open_button)
        top_bar.addWidget(self.metadata_button)
        top_bar.addStretch()

        mode_label = QLabel(self.i18n.tr("reader.mode"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(icon("single_page"), self.i18n.tr("reader.single_page"), "single")
        self.mode_combo.addItem(icon("dual_page"), self.i18n.tr("reader.dual_page"), "dual")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        direction_label = QLabel(self.i18n.tr("reader.direction"))
        self.direction_combo = QComboBox()
        self.direction_combo.addItem(self.i18n.tr("reader.direction_ltr"), "ltr")
        self.direction_combo.addItem(self.i18n.tr("reader.direction_rtl"), "rtl")
        self.direction_combo.currentIndexChanged.connect(self._direction_changed)
        top_bar.addWidget(mode_label)
        top_bar.addWidget(self.mode_combo)
        top_bar.addSpacing(10)
        top_bar.addWidget(direction_label)
        top_bar.addWidget(self.direction_combo)
        root.addLayout(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.thumbnail_list = QListWidget()
        self.thumbnail_list.setObjectName("readerThumbnails")
        self.thumbnail_list.setIconSize(QSize(100, 120))
        self.thumbnail_list.setSpacing(5)
        self.thumbnail_list.setMinimumWidth(130)
        self.thumbnail_list.setMaximumWidth(210)
        self.thumbnail_list.setAccessibleName(self.i18n.tr("reader.thumbnails"))
        self.thumbnail_list.currentRowChanged.connect(self._thumbnail_selected)
        self.thumbnail_list.verticalScrollBar().valueChanged.connect(self._queue_visible_thumbnails)
        splitter.addWidget(self.thumbnail_list)

        self.viewer = ImageViewer()
        self.viewer.set_background_color(str(self.settings.value("reader/background", BACKGROUND)))
        self.viewer.setAccessibleName(self.i18n.tr("reader.page_view"))
        self.viewer.page_wheel.connect(self._wheel_navigation)
        splitter.addWidget(self.viewer)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([165, 900])
        root.addWidget(splitter, 1)

        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(12, 8, 12, 8)
        self.previous_button = self._icon_button("previous", "reader.previous")
        self.next_button = self._icon_button("next", "reader.next")
        self.previous_button.clicked.connect(self.go_previous)
        self.next_button.clicked.connect(self.go_next)
        self.page_counter = QLabel(self.i18n.tr("reader.no_book"))
        self.page_counter.setMinimumWidth(90)
        self.page_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_jump = QSpinBox()
        self.page_jump.setRange(1, 1)
        self.page_jump.setAccessibleName(self.i18n.tr("reader.page_jump"))
        self.page_jump.valueChanged.connect(self._jump_changed)
        self.zoom_out_button = self._icon_button("zoom_out", "reader.zoom_out")
        self.zoom_in_button = self._icon_button("zoom_in", "reader.zoom_in")
        self.fit_page_button = self._icon_button("fit_page", "reader.fit_page")
        self.fit_width_button = self._icon_button("fit_width", "reader.fit_width")
        self.actual_button = self._icon_button("actual_size", "reader.actual_size")
        self.fullscreen_button = self._icon_button("fullscreen", "reader.fullscreen")
        self.zoom_out_button.clicked.connect(self.viewer.zoom_out)
        self.zoom_in_button.clicked.connect(self.viewer.zoom_in)
        self.fit_page_button.clicked.connect(self._fit_page)
        self.fit_width_button.clicked.connect(self._fit_width)
        self.actual_button.clicked.connect(self._actual_size)
        self.fullscreen_button.clicked.connect(self.fullscreen_toggle_requested.emit)
        bottom_bar.addWidget(self.previous_button)
        bottom_bar.addWidget(self.page_counter)
        bottom_bar.addWidget(self.page_jump)
        bottom_bar.addWidget(self.next_button)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.zoom_out_button)
        bottom_bar.addWidget(self.zoom_in_button)
        bottom_bar.addWidget(self.fit_page_button)
        bottom_bar.addWidget(self.fit_width_button)
        bottom_bar.addWidget(self.actual_button)
        bottom_bar.addWidget(self.fullscreen_button)
        root.addLayout(bottom_bar)

    def _icon_button(self, icon_name: str, text_key: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(icon(icon_name))
        button.setToolTip(self.i18n.tr(text_key))
        button.setAccessibleName(self.i18n.tr(text_key))
        return button

    def _install_shortcuts(self) -> None:
        mappings = (
            (QKeySequence(Qt.Key.Key_Left), lambda: self._horizontal_navigation(-1)),
            (QKeySequence(Qt.Key.Key_Right), lambda: self._horizontal_navigation(1)),
            (QKeySequence(Qt.Key.Key_PageUp), self.go_previous),
            (QKeySequence(Qt.Key.Key_PageDown), self.go_next),
            (QKeySequence(Qt.Key.Key_Home), lambda: self.show_page(0)),
            (QKeySequence(Qt.Key.Key_End), self._go_last),
            (QKeySequence(Qt.Key.Key_Escape), self.fullscreen_exit_requested.emit),
            (QKeySequence("Ctrl+0"), self._fit_page),
            (QKeySequence.StandardKey.ZoomIn, self.viewer.zoom_in),
            (QKeySequence.StandardKey.ZoomOut, self.viewer.zoom_out),
            (QKeySequence.StandardKey.Open, self._choose_file),
        )
        for sequence, callback in mappings:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)

    def _choose_file(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            self.i18n.tr("reader.open"),
            str(self.settings.last_directory("reader_open")),
            self.i18n.tr("files.apng_filter"),
        )
        if selected:
            self.open_path(Path(selected))

    def open_path(self, path: Path) -> None:
        if self._open_worker is not None:
            return
        self._request_token += 1
        token = self._request_token
        self.status_message.emit(self.i18n.tr("reader.opening"))
        self.open_button.setEnabled(False)

        def task(cancel_event: Event, _progress):
            if cancel_event.is_set():
                raise OperationCancelledError("Open was cancelled")
            document = ApngDocument(path)
            identity = book_fingerprint(path)
            capacity = max(3, min(9, self.settings.integer("reader/cache_pages", 5)))
            return token, document, FrameCache(document, capacity), identity

        worker = Worker(task)
        self._open_worker = worker
        worker.signals.result.connect(self._open_complete)
        worker.signals.error.connect(self._open_error)
        worker.signals.finished.connect(self._open_finished)
        self.thread_pool.start(worker, 1)

    def _open_complete(self, result: object) -> None:
        token, document, cache, identity = result  # type: ignore[misc]
        if token != self._request_token:
            cache.clear()
            return
        if self.frame_cache is not None:
            self.frame_cache.clear()
        self.document = document
        self.frame_cache = cache
        self.identity = identity
        self.current_index = self.reader_state.position(identity, document.info.frame_count)
        self.settings.set_last_directory("reader_open", document.path)
        self.settings.add_recent_file(document.path)
        self._thumbnail_pending.clear()
        self._thumbnail_loaded.clear()
        self._populate_thumbnail_list()

        private_direction = document.info.metadata.private_metadata.get("reading_direction")
        direction = (
            private_direction
            if private_direction in {"ltr", "rtl"}
            else str(self.settings.value("reader/direction", "ltr"))
        )
        self.direction_combo.blockSignals(True)
        self.direction_combo.setCurrentIndex(max(0, self.direction_combo.findData(direction)))
        self.direction_combo.blockSignals(False)
        fit_mode = str(self.settings.value("reader/fit_mode", "fit_page"))
        if fit_mode == "fit_width":
            self.viewer.fit_width()
        elif fit_mode == "actual":
            self.viewer.actual_size()
        else:
            self.viewer.fit_page()
        self.page_jump.setRange(1, document.info.frame_count)
        self.book_opened.emit(document.path.name)
        self.status_message.emit(
            self.i18n.tr("reader.open_complete", count=document.info.frame_count)
        )
        self.show_page(self.current_index)
        self._queue_visible_thumbnails()
        self._update_actions()

    def _open_error(self, _error_type: str, details: str) -> None:
        show_error(self, self.i18n, "reader.open_error_title", "reader.open_error", details)

    def _open_finished(self) -> None:
        self._open_worker = None
        self.open_button.setEnabled(True)

    def _populate_thumbnail_list(self) -> None:
        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.clear()
        if self.document is not None:
            for index in range(self.document.info.frame_count):
                item = QListWidgetItem(muted_icon("file"), str(index + 1))
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.thumbnail_list.addItem(item)
        self.thumbnail_list.blockSignals(False)

    def _visible_indices(self, start: int | None = None) -> list[int]:
        if self.document is None:
            return []
        index = self.current_index if start is None else start
        indices = [index]
        if (
            self.mode_combo.currentData() == "dual"
            and index > 0
            and index + 1 < self.document.info.frame_count
        ):
            indices.append(index + 1)
        if self.direction_combo.currentData() == "rtl":
            indices.reverse()
        return indices

    def show_page(self, index: int) -> None:
        if self.document is None or self.frame_cache is None:
            return
        index = max(0, min(index, self.document.info.frame_count - 1))
        self.current_index = index
        self._request_token += 1
        token = self._request_token
        cache = self.frame_cache
        indices = self._visible_indices(index)
        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.setCurrentRow(index)
        self.thumbnail_list.scrollToItem(self.thumbnail_list.item(index))
        self.thumbnail_list.blockSignals(False)
        self.page_jump.blockSignals(True)
        self.page_jump.setValue(index + 1)
        self.page_jump.blockSignals(False)
        self._update_counter(indices)
        self.reader_state.set_position(self.identity, index)

        def task(cancel_event: Event, _progress):
            images: list[QImage] = []
            for frame_index in indices:
                if cancel_event.is_set():
                    raise OperationCancelledError("Page load was cancelled")
                frame = cache.get(frame_index)
                try:
                    images.append(_pil_to_qimage(frame))
                finally:
                    frame.close()
            return token, cache, indices, images

        worker = Worker(task)
        worker.signals.result.connect(self._page_loaded)
        worker.signals.error.connect(self._page_load_error)
        self.thread_pool.start(worker, 2)
        self._queue_visible_thumbnails()
        self._update_actions()

    def _page_loaded(self, result: object) -> None:
        token, cache, indices, images = result  # type: ignore[misc]
        if token != self._request_token or cache is not self.frame_cache:
            return
        self.viewer.set_images(images)
        nearby = sorted(
            {
                value
                for index in indices
                for value in (index - 1, index + 1)
                if self.document is not None and 0 <= value < self.document.info.frame_count
            }
            - set(indices)
        )
        if nearby:

            def prefetch_task(cancel_event: Event, _progress):
                if cancel_event.is_set():
                    raise OperationCancelledError("Prefetch was cancelled")
                cache.prefetch(nearby)
                return None

            self.thread_pool.start(Worker(prefetch_task), -1)

    def _page_load_error(self, _error_type: str, details: str) -> None:
        show_error(self, self.i18n, "reader.page_error_title", "reader.page_error", details)

    def _update_counter(self, indices: list[int]) -> None:
        if self.document is None:
            self.page_counter.setText(self.i18n.tr("reader.no_book"))
            return
        logical = sorted(indices)
        if len(logical) == 2:
            self.page_counter.setText(
                self.i18n.tr(
                    "reader.page_counter_dual",
                    first=logical[0] + 1,
                    second=logical[1] + 1,
                    total=self.document.info.frame_count,
                )
            )
        else:
            self.page_counter.setText(
                self.i18n.tr(
                    "reader.page_counter",
                    current=self.current_index + 1,
                    total=self.document.info.frame_count,
                )
            )

    def _queue_visible_thumbnails(self) -> None:
        if self.document is None or not self.identity:
            return
        first = self.thumbnail_list.indexAt(QPoint(0, 0)).row()
        last = self.thumbnail_list.indexAt(
            QPoint(0, max(0, self.thumbnail_list.viewport().height() - 1))
        ).row()
        if first < 0:
            first = max(0, self.current_index - 3)
        if last < first:
            last = min(self.document.info.frame_count - 1, first + 8)
        requested = {
            index
            for index in range(max(0, first - 2), min(self.document.info.frame_count, last + 3))
            if index not in self._thumbnail_loaded and index not in self._thumbnail_pending
        }
        if not requested:
            return
        self._thumbnail_pending.update(requested)
        document = self.document
        identity = self.identity

        def task(cancel_event: Event, _progress):
            results: list[tuple[int, Path]] = []
            for index in sorted(requested):
                if cancel_event.is_set():
                    raise OperationCancelledError("Thumbnail generation was cancelled")
                path = self.thumbnail_cache.frame_thumbnail(
                    document,
                    identity,
                    index,
                    (100, 120),
                )
                results.append((index, path))
            return identity, results

        worker = Worker(task)
        worker.signals.result.connect(self._thumbnails_ready)
        worker.signals.finished.connect(
            lambda: self._thumbnail_pending.difference_update(requested)
        )
        self.thread_pool.start(worker, -2)

    def _thumbnails_ready(self, result: object) -> None:
        identity, thumbnails = result  # type: ignore[misc]
        if identity != self.identity:
            return
        for index, path in thumbnails:
            item = self.thumbnail_list.item(index)
            if item is not None:
                item.setIcon(icon("file") if not path.exists() else QIcon(str(path)))
                self._thumbnail_loaded.add(index)

    def _thumbnail_selected(self, row: int) -> None:
        if row >= 0 and row != self.current_index:
            self.show_page(row)

    def _jump_changed(self, value: int) -> None:
        self.show_page(value - 1)

    def go_next(self) -> None:
        if self.document is None:
            return
        step = 1
        if self.mode_combo.currentData() == "dual" and self.current_index > 0:
            step = 2
        self.show_page(min(self.document.info.frame_count - 1, self.current_index + step))

    def go_previous(self) -> None:
        if self.document is None:
            return
        if self.mode_combo.currentData() == "dual":
            target = 0 if self.current_index <= 1 else self.current_index - 2
        else:
            target = self.current_index - 1
        self.show_page(max(0, target))

    def _go_last(self) -> None:
        if self.document is not None:
            self.show_page(self.document.info.frame_count - 1)

    def _horizontal_navigation(self, direction: int) -> None:
        ltr = self.direction_combo.currentData() != "rtl"
        should_advance = direction > 0 if ltr else direction < 0
        self.go_next() if should_advance else self.go_previous()

    def _wheel_navigation(self, direction: int) -> None:
        self.go_next() if direction > 0 else self.go_previous()

    def _mode_changed(self) -> None:
        self.settings.set_value("reader/mode", str(self.mode_combo.currentData()))
        if self.document is not None:
            self.show_page(self.current_index)

    def _direction_changed(self) -> None:
        self.settings.set_value("reader/direction", str(self.direction_combo.currentData()))
        if self.document is not None:
            self.show_page(self.current_index)

    def _fit_page(self) -> None:
        self.viewer.fit_page()
        self.settings.set_value("reader/fit_mode", "fit_page")

    def _fit_width(self) -> None:
        self.viewer.fit_width()
        self.settings.set_value("reader/fit_mode", "fit_width")

    def _actual_size(self) -> None:
        self.viewer.actual_size()
        self.settings.set_value("reader/fit_mode", "actual")

    def _view_metadata(self) -> None:
        if self.document is not None:
            MetadataViewerDialog(self.i18n, self.document.info.metadata, self).exec()

    def _update_actions(self) -> None:
        has_book = self.document is not None
        self.metadata_button.setEnabled(has_book)
        self.previous_button.setEnabled(has_book and self.current_index > 0)
        self.next_button.setEnabled(
            has_book
            and self.document is not None
            and self.current_index < self.document.info.frame_count - 1
        )
        self.page_jump.setEnabled(has_book)
        for button in (
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_page_button,
            self.fit_width_button,
            self.actual_button,
            self.fullscreen_button,
        ):
            button.setEnabled(has_book)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.open_path(paths[0])
            event.acceptProposedAction()
            return
        super().dropEvent(event)
