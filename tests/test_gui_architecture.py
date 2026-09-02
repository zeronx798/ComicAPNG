"""Smoke tests for the one-window, four-page Qt architecture."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMainWindow

from comicapng.i18n import I18n
from comicapng.services.settings import AppSettings
from comicapng.ui.main_window import MainWindow
from comicapng.ui.pages.creator_page import CreatorPage
from comicapng.ui.pages.extractor_page import ExtractorPage
from comicapng.ui.pages.reader_page import ReaderPage
from comicapng.ui.pages.sources_page import SourcesPage


def test_one_main_window_contains_all_workflow_pages(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    backend = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(I18n("en"), AppSettings(backend))
    try:
        assert isinstance(window, QMainWindow)
        assert window.stack.count() == 4
        assert isinstance(window.stack.widget(0), SourcesPage)
        assert isinstance(window.stack.widget(1), CreatorPage)
        assert isinstance(window.stack.widget(2), ExtractorPage)
        assert isinstance(window.stack.widget(3), ReaderPage)
        assert window.windowTitle() == "ComicAPNG"
        assert window.creator_page.import_apng_button.text() == "Import APNG"
        assert window.creator_page.import_zip_button.text() == "Import ZIP"
        assert window.creator_page.export_zip_button.text() == "Export ZIP"
        assert window.sources_page.zip_button.text() == "Export ZIP"
        assert not window.sources_page.zip_button.icon().isNull()
    finally:
        window.close()
        application.processEvents()
