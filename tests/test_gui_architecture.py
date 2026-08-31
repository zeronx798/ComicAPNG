"""Smoke tests for the one-window, three-page Qt architecture."""

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


def test_one_main_window_contains_all_workflow_pages(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    backend = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(I18n("en"), AppSettings(backend))
    try:
        assert isinstance(window, QMainWindow)
        assert window.stack.count() == 3
        assert isinstance(window.stack.widget(0), CreatorPage)
        assert isinstance(window.stack.widget(1), ExtractorPage)
        assert isinstance(window.stack.widget(2), ReaderPage)
        assert window.windowTitle() == "ComicAPNG"
    finally:
        window.close()
        application.processEvents()
