"""ComicAPNG application bootstrap."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from platformdirs import user_log_path
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from comicapng.i18n import I18n
from comicapng.services.settings import AppSettings
from comicapng.ui.main_window import MainWindow
from comicapng.ui.theme import application_stylesheet

PACKAGING_SMOKE_TEST_ARGUMENT = "--packaging-smoke-test"
PLUGIN_HOST_ARGUMENT = "--plugin-host"


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
    if PLUGIN_HOST_ARGUMENT in sys.argv:
        from comicapng.plugins.host import main as plugin_host_main

        host_arguments = [
            value for value in sys.argv[1:] if value != PLUGIN_HOST_ARGUMENT
        ]
        return plugin_host_main(host_arguments)
    arguments = [value for value in sys.argv if value != PACKAGING_SMOKE_TEST_ARGUMENT]
    smoke_test = len(arguments) != len(sys.argv)
    application, window = create_application(arguments)
    if smoke_test:
        from curl_cffi import Curl
        from PIL import Image

        from comicapng.core.apng_importer import import_apng
        from comicapng.core.apng_writer import write_apng
        from comicapng.core.models import ComicBook, ComicMetadata, ComicPage, SourceMetadata
        from comicapng.core.zip_archive import ZipMetadataStatus, import_zip, write_zip
        from comicapng.plugins.client import PluginHostClient

        for locale_name in I18n.SUPPORTED_LOCALES:
            if not I18n(locale_name).tr("app.name"):
                raise RuntimeError(f"Missing packaged locale: {locale_name}")
        if window.windowIcon().isNull():
            raise RuntimeError("Packaged application icon is unavailable")
        smoke_pages = [
            ComicPage(Path("smoke-a.png"), None, 1, 1, is_cover=True),
            ComicPage(Path("smoke-b.png"), None, 1, 1),
        ]
        first_smoke_page, second_smoke_page = smoke_pages
        window.creator_page.book = ComicBook(pages=smoke_pages)
        for page in smoke_pages:
            window.creator_page.page_list.addItem(
                window.creator_page._make_item(page, Path("missing-smoke-thumbnail.png"))
            )
        window.creator_page._refresh_items()
        reorder_menu = window.creator_page._build_page_context_menu(smoke_pages[0].page_id)
        reorder_actions = {action.objectName(): action for action in reorder_menu.actions()}
        if set(reorder_actions) != {
            "create_page_move_up",
            "create_page_move_down",
            "create_page_move_top",
            "create_page_move_bottom",
        }:
            raise RuntimeError("Packaged Create reorder actions are unavailable")
        if any(action.icon().isNull() for action in reorder_actions.values()):
            raise RuntimeError("Packaged Create reorder icons are unavailable")
        reorder_actions["create_page_move_bottom"].trigger()
        if window.creator_page.book.pages != [second_smoke_page, first_smoke_page]:
            raise RuntimeError("Packaged Create page reordering failed")
        reorder_menu.deleteLater()
        window.creator_page.page_list.clear()
        window.creator_page.book = ComicBook()
        with TemporaryDirectory(prefix="comicapng-frozen-smoke-") as temporary:
            root = Path(temporary)
            image_path = root / "page.jpg"
            Image.new("RGB", (4, 6), (20, 40, 80)).save(image_path, format="JPEG")
            document_book = ComicBook(
                pages=[ComicPage(image_path, None, 4, 6, duration_ms=250, is_cover=True)],
                metadata=ComicMetadata(
                    source=SourceMetadata(
                        "org.comicapng.source.test",
                        "frozen-smoke",
                        {"tags": ["offline"]},
                    )
                ),
            )
            archive_path = write_zip(document_book, root / "document.zip")
            archive_result = import_zip(archive_path, root / "zip-workspace")
            if archive_result.metadata_status != ZipMetadataStatus.VALID:
                raise RuntimeError("Packaged ZIP round trip failed")
            if archive_result.book.metadata.source is None:
                raise RuntimeError("Packaged source metadata round trip failed")
            apng_path = write_apng(archive_result.book, root / "document.apng")
            imported_book = import_apng(apng_path, root / "apng-workspace")
            if len(imported_book.pages) != 1 or imported_book.metadata.source is None:
                raise RuntimeError("Packaged APNG import failed")
        curl_runtime = Curl()
        curl_runtime.close()
        with PluginHostClient() as host:
            listed = host.request("plugin.list", timeout=30.0)
            plugin_ids = {item["id"] for item in listed.get("plugins", [])}
            required = {
                "org.comicapng.source.jmcomic",
                "org.comicapng.source.test",
            }
            if not required.issubset(plugin_ids):
                raise RuntimeError("Packaged source plugin manifests are unavailable")
            health = host.request(
                "plugin.health",
                {"plugin_id": "org.comicapng.source.jmcomic"},
                timeout=30.0,
            )
            if not health.get("available"):
                raise RuntimeError("Packaged jmcomic runtime is unavailable")
            test_page = host.request(
                "source.search",
                {
                    "plugin_id": "org.comicapng.source.test",
                    "query": "fixture",
                    "page": 1,
                },
                timeout=30.0,
            )
            if not test_page.get("items"):
                raise RuntimeError("Packaged test-source IPC smoke operation failed")
        application.processEvents()
        window.close()
        return 0
    if window.restore_maximized:
        window.showMaximized()
    else:
        window.show()
    return application.exec()
