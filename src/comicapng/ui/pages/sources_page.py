"""Source discovery, chapter selection, materialization, and Create integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from comicapng.core.apng_writer import write_apng
from comicapng.core.exceptions import OperationCancelledError
from comicapng.core.models import DEFAULT_BODY_DURATION_MS, DEFAULT_COVER_DURATION_MS, ComicBook
from comicapng.core.zip_archive import write_zip
from comicapng.i18n import I18n
from comicapng.plugins.api import (
    MaterializedChapter,
    SourceChapter,
    SourceComic,
    SourceSearchPage,
    SourceSearchResult,
)
from comicapng.plugins.errors import PluginCallError, PluginErrorCode
from comicapng.plugins.manager import PluginManager, PluginStatus
from comicapng.plugins.source_book import comic_book_from_source, safe_filename
from comicapng.plugins.workspace import SourceWorkspaceStore
from comicapng.services.settings import AppSettings
from comicapng.ui.dialogs.error_dialog import show_error
from comicapng.ui.icons import icon
from comicapng.ui.workers import Worker

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SourceWorkflowResult:
    workflow: str
    destination: Path
    workspace: Path | None = None
    book: ComicBook | None = None
    outputs: tuple[Path, ...] = ()
    chapter_count: int = 0


class SourcesPage(QWidget):
    status_message = Signal(str)
    open_in_create = Signal(object)

    def __init__(
        self,
        i18n: I18n,
        settings: AppSettings,
        plugin_manager: PluginManager,
        workspace_store: SourceWorkspaceStore,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.settings = settings
        self.plugin_manager = plugin_manager
        self.workspace_store = workspace_store
        self.thread_pool = QThreadPool.globalInstance()
        self.current_search: SourceSearchPage | None = None
        self.current_query = ""
        self.current_comic: SourceComic | None = None
        self.current_chapters: tuple[SourceChapter, ...] = ()
        self._active_worker: Worker | None = None
        self._progress_dialog: QProgressDialog | None = None
        self._initial_health_started = False
        self._build_ui()
        self.refresh_plugins()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        heading = QLabel(self.i18n.tr("sources.title"))
        heading.setObjectName("heading")
        root.addWidget(heading)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        plugin_panel = QFrame()
        plugin_panel.setObjectName("panel")
        plugin_layout = QVBoxLayout(plugin_panel)
        plugin_layout.addWidget(QLabel(self.i18n.tr("sources.plugins")))
        self.plugin_list = QListWidget()
        self.plugin_list.setAccessibleName(self.i18n.tr("sources.plugins"))
        plugin_layout.addWidget(self.plugin_list, 1)
        self.plugin_status = QLabel(self.i18n.tr("sources.status_not_checked"))
        self.plugin_status.setObjectName("muted")
        self.plugin_status.setWordWrap(True)
        plugin_layout.addWidget(self.plugin_status)
        splitter.addWidget(plugin_panel)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 0, 0, 0)
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(self.i18n.tr("sources.search_placeholder"))
        self.search_edit.setAccessibleName(self.i18n.tr("sources.search"))
        self.search_button = QToolButton()
        self.search_button.setObjectName("primary")
        self.search_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.search_button.setIcon(icon("search"))
        self.search_button.setText(self.i18n.tr("sources.search"))
        search_layout.addWidget(self.search_edit, 1)
        search_layout.addWidget(self.search_button)
        content_layout.addLayout(search_layout)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self._build_results_page())
        self.content_stack.addWidget(self._build_details_page())
        content_layout.addWidget(self.content_stack, 1)
        splitter.addWidget(content)
        splitter.setSizes([230, 850])

        self.plugin_list.currentItemChanged.connect(self._plugin_changed)
        self.search_button.clicked.connect(lambda: self._search(1))
        self.search_edit.returnPressed.connect(lambda: self._search(1))
        self.search_edit.textChanged.connect(lambda _text: self._update_actions())

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.results_label = QLabel(self.i18n.tr("sources.results_empty"))
        self.results_label.setObjectName("muted")
        layout.addWidget(self.results_label)
        self.results_list = QListWidget()
        self.results_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_list.setAccessibleName(self.i18n.tr("sources.results"))
        layout.addWidget(self.results_list, 1)
        footer = QHBoxLayout()
        self.previous_button = QPushButton(self.i18n.tr("sources.previous_page"))
        self.next_button = QPushButton(self.i18n.tr("sources.next_page"))
        self.page_label = QLabel(self.i18n.tr("sources.page_status", page=0, pages=0, total=0))
        self.open_details_button = QPushButton(self.i18n.tr("sources.open_details"))
        footer.addWidget(self.previous_button)
        footer.addWidget(self.next_button)
        footer.addWidget(self.page_label)
        footer.addStretch()
        footer.addWidget(self.open_details_button)
        layout.addLayout(footer)
        self.previous_button.clicked.connect(self._previous_page)
        self.next_button.clicked.connect(self._next_page)
        self.open_details_button.clicked.connect(self._open_selected_details)
        self.results_list.itemDoubleClicked.connect(lambda _item: self._open_selected_details())
        self.results_list.itemSelectionChanged.connect(self._update_actions)
        return page

    def _build_details_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.back_button = QPushButton(self.i18n.tr("sources.back_to_results"))
        header.addWidget(self.back_button)
        header.addStretch()
        layout.addLayout(header)

        summary = QHBoxLayout()
        self.cover_label = QLabel(self.i18n.tr("sources.cover_on_download"))
        self.cover_label.setObjectName("panel")
        self.cover_label.setFixedSize(150, 200)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setWordWrap(True)
        summary.addWidget(self.cover_label)
        details = QVBoxLayout()
        self.comic_title = QLabel()
        self.comic_title.setObjectName("heading")
        self.comic_title.setWordWrap(True)
        self.comic_author = QLabel()
        self.comic_author.setWordWrap(True)
        self.comic_tags = QLabel()
        self.comic_tags.setWordWrap(True)
        self.comic_description = QLabel()
        self.comic_description.setWordWrap(True)
        self.comic_description.setAlignment(Qt.AlignmentFlag.AlignTop)
        details.addWidget(self.comic_title)
        details.addWidget(self.comic_author)
        details.addWidget(self.comic_tags)
        details.addWidget(self.comic_description, 1)
        summary.addLayout(details, 1)
        layout.addLayout(summary)

        chapter_header = QHBoxLayout()
        chapter_header.addWidget(QLabel(self.i18n.tr("sources.chapters")))
        self.select_all_button = QPushButton(self.i18n.tr("sources.select_all"))
        self.select_none_button = QPushButton(self.i18n.tr("sources.select_none"))
        chapter_header.addStretch()
        chapter_header.addWidget(self.select_all_button)
        chapter_header.addWidget(self.select_none_button)
        layout.addLayout(chapter_header)
        self.chapter_list = QListWidget()
        self.chapter_list.setAccessibleName(self.i18n.tr("sources.chapters"))
        layout.addWidget(self.chapter_list, 1)

        options = QHBoxLayout()
        self.include_cover = QCheckBox(self.i18n.tr("sources.include_cover"))
        self.include_cover.setChecked(
            self.settings.boolean(
                "plugins/org.comicapng.source.jmcomic/include_cover",
                True,
            )
        )
        options.addWidget(self.include_cover)
        options.addStretch()
        options.addWidget(QLabel(self.i18n.tr("sources.pack_mode")))
        self.pack_mode = QComboBox()
        self.pack_mode.addItem(self.i18n.tr("sources.pack_combined"), "combined")
        self.pack_mode.addItem(self.i18n.tr("sources.pack_per_chapter"), "per_chapter")
        options.addWidget(self.pack_mode)
        layout.addLayout(options)

        actions = QHBoxLayout()
        self.download_button = QPushButton(self.i18n.tr("sources.download"))
        self.download_all_button = QPushButton(self.i18n.tr("sources.download_all"))
        self.open_create_button = QPushButton(self.i18n.tr("sources.open_in_create"))
        self.open_create_button.setObjectName("primary")
        self.pack_button = QPushButton(self.i18n.tr("sources.download_and_pack"))
        self.zip_button = QPushButton(icon("archive"), self.i18n.tr("sources.export_zip"))
        actions.addWidget(self.download_button)
        actions.addWidget(self.download_all_button)
        actions.addStretch()
        actions.addWidget(self.open_create_button)
        actions.addWidget(self.zip_button)
        actions.addWidget(self.pack_button)
        layout.addLayout(actions)

        self.back_button.clicked.connect(lambda: self.content_stack.setCurrentIndex(0))
        self.select_all_button.clicked.connect(self._select_all_chapters)
        self.select_none_button.clicked.connect(self._select_no_chapters)
        self.chapter_list.itemChanged.connect(lambda _item: self._update_actions())
        self.download_button.clicked.connect(self._download_selected)
        self.download_all_button.clicked.connect(self._download_all)
        self.open_create_button.clicked.connect(self._open_selected_in_create)
        self.zip_button.clicked.connect(self._export_zip)
        self.pack_button.clicked.connect(self._download_and_pack)
        return page

    def refresh_plugins(self) -> None:
        selected = self._selected_plugin_id()
        self.plugin_list.blockSignals(True)
        self.plugin_list.clear()
        selected_row = 0
        for row, status in enumerate(self.plugin_manager.statuses()):
            suffix = self.i18n.tr("sources.official_suffix") if status.manifest.official else ""
            item = QListWidgetItem(
                self.i18n.tr(
                    "sources.plugin_item",
                    name=status.manifest.name,
                    version=status.manifest.version,
                    official=suffix,
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, status.manifest.plugin_id)
            self.plugin_list.addItem(item)
            if status.manifest.plugin_id == selected:
                selected_row = row
        self.plugin_list.blockSignals(False)
        if self.plugin_list.count():
            self.plugin_list.setCurrentRow(selected_row)
            if self.isVisible():
                self._plugin_changed(self.plugin_list.currentItem(), None)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._initial_health_started and self.plugin_list.currentItem() is not None:
            self._initial_health_started = True
            self._plugin_changed(self.plugin_list.currentItem(), None)

    def _selected_plugin_id(self) -> str | None:
        item = self.plugin_list.currentItem()
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole))

    def _plugin_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None or self._active_worker is not None:
            return
        plugin_id = str(current.data(Qt.ItemDataRole.UserRole))
        self.include_cover.setChecked(
            self.settings.boolean(f"plugins/{plugin_id}/include_cover", True)
        )
        self.current_search = None
        self.current_comic = None
        self.current_chapters = ()
        self.results_list.clear()
        self.content_stack.setCurrentIndex(0)
        self.plugin_status.setText(self.i18n.tr("sources.status_checking"))

        def task(_cancel_event: Event, _progress):
            return self.plugin_manager.health(plugin_id)

        self._run_worker(task, self._health_complete, progress_key=None)

    def _health_complete(self, result: object) -> None:
        status = result
        if not isinstance(status, PluginStatus):
            return
        if status.available:
            version = (
                self.i18n.tr("sources.dependency_version", version=status.dependency_version)
                if status.dependency_version
                else ""
            )
            self.plugin_status.setText(
                self.i18n.tr("sources.status_available", message=status.message, version=version)
            )
        else:
            self.plugin_status.setText(
                self.i18n.tr("sources.status_unavailable", message=status.message)
            )
        self._update_actions()

    def _search(self, page: int) -> None:
        plugin_id = self._selected_plugin_id()
        query = self.search_edit.text().strip()
        if plugin_id is None or not query or self._active_worker is not None:
            return
        if page == 1:
            self.current_query = query

        def task(cancel_event: Event, _progress):
            return self.plugin_manager.search(
                plugin_id,
                self.current_query,
                page,
                cancel_event=cancel_event,
            )

        self._run_worker(task, self._search_complete, progress_key="sources.searching")

    def _search_complete(self, result: object) -> None:
        if not isinstance(result, SourceSearchPage):
            return
        self.current_search = result
        self.results_list.clear()
        for search_result in result.items:
            tags = ", ".join(search_result.tags)
            item = QListWidgetItem(
                self.i18n.tr(
                    "sources.result_item",
                    title=search_result.title,
                    source_id=search_result.source_id,
                    tags=tags,
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, search_result.to_dict())
            self.results_list.addItem(item)
        self.results_label.setText(
            self.i18n.tr("sources.results_count", count=len(result.items))
            if result.items
            else self.i18n.tr("sources.results_empty")
        )
        self.page_label.setText(
            self.i18n.tr(
                "sources.page_status",
                page=result.page,
                pages=result.page_count,
                total=result.total,
            )
        )
        self.status_message.emit(
            self.i18n.tr("sources.search_complete", count=len(result.items))
        )
        self._update_actions()

    def _previous_page(self) -> None:
        if self.current_search is not None and self.current_search.page > 1:
            self._search(self.current_search.page - 1)

    def _next_page(self) -> None:
        if (
            self.current_search is not None
            and self.current_search.page < self.current_search.page_count
        ):
            self._search(self.current_search.page + 1)

    def _selected_result(self) -> SourceSearchResult | None:
        item = self.results_list.currentItem()
        if item is None:
            return None
        try:
            return SourceSearchResult.from_dict(item.data(Qt.ItemDataRole.UserRole))
        except ValueError:
            return None

    def _open_selected_details(self) -> None:
        result = self._selected_result()
        if result is None or self._active_worker is not None:
            return
        preview_task_id = f"cover-{uuid4().hex}"
        preview_workspace = self.workspace_store.create(result.plugin_id, preview_task_id)

        def task(cancel_event: Event, progress):
            try:
                comic = self.plugin_manager.get_comic(
                    result.plugin_id,
                    result.source_id,
                    cancel_event=cancel_event,
                )
                progress(1, 3)
                chapters = self.plugin_manager.get_chapters(
                    result.plugin_id,
                    result.source_id,
                    cancel_event=cancel_event,
                )
                progress(2, 3)
                cover_path = None
                cover_error = None
                if comic.cover_ref:
                    try:
                        cover_path = self.plugin_manager.materialize_cover(
                            result.plugin_id,
                            result.source_id,
                            preview_workspace,
                            task_id=preview_task_id,
                            cancel_event=cancel_event,
                        )
                    except PluginCallError as exc:
                        if exc.error.code == PluginErrorCode.CANCELLED:
                            raise
                        cover_error = exc.error.message
                progress(3, 3)
                if cover_path is None:
                    self._cleanup_workspace(preview_workspace)
                return comic, chapters, cover_path, preview_workspace, cover_error
            except Exception:
                self._cleanup_workspace(preview_workspace)
                raise

        self._run_worker(
            task,
            self._details_complete,
            progress_key="sources.loading_details",
            maximum=3,
        )

    def _details_complete(self, result: object) -> None:
        comic, chapters, cover_path, preview_workspace, cover_error = result  # type: ignore[misc]
        if not isinstance(comic, SourceComic):
            return
        self.current_comic = comic
        self.current_chapters = tuple(chapters)
        self.comic_title.setText(comic.title)
        self.comic_author.setText(
            self.i18n.tr("sources.author", value=", ".join(comic.authors) or self.i18n.tr("common.not_available"))
        )
        self.comic_tags.setText(
            self.i18n.tr("sources.tags", value=", ".join(comic.tags) or self.i18n.tr("common.not_available"))
        )
        self.comic_description.setText(comic.description or self.i18n.tr("common.not_available"))
        self.cover_label.setPixmap(QPixmap())
        if isinstance(cover_path, Path):
            self.workspace_store.retain(preview_workspace)
            pixmap = QPixmap(str(cover_path))
            self.cover_label.setPixmap(
                pixmap.scaled(
                    self.cover_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.cover_label.setText(self.i18n.tr("common.not_available"))
            if cover_error:
                self.status_message.emit(self.i18n.tr("sources.cover_unavailable"))
        self.chapter_list.blockSignals(True)
        self.chapter_list.clear()
        for chapter in self.current_chapters:
            item = QListWidgetItem(
                self.i18n.tr(
                    "sources.chapter_item",
                    index=chapter.index,
                    title=chapter.title,
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, chapter.to_dict())
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.chapter_list.addItem(item)
        self.chapter_list.blockSignals(False)
        self.content_stack.setCurrentIndex(1)
        self._update_actions()

    def _select_all_chapters(self) -> None:
        self.chapter_list.blockSignals(True)
        for row in range(self.chapter_list.count()):
            self.chapter_list.item(row).setCheckState(Qt.CheckState.Checked)
        self.chapter_list.blockSignals(False)
        self._update_actions()

    def _select_no_chapters(self) -> None:
        self.chapter_list.blockSignals(True)
        for row in range(self.chapter_list.count()):
            self.chapter_list.item(row).setCheckState(Qt.CheckState.Unchecked)
        self.chapter_list.blockSignals(False)
        self._update_actions()

    def _selected_chapters(self) -> tuple[SourceChapter, ...]:
        result: list[SourceChapter] = []
        for row in range(self.chapter_list.count()):
            item = self.chapter_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(SourceChapter.from_dict(item.data(Qt.ItemDataRole.UserRole)))
        return tuple(result)

    def _download_all(self) -> None:
        self._select_all_chapters()
        self._download_selected()

    def _download_selected(self) -> None:
        chapters = self._selected_chapters()
        comic = self.current_comic
        if comic is None or not chapters:
            return
        selected = QFileDialog.getExistingDirectory(
            self,
            self.i18n.tr("sources.choose_download_folder"),
            str(self.settings.last_directory("source_download")),
        )
        if not selected:
            return
        destination = Path(selected)
        self.settings.set_last_directory("source_download", destination)
        root = destination / safe_filename(comic.title)
        if not self._confirm_operation(chapters, root, "sources.download_behavior"):
            return
        self._start_source_workflow("download", chapters, root)

    def _open_selected_in_create(self) -> None:
        chapters = self._selected_chapters()
        comic = self.current_comic
        if comic is None or not chapters:
            return
        if not self._confirm_operation(chapters, None, "sources.open_create_behavior"):
            return
        self._start_source_workflow("create", chapters, None)

    def _download_and_pack(self) -> None:
        chapters = self._selected_chapters()
        comic = self.current_comic
        if comic is None or not chapters:
            return
        mode = str(self.pack_mode.currentData())
        if mode == "combined":
            default = self.settings.last_directory("source_pack") / f"{safe_filename(comic.title)}.apng"
            selected, _filter = QFileDialog.getSaveFileName(
                self,
                self.i18n.tr("sources.download_and_pack"),
                str(default),
                self.i18n.tr("files.apng_filter"),
            )
            if not selected:
                return
            destination = Path(selected)
            if destination.suffix.casefold() not in {".png", ".apng"}:
                destination = destination.with_suffix(".apng")
            if destination.exists() and not self._confirm_overwrite(destination):
                return
        else:
            selected = QFileDialog.getExistingDirectory(
                self,
                self.i18n.tr("sources.choose_pack_folder"),
                str(self.settings.last_directory("source_pack")),
            )
            if not selected:
                return
            destination = Path(selected)
            outputs = self._per_chapter_outputs(destination, chapters)
            existing = [path for path in outputs if path.exists()]
            if existing and not self._confirm_multiple_overwrite(len(existing)):
                return
        self.settings.set_last_directory("source_pack", destination)
        if not self._confirm_operation(chapters, destination, "sources.pack_behavior"):
            return
        self._start_source_workflow("pack", chapters, destination, pack_mode=mode)

    def _export_zip(self) -> None:
        chapters = self._selected_chapters()
        comic = self.current_comic
        if comic is None or not chapters:
            return
        default = self.settings.last_directory("source_zip") / f"{safe_filename(comic.title)}.zip"
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            self.i18n.tr("sources.export_zip"),
            str(default),
            self.i18n.tr("files.zip_filter"),
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.casefold() != ".zip":
            destination = destination.with_suffix(".zip")
        if destination.exists() and not self._confirm_overwrite(destination):
            return
        self.settings.set_last_directory("source_zip", destination)
        if not self._confirm_operation(chapters, destination, "sources.zip_behavior"):
            return
        self._start_source_workflow("zip", chapters, destination)

    def _confirm_operation(
        self,
        chapters: tuple[SourceChapter, ...],
        destination: Path | None,
        behavior_key: str,
    ) -> bool:
        destination_text = str(destination) if destination is not None else self.i18n.tr(
            "sources.temporary_destination"
        )
        answer = QMessageBox.question(
            self,
            self.i18n.tr("sources.confirm_title"),
            self.i18n.tr(
                "sources.confirm_message",
                count=len(chapters),
                destination=destination_text,
                behavior=self.i18n.tr(behavior_key),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_overwrite(self, path: Path) -> bool:
        answer = QMessageBox.question(
            self,
            self.i18n.tr("common.overwrite_title"),
            self.i18n.tr("common.overwrite_message", path=str(path)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_multiple_overwrite(self, count: int) -> bool:
        answer = QMessageBox.question(
            self,
            self.i18n.tr("common.overwrite_title"),
            self.i18n.tr("sources.overwrite_multiple", count=count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _start_source_workflow(
        self,
        workflow: str,
        chapters: tuple[SourceChapter, ...],
        destination: Path | None,
        *,
        pack_mode: str = "combined",
    ) -> None:
        comic = self.current_comic
        plugin_id = self._selected_plugin_id()
        if comic is None or plugin_id is None:
            return
        include_cover = self.include_cover.isChecked()
        self.settings.set_value(
            f"plugins/{plugin_id}/include_cover",
            include_cover,
        )
        task_id = uuid4().hex
        workspace: Path | None = None
        if workflow in {"create", "pack", "zip"}:
            workspace = self.workspace_store.create(plugin_id, task_id)
            materialization_root = workspace
        else:
            if destination is None:
                return
            materialization_root = destination.resolve()
        source_name = self.plugin_manager.discovered[plugin_id].manifest.name
        cover_duration = self.settings.integer(
            "creator/cover_duration", DEFAULT_COVER_DURATION_MS
        )
        body_duration = self.settings.integer("creator/body_duration", DEFAULT_BODY_DURATION_MS)

        def task(cancel_event: Event, progress):
            try:
                materialized: list[MaterializedChapter] = []
                for index, chapter in enumerate(chapters):
                    if cancel_event.is_set():
                        raise OperationCancelledError("Source materialization was cancelled")
                    chapter_directory = materialization_root / safe_filename(
                        f"{chapter.index:03d}-{chapter.title}",
                        f"chapter-{chapter.index}",
                    )
                    result = self.plugin_manager.materialize_chapter(
                        chapter,
                        chapter_directory,
                        include_cover=include_cover and index == 0,
                        task_id=task_id,
                        cancel_event=cancel_event,
                    )
                    materialized.append(result)
                    progress(index + 1, len(chapters))

                if workflow == "download":
                    return SourceWorkflowResult(
                        workflow,
                        materialization_root,
                        chapter_count=len(materialized),
                    )
                if workflow == "create":
                    book = comic_book_from_source(
                        comic,
                        source_name,
                        tuple(materialized),
                        include_cover=include_cover,
                        cover_duration_ms=cover_duration,
                        body_duration_ms=body_duration,
                    )
                    return SourceWorkflowResult(
                        workflow,
                        materialization_root,
                        workspace=workspace,
                        book=book,
                        chapter_count=len(materialized),
                    )

                if workflow == "zip":
                    if destination is None:
                        raise ValueError("ZIP destination is missing")
                    book = comic_book_from_source(
                        comic,
                        source_name,
                        tuple(materialized),
                        include_cover=include_cover,
                        cover_duration_ms=cover_duration,
                        body_duration_ms=body_duration,
                    )
                    write_zip(
                        book,
                        destination,
                        overwrite=destination.exists(),
                        cancel_event=cancel_event,
                    )
                    return SourceWorkflowResult(
                        workflow,
                        destination,
                        workspace=workspace,
                        outputs=(destination,),
                        chapter_count=len(materialized),
                    )

                outputs: list[Path] = []
                if destination is None:
                    raise ValueError("Pack destination is missing")
                if pack_mode == "combined":
                    book = comic_book_from_source(
                        comic,
                        source_name,
                        tuple(materialized),
                        include_cover=include_cover,
                        cover_duration_ms=cover_duration,
                        body_duration_ms=body_duration,
                    )
                    write_apng(
                        book,
                        destination,
                        overwrite=destination.exists(),
                        cancel_event=cancel_event,
                    )
                    outputs.append(destination)
                else:
                    cover_path = next(
                        (item.cover_path for item in materialized if item.cover_path is not None),
                        None,
                    )
                    per_chapter_paths = self._per_chapter_outputs(destination, chapters)
                    for item, output in zip(materialized, per_chapter_paths, strict=True):
                        single = replace(item, cover_path=cover_path if include_cover else None)
                        chapter_comic = replace(
                            comic,
                            title=f"{comic.title} - {item.chapter.title}",
                            chapter_count=1,
                        )
                        book = comic_book_from_source(
                            chapter_comic,
                            source_name,
                            (single,),
                            include_cover=include_cover,
                            cover_duration_ms=cover_duration,
                            body_duration_ms=body_duration,
                        )
                        write_apng(
                            book,
                            output,
                            overwrite=output.exists(),
                            cancel_event=cancel_event,
                        )
                        outputs.append(output)
                return SourceWorkflowResult(
                    workflow,
                    destination,
                    workspace=workspace,
                    outputs=tuple(outputs),
                    chapter_count=len(materialized),
                )
            except Exception:
                if workspace is not None:
                    self._cleanup_workspace(workspace)
                raise

        self._run_worker(
            task,
            self._workflow_complete,
            progress_key="sources.materializing",
            maximum=len(chapters),
        )

    @staticmethod
    def _per_chapter_outputs(
        destination: Path,
        chapters: tuple[SourceChapter, ...],
    ) -> tuple[Path, ...]:
        return tuple(
            destination
            / f"{safe_filename(f'{chapter.index:03d}-{chapter.title}', f'chapter-{chapter.index}')}.apng"
            for chapter in chapters
        )

    def _workflow_complete(self, result: object) -> None:
        if not isinstance(result, SourceWorkflowResult):
            return
        if result.workflow == "create" and result.book is not None:
            if result.workspace is not None:
                self.workspace_store.retain(result.workspace)
            self.open_in_create.emit(result.book)
            self.status_message.emit(
                self.i18n.tr("sources.open_create_complete", count=len(result.book.pages))
            )
            return
        if result.workspace is not None:
            self._cleanup_workspace(result.workspace)
        if result.workflow == "pack":
            paths = "\n".join(str(path) for path in result.outputs)
            QMessageBox.information(
                self,
                self.i18n.tr("sources.pack_complete_title"),
                self.i18n.tr("sources.pack_complete", count=len(result.outputs), paths=paths),
            )
            self.status_message.emit(
                self.i18n.tr("sources.pack_complete_status", count=len(result.outputs))
            )
        elif result.workflow == "zip":
            QMessageBox.information(
                self,
                self.i18n.tr("sources.zip_complete_title"),
                self.i18n.tr("sources.zip_complete", path=str(result.destination)),
            )
            self.status_message.emit(
                self.i18n.tr("sources.zip_complete_status")
            )
        else:
            QMessageBox.information(
                self,
                self.i18n.tr("sources.download_complete_title"),
                self.i18n.tr(
                    "sources.download_complete",
                    count=result.chapter_count,
                    path=str(result.destination),
                ),
            )
            self.status_message.emit(
                self.i18n.tr("sources.download_complete_status", count=result.chapter_count)
            )

    def _run_worker(
        self,
        function,
        result_handler,
        *,
        progress_key: str | None,
        maximum: int = 0,
    ) -> None:
        if self._active_worker is not None:
            return

        def guarded(cancel_event: Event, progress):
            try:
                return function(cancel_event, progress)
            except PluginCallError as exc:
                if exc.error.code == PluginErrorCode.CANCELLED:
                    raise OperationCancelledError(exc.error.message) from exc
                raise

        worker = Worker(guarded)
        self._active_worker = worker
        worker.signals.result.connect(result_handler)
        worker.signals.error.connect(self._worker_error)
        worker.signals.canceled.connect(
            lambda: self.status_message.emit(self.i18n.tr("common.cancelled"))
        )
        worker.signals.finished.connect(self._operation_finished)
        if progress_key is not None:
            dialog = QProgressDialog(
                self.i18n.tr(progress_key, current=0, total=maximum),
                self.i18n.tr("common.cancel"),
                0,
                maximum,
                self,
            )
            dialog.setWindowTitle(self.i18n.tr(progress_key, current=0, total=maximum))
            dialog.setWindowModality(Qt.WindowModality.WindowModal)
            dialog.setMinimumDuration(0)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.canceled.connect(worker.cancel)
            worker.signals.progress.connect(
                lambda current, total: self._update_progress(
                    dialog, progress_key, current, total
                )
            )
            dialog.show()
            self._progress_dialog = dialog
        self._set_busy(True)
        self.thread_pool.start(worker)

    def _update_progress(
        self,
        dialog: QProgressDialog,
        label_key: str,
        current: int,
        total: int,
    ) -> None:
        if dialog.maximum() != total:
            dialog.setMaximum(total)
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
        self.plugin_list.setEnabled(not busy)
        self.search_edit.setEnabled(not busy)
        self.results_list.setEnabled(not busy)
        self.chapter_list.setEnabled(not busy)

    def _update_actions(self) -> None:
        busy = self._active_worker is not None
        plugin_id = self._selected_plugin_id()
        status = self.plugin_manager.health_cache.get(plugin_id or "")
        available = bool(status and status.available)
        self.search_button.setEnabled(available and not busy and bool(self.search_edit.text().strip()))
        selected_result = self._selected_result() is not None
        self.open_details_button.setEnabled(selected_result and not busy)
        if self.current_search is None:
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
        else:
            self.previous_button.setEnabled(self.current_search.page > 1 and not busy)
            self.next_button.setEnabled(
                self.current_search.page < self.current_search.page_count and not busy
            )
        selected_chapters = bool(self._selected_chapters())
        for button in (
            self.download_button,
            self.open_create_button,
            self.zip_button,
            self.pack_button,
        ):
            button.setEnabled(selected_chapters and not busy)
        self.download_all_button.setEnabled(bool(self.current_chapters) and not busy)
        self.select_all_button.setEnabled(bool(self.current_chapters) and not busy)
        self.select_none_button.setEnabled(bool(self.current_chapters) and not busy)

    def _cleanup_workspace(self, path: Path) -> None:
        try:
            self.workspace_store.cleanup(path)
        except OSError:
            LOGGER.warning("Could not clean source workspace: %s", path, exc_info=True)
