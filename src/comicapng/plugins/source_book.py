"""Bridge materialized source pages into the normal ComicBook model."""

from __future__ import annotations

import re
from pathlib import Path

from comicapng.core.image_files import inspect_image
from comicapng.core.models import ComicBook, ComicMetadata, ComicPage, ReadingDirection

from .api import MaterializedChapter, SourceComic

INVALID_FILENAME_CHARACTERS = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")


def safe_filename(value: str, fallback: str = "comic") -> str:
    cleaned = INVALID_FILENAME_CHARACTERS.sub("_", value).strip().rstrip(".")
    return cleaned[:120] or fallback


def source_metadata(comic: SourceComic, source_name: str) -> ComicMetadata:
    fields = {
        "Title": comic.title,
        "Author": ", ".join(comic.authors),
        "Source": source_name,
        "SourceId": comic.source_id,
        "Tags": ", ".join(comic.tags),
        "SourceRef": comic.source_ref or "",
    }
    return ComicMetadata(text_fields={key: value for key, value in fields.items() if value})


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
            )
        )
    # SourcePage.index establishes only this initial transfer order. ComicPage
    # deliberately has no immutable source-order field; ComicBook.pages owns all
    # subsequent Create ordering.
    for chapter in chapters:
        for source_page in chapter.pages:
            width, height, _format = inspect_image(source_page.local_path)
            pages.append(
                ComicPage(
                    source_path=source_page.local_path,
                    source_width=width,
                    source_height=height,
                )
            )
    if cover_path is None and pages:
        pages[0].is_cover = True
    book = ComicBook(
        pages=pages,
        metadata=source_metadata(comic, source_name),
        reading_direction=reading_direction,
        cover_duration_ms=cover_duration_ms,
        body_duration_ms=body_duration_ms,
    )
    book.validate()
    return book
