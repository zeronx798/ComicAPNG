"""Create/Edit document import and owned-workspace UI tests."""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from comicapng.core.apng_writer import write_apng
from comicapng.core.models import ComicBook, ComicMetadata, ComicPage, SourceMetadata
from comicapng.core.zip_archive import ArchiveDifferences, write_zip
from comicapng.i18n import I18n
from comicapng.plugins.workspace import WorkspaceStore
from comicapng.services.settings import AppSettings
from comicapng.services.thumbnail_cache import ThumbnailCache
from comicapng.ui.dialogs.archive_mismatch_dialog import (
    ArchiveMismatchChoice,
    ArchiveMismatchDialog,
)
from comicapng.ui.pages.creator_page import CreatorPage


def _page(path: Path, color: tuple[int, int, int], label: str) -> ComicPage:
    Image.new("RGB", (24, 18), color).save(path, format="PNG")
    return ComicPage(
        path,
        None,
        24,
        18,
        source_metadata={"label": label},
    )


def _wait_for(application: QApplication, condition, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    application.processEvents()
    assert condition()


def _creator(tmp_path: Path) -> tuple[CreatorPage, QApplication, WorkspaceStore]:
    application = QApplication.instance() or QApplication([])
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    store = WorkspaceStore(tmp_path / "owned-workspaces")
    creator = CreatorPage(
        I18n("en"),
        settings,
        ThumbnailCache(tmp_path / "thumbnails"),
        store,
    )
    return creator, application, store


def test_apng_and_zip_import_replace_transactionally_and_cleanup_workspaces(
    tmp_path: Path,
    monkeypatch,
) -> None:
    creator, application, store = _creator(tmp_path)
    first = _page(tmp_path / "first.png", (230, 20, 30), "first")
    second = _page(tmp_path / "second.png", (20, 220, 40), "second")
    second.is_cover = True
    apng = tmp_path / "input.apng"
    write_apng(ComicBook(pages=[first, second]), apng)
    zip_workspace: Path | None = None

    try:
        creator._start_document_import(apng, "apng")
        _wait_for(
            application,
            lambda: creator._active_worker is None
            and creator._document_workspace is not None,
        )
        apng_workspace = creator._document_workspace
        assert apng_workspace is not None and apng_workspace.is_dir()
        assert all(type(page) is ComicPage for page in creator.book.pages)
        assert all(page.source_path is not None for page in creator.book.pages)
        creator.page_list.item(1).setSelected(True)
        creator.page_list.pages_move_requested.emit([1], 0)
        assert creator.book.pages[0].source_metadata["label"] == "first"

        zip_book = ComicBook(
            pages=[
                _page(tmp_path / "blue.png", (20, 30, 230), "blue"),
                _page(tmp_path / "yellow.png", (230, 220, 20), "yellow"),
            ],
            metadata=ComicMetadata(
                source=SourceMetadata(
                    "org.comicapng.source.test",
                    "fixture-comic",
                    {"tags": ["fixture"]},
                )
            ),
        )
        zip_book.pages[0].is_cover = True
        archive = tmp_path / "input.zip"
        write_zip(zip_book, archive)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        creator._start_document_import(archive, "zip")
        _wait_for(
            application,
            lambda: creator._active_worker is None
            and creator._document_workspace is not None
            and creator._document_workspace != apng_workspace,
        )
        zip_workspace = creator._document_workspace
        assert zip_workspace is not None and zip_workspace.is_dir()
        assert not apng_workspace.exists()
        assert creator.book.metadata.source is not None
        assert creator.book.metadata.source.resource_id == "fixture-comic"
        creator.page_list.item(1).setSelected(True)
        creator.page_list.pages_move_requested.emit([1], 0)
        assert [page.source_metadata["label"] for page in creator.book.pages] == [
            "yellow",
            "blue",
        ]
    finally:
        creator.close()
        store.close()
        application.processEvents()
    assert zip_workspace is not None and not zip_workspace.exists()


def test_mismatch_cancel_keeps_current_document_and_cleans_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    creator, application, store = _creator(tmp_path)
    current_page = _page(tmp_path / "current.png", (10, 20, 30), "current")
    current_page.is_cover = True
    current_book = ComicBook(pages=[current_page])
    creator._finish_source_book_load((current_book, [current_page.source_path]))

    archive_book = ComicBook(
        pages=[
            _page(tmp_path / "archive-a.png", (100, 20, 30), "a"),
            _page(tmp_path / "archive-b.png", (20, 100, 30), "b"),
        ]
    )
    archive_book.pages[0].is_cover = True
    valid = tmp_path / "valid.zip"
    write_zip(archive_book, valid)
    mismatch = tmp_path / "mismatch.zip"
    with zipfile.ZipFile(valid, "r") as source, zipfile.ZipFile(mismatch, "w") as target:
        for name in source.namelist():
            target.writestr("renamed.png" if name == "2.png" else name, source.read(name))

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        ArchiveMismatchDialog,
        "exec",
        lambda _self: QDialog.DialogCode.Rejected,
    )
    try:
        creator._start_document_import(mismatch, "zip")
        _wait_for(
            application,
            lambda: creator._active_worker is None
            and creator._pending_document_import is None,
        )
        assert creator.book is current_book
        assert creator.book.pages[0] is current_page
        assert store.owned == set()
    finally:
        creator.close()
        store.close()
        application.processEvents()


def test_mismatch_dialog_lists_differences_and_exposes_safe_choices(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    dialog = ArchiveMismatchDialog(
        I18n("en"),
        ArchiveDifferences(
            found=("1.jpg", "2.png", "4.webp"),
            referenced=("1.jpg", "2.png", "5.webp"),
            missing=("5.webp",),
            unexpected=("4.webp",),
        ),
    )
    try:
        dialog.show()
        application.processEvents()
        assert dialog.details.isVisible() is False
        dialog.review_button.click()
        application.processEvents()
        assert dialog.details.isVisible() is True
        text = dialog.details.toPlainText()
        assert "1.jpg" in text
        assert "5.webp" in text
        assert "4.webp" in text
        dialog.images_button.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.choice == ArchiveMismatchChoice.IMAGES_ONLY
    finally:
        dialog.close()
        application.processEvents()
