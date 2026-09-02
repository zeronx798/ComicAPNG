"""Bridge materialized source pages into the normal ComicBook model."""

from __future__ import annotations

import re
from pathlib import Path

from comicapng.core.image_files import inspect_image
from comicapng.core.models import (
    ComicBook,
    ComicMetadata,
    ComicPage,
    ReadingDirection,
    SourceMetadata,
)

from .api import MaterializedChapter, SourceComic

INVALID_FILENAME_CHARACTERS = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")


def safe_filename(value: str, fallback: str = "comic") -> str:
    cleaned = INVALID_FILENAME_CHARACTERS.sub("_", value).strip().rstrip(".")
    return cleaned[:120] or fallback


def source_metadata(
    comic: SourceComic,
    source_name: str,
    chapters: tuple[MaterializedChapter, ...] = (),
) -> ComicMetadata:
    fields = {
        "Title": comic.title,
        "Author": ", ".join(comic.authors),
        "Source": source_name,
        "SourceId": comic.source_id,
        "Tags": ", ".join(comic.tags),
        "SourceRef": comic.source_ref or "",
    }
    source_data: dict[str, object] = {}
    if comic.tags:
        source_data["tags"] = list(comic.tags)
    if comic.authors:
        source_data["authors"] = list(comic.authors)
    if comic.description:
        source_data["description"] = comic.description
    if comic.source_ref:
        source_data["source_ref"] = comic.source_ref
    if source_name:
        source_data["source_name"] = source_name
    if comic.extra:
        source_data["extra"] = dict(comic.extra)
    if chapters:
        source_data["chapters"] = [
            {
                "source_id": chapter.chapter.source_id,
                "title": chapter.chapter.title,
                "index": chapter.chapter.index,
            }
            for chapter in chapters
        ]
    return ComicMetadata(
        text_fields={key: value for key, value in fields.items() if value},
        source=SourceMetadata(
            plugin_id=comic.plugin_id,
            resource_id=comic.source_id,
            data=source_data,
        ),
    )


def comic_book_from_source(
    comic: SourceComic,
    source_name: str,
    chapters: tuple[MaterializedChapter, ...],
    *,
    include_cover: bool,
    cover_duration_ms: int,
    body_duration_ms: int,
    reading_direction: ReadingDirection = "ltr",
) -> ComicBook:
    """Build the same model used for manually imported pages and normal export."""
    pages: list[ComicPage] = []
    cover_path: Path | None = None
    if include_cover:
        cover_path = next(
            (chapter.cover_path for chapter in chapters if chapter.cover_path is not None),
            None,
        )
    if cover_path is not None:
        width, height, _format = inspect_image(cover_path)
        pages.append(
            ComicPage(
                source_path=cover_path,
                source_width=width,
                source_height=height,
                is_cover=True,
                source_metadata={"source_id": comic.source_id, "kind": "cover"},
            )
        )
    # SourcePage.index establishes only this initial transfer order. ComicPage
    # deliberately has no immutable source-order field; ComicBook.pages owns all
    # subsequent Create ordering.
    for chapter in chapters:
        for source_page in chapter.pages:
            width, height, _format = inspect_image(source_page.local_path)
            page_source_metadata = dict(source_page.metadata)
            page_source_metadata.update(
                {
                    "source_id": source_page.source_id,
                    "chapter_id": source_page.chapter_id,
                    "source_page_index": source_page.index,
                    "chapter_index": chapter.chapter.index,
                    "chapter_title": chapter.chapter.title,
                }
            )
            pages.append(
                ComicPage(
                    source_path=source_page.local_path,
                    source_width=width,
                    source_height=height,
                    source_metadata=page_source_metadata,
                )
            )
    if cover_path is None and pages:
        pages[0].is_cover = True
    book = ComicBook(
        pages=pages,
        metadata=source_metadata(comic, source_name, chapters),
        reading_direction=reading_direction,
        cover_duration_ms=cover_duration_ms,
        body_duration_ms=body_duration_ms,
    )
    book.validate()
    return book
