"""Subprocess IPC tests using the deterministic source extension."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from comicapng.core.zip_archive import ZipMetadataStatus, import_zip, write_zip
from comicapng.plugins.api import MaterializedChapter, SourceChapter, SourceComic, SourceSearchPage
from comicapng.plugins.client import PluginHostClient
from comicapng.plugins.errors import PluginCallError, PluginErrorCode
from comicapng.plugins.source_book import comic_book_from_source


def test_host_lists_and_runs_test_source(tmp_path: Path) -> None:
    with PluginHostClient() as client:
        listed = client.request("plugin.list")
        assert {item["id"] for item in listed["plugins"]} >= {
            "org.comicapng.source.jmcomic",
            "org.comicapng.source.test",
        }
        health = client.request(
            "plugin.health", {"plugin_id": "org.comicapng.source.test"}
        )
        assert health["available"] is True
        page = SourceSearchPage.from_dict(
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
                    "plugin_id": "org.comicapng.source.test",
                    "source_id": page.items[0].source_id,
                },
            )
        )
        chapters_result = client.request(
            "source.get_chapters",
            {"plugin_id": comic.plugin_id, "comic_id": comic.source_id},
        )
        chapter = SourceChapter.from_dict(chapters_result["items"][0])
        progress: list[tuple[int, int]] = []
        materialized = MaterializedChapter.from_dict(
            client.request(
                "source.materialize_chapter",
                {
                    "plugin_id": comic.plugin_id,
                    "chapter": chapter.to_dict(),
                    "destination": str(tmp_path.resolve()),
                    "include_cover": True,
                    "task_id": "host-test",
                },
                progress=lambda current, total: progress.append((current, total)),
                timeout=None,
            )
        )
    assert len(materialized.pages) == 5
    assert [page.local_path.name for page in materialized.pages] == [
        "page-01.png",
        "page-02.png",
        "page-03.png",
        "page-04.png",
        "page-05.png",
    ]
    assert materialized.cover_path is not None
    assert materialized.cover_path.is_file()
    assert progress[-1] == (5, 5)

    book = comic_book_from_source(
        comic,
        "ComicAPNG Test Source",
        (materialized,),
        include_cover=True,
        cover_duration_ms=1000,
        body_duration_ms=500,
    )
    archive = tmp_path / "test-source.zip"
    write_zip(book, archive)
    imported = import_zip(archive, tmp_path / "archive-workspace")
    assert imported.metadata_status == ZipMetadataStatus.VALID
    assert imported.book.metadata.source is not None
    assert imported.book.metadata.source.plugin_id == "org.comicapng.source.test"
    assert imported.book.metadata.source.resource_id == "fixture-comic"
    assert imported.book.metadata.source.data["tags"] == ["fixture", "offline", "rgba"]
    assert [page.source_metadata.get("source_page_index") for page in imported.book.pages] == [
        None,
        1,
        2,
        3,
        4,
        5,
    ]


def test_host_cancellation_is_controlled(tmp_path: Path) -> None:
    cancel_event = Event()
    with PluginHostClient() as client:
        chapters = client.request(
            "source.get_chapters",
            {
                "plugin_id": "org.comicapng.source.test",
                "comic_id": "fixture-comic",
            },
        )["items"]
        with pytest.raises(PluginCallError) as caught:
            client.request(
                "source.materialize_chapter",
                {
                    "plugin_id": "org.comicapng.source.test",
                    "chapter": chapters[0],
                    "destination": str(tmp_path.resolve()),
                    "include_cover": False,
                    "task_id": "cancellation-test",
                },
                cancel_event=cancel_event,
                progress=lambda current, _total: cancel_event.set() if current == 1 else None,
                timeout=None,
            )
    assert caught.value.error.code == PluginErrorCode.CANCELLED
