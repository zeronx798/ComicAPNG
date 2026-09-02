"""Mocked tests for the official JMComic adapter and manifest handling."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from comicapng.core.models import ComicPage
from comicapng.extensions.jmcomic.adapter import JMComicPlugin
from comicapng.extensions.jmcomic.mapper import PLUGIN_ID, map_album, map_chapters, map_search_page
from comicapng.plugins.api import SourceChapter
from comicapng.plugins.errors import PluginErrorCode, PluginOperationError
from comicapng.plugins.source_book import comic_book_from_source


class FakePhoto:
    def __init__(self, photo_id: str, name: str) -> None:
        self.photo_id = photo_id
        self.name = name


class FakeAlbum:
    album_id = "123"
    name = "Mapped Album"
    authors = ["First Author", "Second Author"]
    description = "Description"
    tags = ["tag-a", "tag-b"]
    page_count = 3
    likes = "10"
    views = "20"

    def __init__(self) -> None:
        self.photos = [FakePhoto("301", "First"), FakePhoto("302", "Second")]

    def __iter__(self):
        return iter(self.photos)

    def __len__(self) -> int:
        return len(self.photos)


class FakeSearchPage:
    page_number = 2
    page_count = 4
    total = 75

    def iter_id_title_tag(self):
        yield "123", "Mapped Album", ["tag-a", "tag-b"]
        yield "456", "Other", []


class FakeClient:
    def __init__(self, album: FakeAlbum) -> None:
        self.album = album
        self.search_calls: list[tuple[str, int]] = []
        self.detail_calls: list[str] = []

    def search_site(self, *, search_query: str, page: int):
        self.search_calls.append((search_query, page))
        return FakeSearchPage()

    def get_album_detail(self, album_id: str):
        self.detail_calls.append(album_id)
        return self.album

    def download_album_cover(self, album_id: str, path: str) -> None:
        assert album_id == "123"
        Image.new("RGB", (5, 7), (220, 180, 20)).save(path, format="JPEG")


class FakeOption:
    client: FakeClient
    configs: list[dict] = []

    @classmethod
    def construct(cls, config: dict):
        cls.configs.append(config)
        return cls()

    def new_jm_client(self):
        return self.client


class FakeBackend:
    __version__ = "2.7.5"
    JmOption = FakeOption

    def __init__(self, result) -> None:
        self.result = result
        self.download_calls: list[tuple[str, object]] = []

    def download_photo(self, chapter_id: str, *, option):
        self.download_calls.append((chapter_id, option))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    @staticmethod
    @contextmanager
    def jm_task_context(**_fields):
        yield


def _chapter() -> SourceChapter:
    return SourceChapter(PLUGIN_ID, "301", "123", "First", 1)


def _result(paths: list[Path], *, failed: bool = False):
    downloader = SimpleNamespace(
        download_failed_image=[("image", RuntimeError())] if failed else [],
        download_failed_photo=[],
    )
    return SimpleNamespace(
        manifest=SimpleNamespace(image_filepath_list=[str(path) for path in paths]),
        downloader=downloader,
        duration=1.25,
    )


def test_search_details_and_chapters_are_mapped_without_upstream_entities() -> None:
    page = map_search_page(FakeSearchPage(), 2)
    assert page.page == 2
    assert page.page_count == 4
    assert page.total == 75
    assert page.items[0].source_id == "123"
    assert page.items[0].tags == ("tag-a", "tag-b")

    album = FakeAlbum()
    comic = map_album(album)
    chapters = map_chapters(album)
    assert comic.source_id == "123"
    assert comic.authors == ("First Author", "Second Author")
    assert comic.description == "Description"
    assert comic.chapter_count == 2
    assert [chapter.source_id for chapter in chapters] == ["301", "302"]
    assert [chapter.index for chapter in chapters] == [1, 2]


def test_optional_album_metadata_does_not_fail_mapping() -> None:
    class MinimalAlbum:
        album_id = "9"
        name = "Minimal"

        def __iter__(self):
            return iter(())

        def __len__(self) -> int:
            return 0

    comic = map_album(MinimalAlbum())
    assert comic.authors == ()
    assert comic.tags == ()
    assert comic.description is None


def test_adapter_uses_manifest_order_and_downloads_cover(tmp_path: Path) -> None:
    paths = [
        tmp_path / "E-file.png",
        tmp_path / "A-file.png",
        tmp_path / "D-file.png",
        tmp_path / "B-file.png",
        tmp_path / "C-file.png",
    ]
    for index, path in enumerate(paths, 1):
        Image.new("RGBA", (5 + index, 7 + index), (index * 30, 20, 210, 255)).save(path)
    client = FakeClient(FakeAlbum())
    FakeOption.client = client
    FakeOption.configs = []
    backend = FakeBackend(_result(paths))
    plugin = JMComicPlugin(backend)
    progress: list[tuple[int, int]] = []
    materialized = plugin.materialize_chapter(
        _chapter(),
        tmp_path,
        include_cover=True,
        task_id="adapter-test",
        cancel_event=SimpleNamespace(is_set=lambda: False),
        progress=lambda current, total: progress.append((current, total)),
    )
    assert [page.local_path for page in materialized.pages] == [
        path.resolve() for path in paths
    ]
    assert [page.index for page in materialized.pages] == [1, 2, 3, 4, 5]
    assert materialized.cover_path is not None
    assert materialized.cover_path.is_file()
    assert backend.download_calls[0][0] == "301"
    assert FakeOption.configs[0]["dir_rule"]["base_dir"] == str(tmp_path.resolve())
    assert progress == [(0, 1), (1, 1)]

    book = comic_book_from_source(
        map_album(FakeAlbum()),
        "JMComic",
        (materialized,),
        include_cover=False,
        cover_duration_ms=1000,
        body_duration_ms=500,
    )
    assert all(type(page) is ComicPage for page in book.pages)
    assert all(not hasattr(page, "index") for page in book.pages)
    assert [page.source_path for page in book.pages] == [path.resolve() for path in paths]

    moved_page = book.pages[-1]
    book.move_page(4, 1)
    book.metadata.text_fields["Edit"] = "does-not-sort"
    book.set_cover(moved_page.page_id)
    book.validate()

    assert [page.source_path for page in book.pages] == [
        paths[0].resolve(),
        paths[4].resolve(),
        paths[1].resolve(),
        paths[2].resolve(),
        paths[3].resolve(),
    ]
    assert book.pages[1] is moved_page
    assert moved_page.is_cover is True
    assert [page.local_path for page in materialized.pages] == [
        path.resolve() for path in paths
    ]


@pytest.mark.parametrize("paths", [[], [Path("missing.png")]])
def test_adapter_rejects_empty_or_missing_manifest_files(tmp_path: Path, paths: list[Path]) -> None:
    resolved = [path if path.is_absolute() else tmp_path / path for path in paths]
    FakeOption.client = FakeClient(FakeAlbum())
    plugin = JMComicPlugin(FakeBackend(_result(resolved)))
    with pytest.raises(PluginOperationError) as caught:
        plugin.materialize_chapter(
            _chapter(),
            tmp_path,
            include_cover=False,
            task_id="adapter-test",
            cancel_event=SimpleNamespace(is_set=lambda: False),
            progress=lambda _current, _total: None,
        )
    assert caught.value.error.code == PluginErrorCode.PARTIAL_DOWNLOAD


def test_adapter_surfaces_upstream_partial_failure(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    Image.new("RGBA", (4, 4), (1, 2, 3, 255)).save(page)
    FakeOption.client = FakeClient(FakeAlbum())
    plugin = JMComicPlugin(FakeBackend(_result([page], failed=True)))
    with pytest.raises(PluginOperationError) as caught:
        plugin.materialize_chapter(
            _chapter(),
            tmp_path,
            include_cover=False,
            task_id="adapter-test",
            cancel_event=SimpleNamespace(is_set=lambda: False),
            progress=lambda _current, _total: None,
        )
    assert caught.value.error.code == PluginErrorCode.PARTIAL_DOWNLOAD


def test_adapter_translates_public_not_found_exception() -> None:
    missing_type = type("MissingAlbumPhotoException", (Exception,), {})
    error = JMComicPlugin._translate_exception(missing_type(), "comic details")
    assert error.error.code == PluginErrorCode.NOT_FOUND


def test_missing_dependency_is_an_unavailable_health_state(monkeypatch) -> None:
    def missing(_name: str):
        raise ModuleNotFoundError("jmcomic")

    monkeypatch.setattr(
        "comicapng.extensions.jmcomic.adapter.importlib.import_module",
        missing,
    )
    health = JMComicPlugin().health()
    assert health["available"] is False
    assert health["error_code"] == PluginErrorCode.DEPENDENCY_UNAVAILABLE.value
