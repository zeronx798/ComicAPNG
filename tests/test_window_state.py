"""Main-window geometry and maximized-state persistence tests."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication

from comicapng.i18n import I18n
from comicapng.services.settings import AppSettings
from comicapng.ui.main_window import MainWindow


def _window(tmp_path: Path) -> tuple[MainWindow, QApplication, QSettings]:
    application = QApplication.instance() or QApplication([])
    backend = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return MainWindow(I18n("en"), AppSettings(backend)), application, backend


def test_normal_geometry_and_position_are_restored(tmp_path: Path) -> None:
    window, application, backend = _window(tmp_path)
    screen = application.primaryScreen().availableGeometry()
    requested = QRect(screen.x() + 24, screen.y() + 32, 1000, 680)
    try:
        window.setGeometry(requested)
        saved = QRect(window.geometry())
        window._save_window_geometry()
        backend.sync()
    finally:
        window.close()
        application.processEvents()

    restored = MainWindow(I18n("en"), AppSettings(backend))
    try:
        assert restored.geometry() == saved
        assert restored.restore_maximized is False
    finally:
        restored.close()
        application.processEvents()


def test_maximized_state_preserves_normal_geometry(tmp_path: Path) -> None:
    window, application, backend = _window(tmp_path)
    screen = application.primaryScreen().availableGeometry()
    requested = QRect(screen.x() + 35, screen.y() + 45, 1050, 690)
    try:
        window.setGeometry(requested)
        window.stack.setCurrentIndex(1)
        window.show()
        application.processEvents()
        normal = QRect(window.geometry())
        window.showMaximized()
        application.processEvents()
        assert window.isMaximized() is True
        window.close()
        application.processEvents()
    finally:
        if window.isVisible():
            window.close()

    assert AppSettings(backend).boolean("window/maximized", False) is True
    saved = backend.value("window/normal_geometry")
    assert isinstance(saved, QRect)
    assert saved == normal

    restored = MainWindow(I18n("en"), AppSettings(backend))
    try:
        assert restored.restore_maximized is True
        assert restored.geometry() == normal
    finally:
        restored.close()
        application.processEvents()


def test_offscreen_geometry_falls_back_to_default_size(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    backend = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    backend.setValue("window/normal_geometry", QRect(500_000, 500_000, 1600, 900))
    backend.setValue("window/width", 1600)
    backend.setValue("window/height", 900)
    backend.sync()

    window = MainWindow(I18n("en"), AppSettings(backend))
    try:
        assert window.size().width() == 1280
        assert window.size().height() == 820
        assert window.geometry().x() != 500_000
        assert window.geometry().y() != 500_000
    finally:
        window.close()
        application.processEvents()


def test_visibility_check_supports_changed_multi_screen_layouts() -> None:
    screens = [QRect(0, 0, 1920, 1080), QRect(-1280, 0, 1280, 1024)]
    assert MainWindow._geometry_is_visible(QRect(-900, 50, 1000, 700), screens)
    assert MainWindow._geometry_is_visible(QRect(1750, 900, 500, 300), screens)
    assert not MainWindow._geometry_is_visible(QRect(10_000, 50, 1000, 700), screens)
    assert not MainWindow._geometry_is_visible(QRect(10, 10, 40, 40), screens)
