"""End-to-end deterministic Source-to-Create-to-APNG validation."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from comicapng.core.apng_reader import ApngDocument
from comicapng.core.apng_writer import write_apng
from comicapng.core.models import ComicPage
from comicapng.extensions.test_source.reorder_fixtures import REORDER_FIXTURE_SPECS
from comicapng.i18n import I18n
from comicapng.plugins.api import (
    MaterializedChapter,
    SourceChapter,
    SourceComic,
    SourceSearchPage,
)
from comicapng.plugins.client import PluginHostClient
from comicapng.plugins.source_book import comic_book_from_source
from comicapng.services.settings import AppSettings
from comicapng.services.thumbnail_cache import ThumbnailCache
from comicapng.ui.pages.creator_page import CreatorPage


def _wait_for_creator(creator: CreatorPage, application: QApplication) -> None:
    deadline = time.monotonic() + 10.0
    while creator._active_worker is not None and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    application.processEvents()
    assert creator._active_worker is None


def _names(pages: list[ComicPage]) -> list[str]:
    return [page.source_path.name for page in pages if page.source_path is not None]


def test_source_materialization_reorders_in_create_and_controls_export(
    tmp_path: Path,
) -> None:
    with PluginHostClient() as client:
        search = SourceSearchPage.from_dict(
            client.request(
                "source.search",
                {
                    "plugin_id": "org.comicapng.source.test",
                    "query": "fixture",
                    "page": 1,
                },
            )
        )
        comic = SourceComic.from_dict(
            client.request(
                "source.get_comic",
                {
                    "plugin_id": search.items[0].plugin_id,
                    "source_id": search.items[0].source_id,
                },
            )
        )
        raw_chapters = client.request(
            "source.get_chapters",
            {"plugin_id": comic.plugin_id, "comic_id": comic.source_id},
        )["items"]
        chapters = tuple(SourceChapter.from_dict(value) for value in raw_chapters)
        materialized: list[MaterializedChapter] = []
        for index, chapter in enumerate(chapters):
            destination = (tmp_path / f"chapter-{index + 1}").resolve()
            destination.mkdir()
            materialized.append(
                MaterializedChapter.from_dict(
                    client.request(
                        "source.materialize_chapter",
                        {
                            "plugin_id": comic.plugin_id,
                            "chapter": chapter.to_dict(),
                            "destination": str(destination),
                            "include_cover": index == 0,
                            "task_id": "source-reorder-roundtrip",
                        },
                        timeout=None,
                    )
                )
            )

    book = comic_book_from_source(
        comic,
        "ComicAPNG Test Source",
        tuple(materialized),
        include_cover=True,
        cover_duration_ms=2500,
        body_duration_ms=750,
    )
    assert book.metadata.text_fields["Title"] == "Fixture Comic"
    assert book.metadata.text_fields["SourceId"] == "fixture-comic"
    assert all(type(page) is ComicPage for page in book.pages)
    assert all(not hasattr(page, "index") for page in book.pages)
    assert _names(book.pages) == [
        "cover.png",
        *(f"page-{index:02d}.png" for index in range(1, 11)),
    ]

    application = QApplication.instance() or QApplication([])
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    creator = CreatorPage(I18n("en"), settings, ThumbnailCache(tmp_path / "thumbnails"))
    try:
        assert creator.load_book(book) is True
        _wait_for_creator(creator, application)
        assert creator.book is book

        cover_page = next(
            page for page in creator.book.pages if page.source_path.name == "page-03.png"
        )
        cover_row = creator.book.pages.index(cover_page)
        creator.page_list.clearSelection()
        creator.page_list.item(cover_row).setSelected(True)
        creator._set_selected_cover()

        manual_order = [
            "page-05.png",
            "page-03.png",
            "page-01.png",
            "page-10.png",
            "page-04.png",
            "page-02.png",
            "page-06.png",
            "page-09.png",
            "page-07.png",
            "cover.png",
            "page-08.png",
        ]
        for target_index, name in enumerate(manual_order):
            source_index = _names(creator.book.pages).index(name)
            creator.page_list.clearSelection()
            creator.page_list.item(source_index).setSelected(True)
            creator.page_list.pages_move_requested.emit([source_index], target_index)

        assert _names(creator.book.pages) == manual_order
        assert creator.book.pages[1] is cover_page
        assert cover_page.is_cover is True
        creator.book.metadata.text_fields["ReorderTest"] = "manual-order-wins"
        creator._refresh_items()
        assert _names(creator.book.pages) == manual_order

        duration_by_name = {"cover.png": 1100}
        duration_by_name.update(
            {f"page-{index:02d}.png": 1200 + index for index in range(1, 11)}
        )
        for page in creator.book.pages:
            page.duration_ms = duration_by_name[page.source_path.name]

        export_pages = creator.book.export_pages()
        expected_export_order = [
            "page-03.png",
            *(name for name in manual_order if name != "page-03.png"),
        ]
        assert _names(export_pages) == expected_export_order

        output = tmp_path / "source-reordered.apng"
        write_apng(creator.book, output)
    finally:
        creator.close()
        application.processEvents()

    document = ApngDocument(output)
    assert document.info.frame_count == 11
    assert document.info.canvas_size == (960, 960)
    source_sizes = {"cover.png": (16, 16)}
    source_sizes.update({spec.filename: spec.size for spec in REORDER_FIXTURE_SPECS})
    probe_colors = {"cover.png": (245, 190, 20)}
    probe_colors.update({spec.filename: spec.probe_color for spec in REORDER_FIXTURE_SPECS})

    for index, name in enumerate(expected_export_order):
        assert document.frame_duration_ms(index) == duration_by_name[name]
        geometry = document.original_geometry(index)
        assert geometry is not None
        assert (geometry["source_width"], geometry["source_height"]) == source_sizes[name]
        source_ratio = geometry["source_width"] / geometry["source_height"]
        render_ratio = geometry["render_width"] / geometry["render_height"]
        assert abs(source_ratio - render_ratio) < 0.01

        frame = document.load_frame(index)
        try:
            actual_probe = frame.getpixel((480, 480))[:3]
            expected_probe = probe_colors[name]
            assert all(
                abs(actual_probe[channel] - expected_probe[channel]) <= 2
                for channel in range(3)
            )
            if geometry["offset_x"] > 0:
                assert frame.getpixel((0, 480))[3] == 0
            if geometry["offset_y"] > 0:
                assert frame.getpixel((480, 0))[3] == 0
        finally:
            frame.close()
