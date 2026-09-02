"""Deterministic, network-free implementation of Plugin API v1."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Any

from PIL import Image

from comicapng.plugins.api import (
    MaterializedChapter,
    SourceChapter,
    SourceComic,
    SourcePage,
    SourceSearchPage,
    SourceSearchResult,
)
from comicapng.plugins.errors import PluginError, PluginErrorCode, PluginOperationError

from .reorder_fixtures import REORDER_FIXTURE_SPECS, render_reorder_fixture

PLUGIN_ID = "org.comicapng.source.test"
COMIC_ID = "fixture-comic"


class TestSourcePlugin:
    """A fixed source with two chapters and varied predictable RGBA pages."""

    __test__ = False
    plugin_id = PLUGIN_ID

    def health(self) -> dict[str, Any]:
        return {
            "available": True,
            "message": "Deterministic local source is ready",
            "dependency_version": None,
        }

    def search(self, query: str, page: int) -> SourceSearchPage:
        if page != 1:
            return SourceSearchPage(page=page, page_count=1, total=1, items=())
        normalized = query.strip().casefold()
        if normalized and normalized not in {"fixture", "fixture comic", COMIC_ID}:
            return SourceSearchPage(page=1, page_count=0, total=0, items=())
        result = SourceSearchResult(
            plugin_id=PLUGIN_ID,
            source_id=COMIC_ID,
            title="Fixture Comic",
            tags=("fixture", "offline"),
            summary="A deterministic source for ComicAPNG validation",
            source_ref="comicapng:test-source:fixture-comic",
        )
        return SourceSearchPage(page=1, page_count=1, total=1, items=(result,))

    def get_comic(self, source_id: str) -> SourceComic:
        self._require_comic(source_id)
        return SourceComic(
            plugin_id=PLUGIN_ID,
            source_id=COMIC_ID,
            title="Fixture Comic",
            authors=("ComicAPNG",),
            description="Deterministic pages used to validate the source pipeline.",
            tags=("fixture", "offline", "rgba"),
            chapter_count=2,
            cover_ref="comicapng:test-source:cover",
            source_ref="comicapng:test-source:fixture-comic",
        )

    def get_chapters(self, comic_id: str) -> tuple[SourceChapter, ...]:
        self._require_comic(comic_id)
        return (
            SourceChapter(PLUGIN_ID, "fixture-chapter-1", COMIC_ID, "Chapter One", 1),
            SourceChapter(PLUGIN_ID, "fixture-chapter-2", COMIC_ID, "Chapter Two", 2),
        )

    def materialize_cover(
        self,
        comic_id: str,
        destination: Path,
        *,
        task_id: str,
        cancel_event: Event,
    ) -> Path:
        del task_id
        self._require_comic(comic_id)
        self._check_cancel(cancel_event)
        destination.mkdir(parents=True, exist_ok=True)
        path = (destination / "cover.png").resolve()
        with Image.new("RGBA", (16, 16), (245, 190, 20, 192)) as image:
            image.save(path, format="PNG")
        return path

    def materialize_chapter(
        self,
        chapter: SourceChapter,
        destination: Path,
        *,
        include_cover: bool,
        task_id: str,
        cancel_event: Event,
        progress,
    ) -> MaterializedChapter:
        valid = {item.source_id: item for item in self.get_chapters(chapter.comic_id)}
        if chapter.source_id not in valid:
            raise PluginOperationError(
                PluginError(PluginErrorCode.NOT_FOUND, "The requested fixture chapter was not found")
            )
        chapter = valid[chapter.source_id]
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        definitions = {
            "fixture-chapter-1": REORDER_FIXTURE_SPECS[:5],
            "fixture-chapter-2": REORDER_FIXTURE_SPECS[5:],
        }[chapter.source_id]
        pages: list[SourcePage] = []
        for index, fixture in enumerate(definitions, 1):
            self._check_cancel(cancel_event)
            path = render_reorder_fixture(fixture, destination / fixture.filename)
            pages.append(
                SourcePage(
                    plugin_id=PLUGIN_ID,
                    source_id=f"{chapter.source_id}:{fixture.index}",
                    chapter_id=chapter.source_id,
                    index=index,
                    local_path=path,
                    metadata={
                        "fixture_page_index": fixture.index,
                        "source_page_index": index,
                    },
                )
            )
            progress(index, len(definitions))
            if task_id == "cancellation-test" and index == 1:
                cancel_event.wait(1.0)
                self._check_cancel(cancel_event)

        cover_path: Path | None = None
        if include_cover:
            self._check_cancel(cancel_event)
            cover_path = self.materialize_cover(
                chapter.comic_id,
                destination,
                task_id=task_id,
                cancel_event=cancel_event,
            )
        return MaterializedChapter(
            chapter=chapter,
            pages=tuple(pages),
            cover_path=cover_path,
            metadata={"fixture": True},
        )

    @staticmethod
    def _check_cancel(cancel_event: Event) -> None:
        if cancel_event.is_set():
            raise PluginOperationError(
                PluginError(PluginErrorCode.CANCELLED, "Source materialization was cancelled")
            )

    @staticmethod
    def _require_comic(source_id: str) -> None:
        if source_id != COMIC_ID:
            raise PluginOperationError(
                PluginError(PluginErrorCode.NOT_FOUND, "The requested fixture comic was not found")
            )


def create_plugin() -> TestSourcePlugin:
    return TestSourcePlugin()
