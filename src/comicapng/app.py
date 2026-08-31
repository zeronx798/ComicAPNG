"""ComicAPNG application bootstrap."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from platformdirs import user_log_path
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from comicapng.i18n import I18n
from comicapng.services.settings import AppSettings
from comicapng.ui.main_window import MainWindow
from comicapng.ui.theme import application_stylesheet

PACKAGING_SMOKE_TEST_ARGUMENT = "--packaging-smoke-test"


def configure_logging() -> None:
    try:
        directory = user_log_path("ComicAPNG", appauthor=False)
        directory.mkdir(parents=True, exist_ok=True)
        destination: Path | None = directory / "comicapng.log"
    except OSError:
        destination = None
    logging.basicConfig(
        filename=str(destination) if destination is not None else None,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_application(arguments: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    application = QApplication(arguments if arguments is not None else sys.argv)
    application.setApplicationName("ComicAPNG")
    application.setOrganizationName("ComicAPNG")
    application.setStyle("Fusion")

    settings = AppSettings()
    locale_name = str(settings.value("ui/language", QLocale.system().name()))
    i18n = I18n(locale_name)
    application.setApplicationDisplayName(i18n.tr("app.name"))
    application.setStyleSheet(application_stylesheet())
    window = MainWindow(i18n, settings)
    return application, window


def main() -> int:
    configure_logging()
    arguments = [value for value in sys.argv if value != PACKAGING_SMOKE_TEST_ARGUMENT]
    smoke_test = len(arguments) != len(sys.argv)
    application, window = create_application(arguments)
    if smoke_test:
        for locale_name in I18n.SUPPORTED_LOCALES:
            if not I18n(locale_name).tr("app.name"):
                raise RuntimeError(f"Missing packaged locale: {locale_name}")
        if window.windowIcon().isNull():
            raise RuntimeError("Packaged application icon is unavailable")
        application.processEvents()
        window.close()
        return 0
    window.show()
    return application.exec()
