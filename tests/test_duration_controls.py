"""Tests for the seconds-based duration controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from comicapng.core.models import (
    DEFAULT_BODY_DURATION_MS,
    DEFAULT_COVER_DURATION_MS,
    ComicBook,
)
from comicapng.i18n import I18n
from comicapng.services.settings import AppSettings
from comicapng.services.thumbnail_cache import ThumbnailCache
from comicapng.ui.dialogs.preferences_dialog import PreferencesDialog
from comicapng.ui.pages.creator_page import CreatorPage
from comicapng.ui.widgets.duration_spin_box import DurationSpinBox


def test_model_uses_new_duration_defaults() -> None:
    book = ComicBook()
    assert book.cover_duration_ms == DEFAULT_COVER_DURATION_MS == 10_000
    assert book.body_duration_ms == DEFAULT_BODY_DURATION_MS == 5_000


def test_duration_spin_box_displays_seconds_and_preserves_milliseconds() -> None:
    application = QApplication.instance() or QApplication([])
    duration = DurationSpinBox()
    try:
        duration.set_milliseconds(10_000)
        assert duration.text() == "10.000"
        assert duration.suffix() == ""
        assert duration.decimals() == 3
        assert duration.singleStep() == 1.0

        duration.stepUp()
        assert duration.text() == "11.000"
        duration.stepDown()
        assert duration.text() == "10.000"

        duration.setValue(12.345)
        assert duration.milliseconds() == 12_345
    finally:
        duration.close()
        application.processEvents()


def test_creator_and_preferences_put_units_outside_inputs(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    backend = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings = AppSettings(backend)
    i18n = I18n("en")
    creator = CreatorPage(i18n, settings, ThumbnailCache(tmp_path / "thumbnails"))
    preferences = PreferencesDialog(i18n, settings)
    try:
        assert creator.cover_duration.text() == "10.000"
        assert creator.body_duration.text() == "5.000"
        assert creator.cover_duration_unit.text() == "second(s)"
        assert creator.body_duration_unit.text() == "second(s)"
        assert creator.cover_duration.suffix() == ""
        assert creator.body_duration.suffix() == ""

        assert preferences.cover_duration.text() == "10.000"
        assert preferences.body_duration.text() == "5.000"
        assert preferences.cover_duration_unit.text() == "second(s)"
        assert preferences.body_duration_unit.text() == "second(s)"

        preferences.cover_duration.setValue(11.234)
        preferences.body_duration.setValue(6.789)
        preferences._save()
        assert settings.integer("creator/cover_duration", 0) == 11_234
        assert settings.integer("creator/body_duration", 0) == 6_789
    finally:
        preferences.close()
        creator.close()
        application.processEvents()
