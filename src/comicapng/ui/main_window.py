"""The single ComicAPNG application window."""

from __future__ import annotations

from platformdirs import user_cache_path
from PySide6.QtCore import QRect, QSize, Qt, QThreadPool
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from comicapng import __version__
from comicapng.core.models import DEFAULT_BODY_DURATION_MS, DEFAULT_COVER_DURATION_MS, ComicBook
from comicapng.i18n import I18n
from comicapng.plugins.manager import PluginManager
from comicapng.plugins.workspace import SourceWorkspaceStore, WorkspaceStore
from comicapng.services.settings import AppSettings
from comicapng.services.thumbnail_cache import ThumbnailCache
from comicapng.ui.dialogs.preferences_dialog import PreferencesDialog
from comicapng.ui.icons import accent_icon, icon
from comicapng.ui.pages.creator_page import CreatorPage
from comicapng.ui.pages.extractor_page import ExtractorPage
from comicapng.ui.pages.reader_page import ReaderPage
from comicapng.ui.pages.sources_page import SourcesPage


class MainWindow(QMainWindow):
    """One main window containing all four application workflows."""

    def __init__(self, i18n: I18n, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.settings = settings
        self.thumbnail_cache = ThumbnailCache()
        self.plugin_manager = PluginManager(settings)
        self.source_workspaces = SourceWorkspaceStore()
        self.document_workspaces = WorkspaceStore(
            user_cache_path("ComicAPNG", appauthor=False) / "imports"
        )
        self._fullscreen = False
        self._was_maximized_before_fullscreen = False
        self._pre_fullscreen_normal_geometry: QRect | None = None
        self.restore_maximized = settings.boolean("window/maximized", False)
        self.setWindowTitle(i18n.tr("app.name"))
        self.setWindowIcon(accent_icon("book"))
        self.setMinimumSize(960, 640)
        self._restore_window_geometry()
        self._build_ui()
        self._build_menus()
        self.statusBar().showMessage(i18n.tr("status.ready"))

    @staticmethod
    def _geometry_is_visible(
        geometry: QRect,
        screens: list[QRect] | tuple[QRect, ...],
    ) -> bool:
        if not geometry.isValid() or geometry.width() < 100 or geometry.height() < 80:
            return False
        required_width = min(160, geometry.width())
        required_height = min(80, geometry.height())
        return any(
            geometry.intersected(screen).width() >= required_width
            and geometry.intersected(screen).height() >= required_height
            for screen in screens
        )

    def _restore_window_geometry(self) -> None:
        available = [screen.availableGeometry() for screen in QGuiApplication.screens()]
        saved = self.settings.value("window/normal_geometry")
        if isinstance(saved, QRect):
            if self._geometry_is_visible(saved, available):
                self.setGeometry(saved)
            else:
                self.resize(1280, 820)
            return
        width = max(self.minimumWidth(), self.settings.integer("window/width", 1280))
        height = max(self.minimumHeight(), self.settings.integer("window/height", 820))
        self.resize(width, height)

    def _save_window_geometry(self) -> None:
        maximized = (
            self._was_maximized_before_fullscreen if self._fullscreen else self.isMaximized()
        )
        if self._fullscreen and self._pre_fullscreen_normal_geometry is not None:
            normal_geometry = self._pre_fullscreen_normal_geometry
        elif self.isMaximized():
            normal_geometry = self.normalGeometry()
        else:
            normal_geometry = self.geometry()
        if normal_geometry.isValid():
            self.settings.set_value("window/normal_geometry", normal_geometry)
            self.settings.set_value("window/width", normal_geometry.width())
            self.settings.set_value("window/height", normal_geometry.height())
        self.settings.set_value("window/maximized", maximized)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(160)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 18, 10, 12)
        sidebar_layout.setSpacing(8)
        brand = QLabel(self.i18n.tr("app.name"))
        brand.setObjectName("heading")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(brand)
        sidebar_layout.addSpacing(14)

        self.navigation = QButtonGroup(self)
        self.navigation.setExclusive(True)
        destinations = (
            ("sources", "nav.sources"),
            ("create", "nav.create"),
            ("extract", "nav.extract"),
            ("read", "nav.read"),
        )
        for index, (icon_name, key) in enumerate(destinations):
            button = QToolButton()
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setIcon(icon(icon_name))
            button.setIconSize(QSize(20, 20))
            button.setText(self.i18n.tr(key))
            button.setAccessibleName(self.i18n.tr(key))
            button.setMinimumHeight(42)
            sidebar_layout.addWidget(button)
            self.navigation.addButton(button, index)
            if index == 0:
                button.setChecked(True)
        sidebar_layout.addStretch()
        version = QLabel(self.i18n.tr("app.version", version=__version__))
        version.setObjectName("muted")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(version)
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.sources_page = SourcesPage(
            self.i18n,
            self.settings,
            self.plugin_manager,
            self.source_workspaces,
        )
        self.creator_page = CreatorPage(
            self.i18n,
            self.settings,
            self.thumbnail_cache,
            self.document_workspaces,
        )
        self.extractor_page = ExtractorPage(self.i18n, self.settings)
        self.reader_page = ReaderPage(
            self.i18n,
            self.settings,
            self.thumbnail_cache,
        )
        self.stack.addWidget(self.sources_page)
        self.stack.addWidget(self.creator_page)
        self.stack.addWidget(self.extractor_page)
        self.stack.addWidget(self.reader_page)
        layout.addWidget(self.stack, 1)
        self.navigation.idClicked.connect(self.stack.setCurrentIndex)

        for page in (
            self.sources_page,
            self.creator_page,
            self.extractor_page,
            self.reader_page,
        ):
            page.status_message.connect(self.statusBar().showMessage)
        self.sources_page.open_in_create.connect(self._open_source_book)
        self.reader_page.fullscreen_toggle_requested.connect(self.toggle_fullscreen)
        self.reader_page.fullscreen_exit_requested.connect(self.exit_fullscreen)
        self.reader_page.book_opened.connect(self._set_book_title)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu(self.i18n.tr("menu.file"))
        quit_action = QAction(icon("cancel"), self.i18n.tr("menu.quit"), self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        preferences_action = QAction(icon("settings"), self.i18n.tr("preferences.title"), self)
        preferences_action.triggered.connect(self._show_preferences)
        file_menu.insertAction(quit_action, preferences_action)
        file_menu.insertSeparator(quit_action)

        view_menu = self.menuBar().addMenu(self.i18n.tr("menu.view"))
        fullscreen_action = QAction(icon("fullscreen"), self.i18n.tr("reader.fullscreen"), self)
        fullscreen_action.setShortcut("F11")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen_action)

        language_menu = self.menuBar().addMenu(self.i18n.tr("menu.language"))
        language_group = QActionGroup(self)
        for locale_name, text_key in (("en", "language.english"), ("zh_CN", "language.chinese")):
            action = QAction(self.i18n.tr(text_key), self)
            action.setCheckable(True)
            action.setData(locale_name)
            action.setChecked(self.i18n.locale_name == locale_name)
            action.triggered.connect(lambda _checked, value=locale_name: self._set_language(value))
            language_group.addAction(action)
            language_menu.addAction(action)

        help_menu = self.menuBar().addMenu(self.i18n.tr("menu.help"))
        about_action = QAction(icon("about"), self.i18n.tr("menu.about"), self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _set_language(self, locale_name: str) -> None:
        self.settings.set_value("ui/language", locale_name)
        QMessageBox.information(
            self,
            self.i18n.tr("language.changed_title"),
            self.i18n.tr("language.changed_message"),
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            self.i18n.tr("about.title"),
            self.i18n.tr("about.body", version=__version__),
        )

    def _show_preferences(self) -> None:
        dialog = PreferencesDialog(
            self.i18n,
            self.settings,
            self,
            plugin_manager=self.plugin_manager,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        thumbnail_size = self.settings.integer("creator/thumbnail_size", 170)
        self.creator_page.page_list.setIconSize(QSize(thumbnail_size, thumbnail_size))
        self.creator_page.page_list.setGridSize(QSize(thumbnail_size + 36, thumbnail_size + 60))
        self.creator_page.cover_duration.set_milliseconds(
            self.settings.integer("creator/cover_duration", DEFAULT_COVER_DURATION_MS)
        )
        self.creator_page.body_duration.set_milliseconds(
            self.settings.integer("creator/body_duration", DEFAULT_BODY_DURATION_MS)
        )
        self.reader_page.viewer.set_background_color(
            str(self.settings.value("reader/background", "#15181d"))
        )
        self.sources_page.include_cover.setChecked(
            self.settings.boolean(
                "plugins/org.comicapng.source.jmcomic/include_cover",
                True,
            )
        )
        self.sources_page.refresh_plugins()
        self.statusBar().showMessage(self.i18n.tr("preferences.saved"))

    def _open_source_book(self, value: object) -> None:
        if not isinstance(value, ComicBook):
            return
        if self.creator_page.book.pages:
            answer = QMessageBox.question(
                self,
                self.i18n.tr("sources.replace_create_title"),
                self.i18n.tr("sources.replace_create_message"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if not self.creator_page.load_book(value):
            self.statusBar().showMessage(self.i18n.tr("sources.create_busy"))
            return
        self.stack.setCurrentIndex(1)
        creator_button = self.navigation.button(1)
        if creator_button is not None:
            creator_button.setChecked(True)

    def _set_book_title(self, filename: str) -> None:
        self.setWindowTitle(self.i18n.tr("app.book_title", filename=filename))

    def toggle_fullscreen(self) -> None:
        if self._fullscreen:
            self.exit_fullscreen()
            return
        self._was_maximized_before_fullscreen = self.isMaximized()
        self._pre_fullscreen_normal_geometry = (
            self.normalGeometry() if self.isMaximized() else self.geometry()
        )
        self._fullscreen = True
        self.sidebar.hide()
        self.menuBar().hide()
        self.statusBar().hide()
        self.showFullScreen()

    def exit_fullscreen(self) -> None:
        if not self._fullscreen:
            return
        self._fullscreen = False
        self.sidebar.show()
        self.menuBar().show()
        self.statusBar().show()
        if self._was_maximized_before_fullscreen:
            self.showMaximized()
        else:
            self.showNormal()
        self._pre_fullscreen_normal_geometry = None

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_window_geometry()
        self.settings.sync()
        if self.reader_page.frame_cache is not None:
            self.reader_page.frame_cache.clear()
        if self.sources_page._active_worker is not None:
            self.sources_page._active_worker.cancel()
        self.creator_page.prepare_to_close()
        QThreadPool.globalInstance().waitForDone(5000)
        self.plugin_manager.close()
        self.source_workspaces.close()
        self.document_workspaces.close()
        super().closeEvent(event)
