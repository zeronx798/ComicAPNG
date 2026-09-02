"""Domain models independent from the Qt user interface."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

ReadingDirection = Literal["ltr", "rtl"]
ExifValueType = Literal["text", "integer", "rational", "bytes"]
DEFAULT_COVER_DURATION_MS = 10_000
DEFAULT_BODY_DURATION_MS = 5_000


@dataclass(slots=True)
class ExifValue:
    """A typed EXIF value that can be validated before serialization."""

    value_type: ExifValueType
    value: str


@dataclass(slots=True)
class ComicPage:
    """One logical comic page."""

    source_path: Path | None = None
    frame_index: int | None = None
    source_width: int = 0
    source_height: int = 0
    duration_ms: int | None = None
    is_cover: bool = False
    page_id: str = field(default_factory=lambda: uuid4().hex)

    def validate(self) -> None:
        if self.source_width <= 0 or self.source_height <= 0:
            raise ValueError("Page dimensions must be positive")
        if self.duration_ms is not None and self.duration_ms <= 0:
            raise ValueError("Page duration must be positive")
        if self.source_path is None and self.frame_index is None:
            raise ValueError("Page must have a source path or frame index")


@dataclass(slots=True)
class ComicMetadata:
    """Independent EXIF, PNG text, and private metadata collections."""

    exif_fields: dict[int, ExifValue] = field(default_factory=dict)
    text_fields: dict[str, str] = field(default_factory=dict)
    private_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ComicBook:
    """A comic book and its ordered logical pages."""

    pages: list[ComicPage] = field(default_factory=list)
    metadata: ComicMetadata = field(default_factory=ComicMetadata)
    reading_direction: ReadingDirection = "ltr"
    cover_duration_ms: int = DEFAULT_COVER_DURATION_MS
    body_duration_ms: int = DEFAULT_BODY_DURATION_MS

    def validate(self) -> None:
        if not self.pages:
            raise ValueError("Comic book has no pages")
        if self.reading_direction not in ("ltr", "rtl"):
            raise ValueError("Invalid reading direction")
        if self.cover_duration_ms <= 0 or self.body_duration_ms <= 0:
            raise ValueError("Frame durations must be positive")
        for page in self.pages:
            page.validate()
        if sum(page.is_cover for page in self.pages) > 1:
            raise ValueError("Comic book has more than one cover")

    def set_cover(self, page_id: str) -> None:
        found = False
        for page in self.pages:
            page.is_cover = page.page_id == page_id
            found = found or page.is_cover
        if not found:
            raise ValueError("Cover page was not found")

    def move_page(self, source_index: int, target_index: int) -> bool:
        """Move one page to its final index and preserve the page object."""
        if not 0 <= target_index < len(self.pages):
            raise IndexError("Target page index is out of range")
        return self.move_pages((source_index,), target_index)

    def move_pages(self, source_indices: Iterable[int], target_index: int) -> bool:
        """Move pages as an ordered block to a final insertion index.

        ``target_index`` is interpreted after the selected pages are removed. It
        is therefore the final index of the first page in the moved block.
        """
        indices = sorted(set(source_indices))
        if not indices:
            raise ValueError("At least one source page index is required")
        if indices[0] < 0 or indices[-1] >= len(self.pages):
            raise IndexError("Source page index is out of range")

        moved_indexes = set(indices)
        moved = [self.pages[index] for index in indices]
        remaining = [
            page for index, page in enumerate(self.pages) if index not in moved_indexes
        ]
        if not 0 <= target_index <= len(remaining):
            raise IndexError("Target page index is out of range")

        reordered = [*remaining[:target_index], *moved, *remaining[target_index:]]
        if all(before is after for before, after in zip(self.pages, reordered, strict=True)):
            return False
        self.pages[:] = reordered
        return True

    def export_pages(self) -> list[ComicPage]:
        """Return pages with the cover first and without duplication."""
        cover = next((page for page in self.pages if page.is_cover), None)
        if cover is None:
            return list(self.pages)
        return [cover, *(page for page in self.pages if page is not cover)]

    def duration_for_export_index(self, page: ComicPage, index: int) -> int:
        if page.duration_ms is not None:
            return page.duration_ms
        return self.cover_duration_ms if index == 0 else self.body_duration_ms
