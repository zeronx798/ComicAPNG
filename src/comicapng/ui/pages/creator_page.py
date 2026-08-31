"""Create APNG comic workflow."""

from __future__ import annotations

import copy
from pathlib import Path
from threading import Event

from PySide6.QtCore import QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from comicapng.core.apng_writer import write_apng
from comicapng.core.exceptions import (
    InvalidImageError,
    OperationCancelledError,
    ResourceLimitError,
)
from comicapng.core.image_files import discover_images, inspect_image
from comicapng.core.models import (
    DEFAULT_BODY_DURATION_MS,
    DEFAULT_COVER_DURATION_MS,
    ComicBook,
    ComicPage,
)
from comicapng.i18n import I18n
from comicapng.services.settings import AppSettings
from comicapng.services.thumbnail_cache import ThumbnailCache
from comicapng.ui.dialogs.error_dialog import show_error
from comicapng.ui.dialogs.metadata_dialog import MetadataEditorDialog
from comicapng.ui.icons import danger_icon, icon
from comicapng.ui.theme import SELECTION
from comicapng.ui.widgets.duration_spin_box import DurationSpinBox
from comicapng.ui.widgets.thumbnail_view import ThumbnailView
from comicapng.ui.workers import Worker


class CreatorPage(QWidget):
    status_message = Signal(str)

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
        self.thumbnail_cache = thumbnail_cache
        self.thread_pool = QThreadPool.globalInstance()
        self.book = ComicBook(
            cover_duration_ms=settings.integer(
                "creator/cover_duration", DEFAULT_COVER_DURATION_MS
            ),
            body_duration_ms=settings.integer("creator/body_duration", DEFAULT_BODY_DURATION_MS),
        )
        self._active_worker: Worker | None = None
        self._progress_dialog: QProgressDialog | None = None
        self._build_ui()
        self._install_shortcuts()
        self._update_actions()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        heading = QLabel(self.i18n.tr("creator.title"))
        heading.setObjectName("heading")
        root.addWidget(heading)

        toolbar = QHBoxLayout()
        self.import_files_button = self._tool_button("file", "creator.import_files")
        self.import_folder_button = self._tool_button("folder", "creator.import_folder")
        self.remove_button = self._tool_button("delete", "creator.remove", danger=True)
        self.cover_button = self._tool_button("cover", "creator.set_cover")
        self.metadata_button = self._tool_button("metadata", "metadata.title")
        self.export_button = self._tool_button("export", "creator.export", primary=True)
        toolbar.addWidget(self.import_files_button)
        toolbar.addWidget(self.import_folder_button)
        toolbar.addWidget(self.remove_button)
        toolbar.addWidget(self.cover_button)
        toolbar.addWidget(self.metadata_button)
        toolbar.addStretch()
        toolbar.addWidget(self.export_button)
        root.addLayout(toolbar)

        self.page_list = ThumbnailView()
        thumbnail_size = self.settings.integer("creator/thumbnail_size", 170)
        self.page_list.setIconSize(QSize(thumbnail_size, thumbnail_size))
        self.page_list.setGridSize(QSize(thumbnail_size + 36, thumbnail_size + 60))
        self.page_list.setAccessibleName(self.i18n.tr("creator.page_list"))
        self.page_list.setToolTip(self.i18n.tr("creator.page_list_help"))
        self.page_list.paths_dropped.connect(self.import_entries)
        self.page_list.order_changed.connect(self._synchronize_order)
        self.page_list.itemSelectionChanged.connect(self._update_actions)
        root.addWidget(self.page_list, 1)

        options = QFrame()
        options.setObjectName("panel")
        options_layout = QHBoxLayout(options)
        cover_label = QLabel(self.i18n.tr("creator.cover_duration"))
        self.cover_duration = DurationSpinBox()
        self.cover_duration.set_milliseconds(self.book.cover_duration_ms)
        self.cover_duration.setAccessibleName(cover_label.text())
        cover_label.setBuddy(self.cover_duration)
        self.cover_duration_unit = QLabel(self.i18n.tr("common.seconds_unit"))
        body_label = QLabel(self.i18n.tr("creator.body_duration"))
        self.body_duration = DurationSpinBox()
        self.body_duration.set_milliseconds(self.book.body_duration_ms)
        self.body_duration.setAccessibleName(body_label.text())
        body_label.setBuddy(self.body_duration)
        self.body_duration_unit = QLabel(self.i18n.tr("common.seconds_unit"))
        direction_label = QLabel(self.i18n.tr("reader.direction"))
        self.direction_combo = QComboBox()
        self.direction_combo.addItem(self.i18n.tr("reader.direction_ltr"), "ltr")
        self.direction_combo.addItem(self.i18n.tr("reader.direction_rtl"), "rtl")
        options_layout.addWidget(cover_label)
        options_layout.addWidget(self.cover_duration)
        options_layout.addWidget(self.cover_duration_unit)
        options_layout.addSpacing(12)
        options_layout.addWidget(body_label)
        options_layout.addWidget(self.body_duration)
        options_layout.addWidget(self.body_duration_unit)
        options_layout.addSpacing(12)
        options_layout.addWidget(direction_label)
        options_layout.addWidget(self.direction_combo)
        options_layout.addStretch()
        self.count_label = QLabel()
        self.count_label.setObjectName("muted")
        options_layout.addWidget(self.count_label)
        root.addWidget(options)

        self.import_files_button.clicked.connect(self._choose_files)
        self.import_folder_button.clicked.connect(self._choose_folder)
        self.remove_button.clicked.connect(self._remove_selected)
        self.cover_button.clicked.connect(self._set_selected_cover)
        self.metadata_button.clicked.connect(self._edit_metadata)
        self.export_button.clicked.connect(self._choose_export)

    def _tool_button(
        self,
        icon_name: str,
        text_key: str,
        *,
        danger: bool = False,
        primary: bool = False,
    ) -> QToolButton:
        button = QToolButton()
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setText(self.i18n.tr(text_key))
        button.setIcon(danger_icon(icon_name) if danger else icon(icon_name))
        button.setToolTip(self.i18n.tr(text_key))
        button.setAccessibleName(self.i18n.tr(text_key))
        if primary:
            button.setObjectName("primary")
        return button

    def _install_shortcuts(self) -> None:
        select_all = QShortcut(QKeySequence.StandardKey.SelectAll, self)
        select_all.activated.connect(self.page_list.selectAll)
        delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        delete.activated.connect(self._remove_selected)
        open_files = QShortcut(QKeySequence.StandardKey.Open, self)
        open_files.activated.connect(self._choose_files)
        export = QShortcut(QKeySequence.StandardKey.Save, self)
        export.activated.connect(self._choose_export)

    def _choose_files(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            self.i18n.tr("creator.import_files"),
            str(self.settings.last_directory("creator_import")),
            self.i18n.tr("files.image_filter"),
        )
        if paths:
            self.settings.set_last_directory("creator_import", Path(paths[0]))
            self.import_entries([Path(path) for path in paths])

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            self.i18n.tr("creator.import_folder"),
            str(self.settings.last_directory("creator_import")),
        )
        if path:
            directory = Path(path)
            self.settings.set_last_directory("creator_import", directory)
            self.import_entries([directory])

    def import_entries(self, entries: list[Path]) -> None:
        if self._active_worker is not None:
            return
        paths = discover_images(entries)
        existing = {
            str(page.source_path.resolve()).casefold()
            for page in self.book.pages
            if page.source_path is not None
        }
        paths = [path for path in paths if str(path.resolve()).casefold() not in existing]
        if not paths:
            self.status_message.emit(self.i18n.tr("creator.no_new_images"))
            return

        thumbnail_size = self.page_list.iconSize()

        def task(cancel_event: Event, progress) -> tuple[list[tuple], list[str]]:
            imported: list[tuple] = []
            errors: list[str] = []
            for index, path in enumerate(paths):
                if cancel_event.is_set():
                    raise OperationCancelledError("Image import was cancelled")
                try:
                    width, height, image_format = inspect_image(path)
                    thumbnail = self.thumbnail_cache.source_thumbnail(
                        path, (thumbnail_size.width(), thumbnail_size.height())
                    )
                    imported.append((path, width, height, image_format, thumbnail))
                except (InvalidImageError, ResourceLimitError, OSError) as exc:
                    errors.append(str(exc))
                progress(index + 1, len(paths))
            return imported, errors

        worker = Worker(task)
        self._active_worker = worker
        dialog = self._show_progress("creator.importing", len(paths), worker)
        worker.signals.result.connect(self._finish_import)
        worker.signals.error.connect(self._worker_error)
        worker.signals.canceled.connect(
            lambda: self.status_message.emit(self.i18n.tr("common.cancelled"))
        )
        worker.signals.finished.connect(self._operation_finished)
        worker.signals.progress.connect(
            lambda current, total: self._update_progress(
                dialog, label_key="creator.import_progress", current=current, total=total
            )
        )
        self.thread_pool.start(worker)

    def _finish_import(self, result: object) -> None:
        imported, errors = result  # type: ignore[misc]
        had_pages = bool(self.book.pages)
        for path, width, height, _image_format, thumbnail in imported:
            page = ComicPage(
                source_path=path,
                source_width=width,
                source_height=height,
                is_cover=not had_pages and not self.book.pages,
            )
            self.book.pages.append(page)
            item = self._make_item(page, thumbnail)
            self.page_list.addItem(item)
        self._refresh_items()
        self.status_message.emit(self.i18n.tr("creator.import_complete", count=len(imported)))
        if errors:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(self.i18n.tr("creator.import_warning_title"))
            box.setText(self.i18n.tr("creator.import_warning", count=len(errors)))
            box.setDetailedText("\n".join(errors))
            box.exec()

    def _make_item(self, page: ComicPage, thumbnail: Path):
        from PySide6.QtWidgets import QListWidgetItem

        item = QListWidgetItem(QIcon(str(thumbnail)), "")
        item.setData(Qt.ItemDataRole.UserRole, page.page_id)
        item.setToolTip(str(page.source_path or ""))
        return item

    def _synchronize_order(self) -> None:
        by_id = {page.page_id: page for page in self.book.pages}
        ordered: list[ComicPage] = []
        for index in range(self.page_list.count()):
            page_id = str(self.page_list.item(index).data(Qt.ItemDataRole.UserRole))
            page = by_id.get(page_id)
            if page is not None:
                ordered.append(page)
        if len(ordered) == len(self.book.pages):
            self.book.pages = ordered
        self._refresh_items()

    def _refresh_items(self) -> None:
        by_id = {page.page_id: page for page in self.book.pages}
        for index in range(self.page_list.count()):
            item = self.page_list.item(index)
            page = by_id.get(str(item.data(Qt.ItemDataRole.UserRole)))
            if page is None:
                continue
            cover = self.i18n.tr("creator.cover_suffix") if page.is_cover else ""
            item.setText(
                self.i18n.tr(
                    "creator.page_item",
                    number=index + 1,
                    name=page.source_path.name if page.source_path else "",
                    cover=cover,
                )
            )
            item.setBackground(QBrush(QColor(SELECTION)) if page.is_cover else QBrush())
        self.count_label.setText(self.i18n.tr("creator.page_count", count=len(self.book.pages)))
        self._update_actions()

    def _selected_page_ids(self) -> set[str]:
        return {str(item.data(Qt.ItemDataRole.UserRole)) for item in self.page_list.selectedItems()}

    def _remove_selected(self) -> None:
        selected = self._selected_page_ids()
        if not selected:
            return
        cover_removed = any(page.is_cover and page.page_id in selected for page in self.book.pages)
        self.book.pages = [page for page in self.book.pages if page.page_id not in selected]
        for row in range(self.page_list.count() - 1, -1, -1):
            item = self.page_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)) in selected:
                self.page_list.takeItem(row)
        if cover_removed and self.book.pages:
            self.book.set_cover(self.book.pages[0].page_id)
        self._refresh_items()

    def _set_selected_cover(self) -> None:
        selected = self.page_list.selectedItems()
        if len(selected) != 1:
            return
        page_id = str(selected[0].data(Qt.ItemDataRole.UserRole))
        self.book.set_cover(page_id)
        self._refresh_items()

    def _edit_metadata(self) -> None:
        dialog = MetadataEditorDialog(self.i18n, copy.deepcopy(self.book.metadata), self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.book.metadata = dialog.result_metadata
            self.status_message.emit(self.i18n.tr("metadata.saved"))

    def _choose_export(self) -> None:
        if not self.book.pages or self._active_worker is not None:
            return
        default_path = self.settings.last_directory("creator_export") / "comic.apng"
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            self.i18n.tr("creator.export"),
            str(default_path),
            self.i18n.tr("files.apng_filter"),
        )
        if not selected:
            return
        output = Path(selected)
        if output.suffix.casefold() not in {".png", ".apng"}:
            output = output.with_suffix(".apng")
        overwrite = False
        if output.exists():
            answer = QMessageBox.question(
                self,
                self.i18n.tr("common.overwrite_title"),
                self.i18n.tr("common.overwrite_message", path=str(output)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        self.settings.set_last_directory("creator_export", output)
        self.book.cover_duration_ms = self.cover_duration.milliseconds()
        self.book.body_duration_ms = self.body_duration.milliseconds()
        self.book.reading_direction = str(self.direction_combo.currentData())  # type: ignore[assignment]
        self.settings.set_value("creator/cover_duration", self.book.cover_duration_ms)
        self.settings.set_value("creator/body_duration", self.book.body_duration_ms)
        export_book = copy.deepcopy(self.book)

        def task(cancel_event: Event, progress):
            return write_apng(
                export_book,
                output,
                overwrite=overwrite,
                progress=progress,
                cancel_event=cancel_event,
            )

        worker = Worker(task)
        self._active_worker = worker
        dialog = self._show_progress("creator.exporting", len(export_book.pages), worker)
        worker.signals.result.connect(self._export_complete)
        worker.signals.error.connect(self._worker_error)
        worker.signals.canceled.connect(
            lambda: self.status_message.emit(self.i18n.tr("common.cancelled"))
        )
        worker.signals.finished.connect(self._operation_finished)
        worker.signals.progress.connect(
            lambda current, total: self._update_progress(
                dialog, label_key="creator.export_progress", current=current, total=total
            )
        )
        self.thread_pool.start(worker)

    def _export_complete(self, result: object) -> None:
        output = Path(result)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(self.i18n.tr("creator.export_complete_title"))
        box.setText(self.i18n.tr("creator.export_complete", path=str(output)))
        box.exec()
        self.status_message.emit(self.i18n.tr("creator.export_complete", path=str(output)))

    def _show_progress(self, label_key: str, maximum: int, worker: Worker) -> QProgressDialog:
        dialog = QProgressDialog(
            self.i18n.tr(label_key),
            self.i18n.tr("common.cancel"),
            0,
            maximum,
            self,
        )
        dialog.setWindowTitle(self.i18n.tr(label_key))
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(worker.cancel)
        dialog.show()
        self._progress_dialog = dialog
        self._set_busy(True)
        return dialog

    def _update_progress(
        self,
        dialog: QProgressDialog,
        *,
        label_key: str,
        current: int,
        total: int,
    ) -> None:
        dialog.setValue(current)
        dialog.setLabelText(self.i18n.tr(label_key, current=current, total=total))

    def _worker_error(self, _error_type: str, details: str) -> None:
        show_error(self, self.i18n, "common.error_title", "common.operation_failed", details)

    def _operation_finished(self) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
        self._progress_dialog = None
        self._active_worker = None
        self._set_busy(False)
        self._update_actions()

    def _set_busy(self, busy: bool) -> None:
        self.import_files_button.setEnabled(not busy)
        self.import_folder_button.setEnabled(not busy)
        self.page_list.setEnabled(not busy)

    def _update_actions(self) -> None:
        selected_count = len(self.page_list.selectedItems())
        busy = self._active_worker is not None
        self.remove_button.setEnabled(selected_count > 0 and not busy)
        self.cover_button.setEnabled(selected_count == 1 and not busy)
        self.metadata_button.setEnabled(not busy)
        self.export_button.setEnabled(bool(self.book.pages) and not busy)
