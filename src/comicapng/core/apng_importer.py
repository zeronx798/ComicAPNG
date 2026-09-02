"""Materialize an APNG as ordinary editable ComicBook pages."""

from __future__ import annotations

import copy
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

from .apng_reader import ApngDocument
from .exceptions import InvalidApngError, OperationCancelledError
from .extractor import restore_frame_bounds
from .metadata import PRIVATE_FORMAT_NAME
from .models import ComicBook, ComicPage

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int], None]


def _positive_integer(value: object, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return fallback
    return value


def _page_source_metadata(private: dict[str, Any], index: int, count: int) -> dict[str, Any]:
    pages = private.get("pages")
    if not isinstance(pages, list) or len(pages) != count:
        return {}
    value = pages[index]
    if not isinstance(value, dict) or not isinstance(value.get("source", {}), dict):
        return {}
    return dict(value.get("source", {}))


def import_apng(
    input_path: Path,
    workspace: Path,
    *,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> ComicBook:
    """Decode logical APNG frames into normal image-backed editable pages."""
    document = ApngDocument(input_path)
    if not document.info.is_animated:
        raise InvalidApngError("The selected PNG is not animated")

    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    raw_private = document.info.metadata.private_metadata
    private = (
        raw_private
        if raw_private.get("format") == PRIVATE_FORMAT_NAME
        else {}
    )
    private_pages = private.get("pages")
    geometry_is_bound = isinstance(private_pages, list) and len(private_pages) == document.info.frame_count
    pages: list[ComicPage] = []

    for index in range(document.info.frame_count):
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelledError("APNG import was cancelled")
        frame = document.load_frame(index)
        if geometry_is_bound:
            frame = restore_frame_bounds(frame, document.original_geometry(index))
        destination = workspace / f"{index + 1}.png"
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=workspace,
                delete=False,
            ) as stream:
                temporary_name = stream.name
                frame.save(stream, format="PNG")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
            page = ComicPage(
                source_path=destination,
                source_width=frame.width,
                source_height=frame.height,
                duration_ms=document.frame_duration_ms(index),
                source_metadata=_page_source_metadata(
                    private,
                    index,
                    document.info.frame_count,
                ),
            )
            try:
                page.validate()
            except ValueError:
                page.source_metadata = {}
                page.validate()
            pages.append(page)
        except (OSError, ValueError) as exc:
            raise InvalidApngError(f"Cannot materialize frame {index + 1}") from exc
        finally:
            frame.close()
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Could not remove temporary APNG frame", exc_info=True)
        if progress is not None:
            progress(index + 1, document.info.frame_count)

    cover_index = private.get("cover_index", 0)
    if isinstance(cover_index, bool) or not isinstance(cover_index, int):
        cover_index = 0
    if not 0 <= cover_index < len(pages):
        cover_index = 0
    pages[cover_index].is_cover = True
    reading_direction = private.get("reading_direction", "ltr")
    if reading_direction not in ("ltr", "rtl"):
        reading_direction = "ltr"
    book = ComicBook(
        pages=pages,
        metadata=copy.deepcopy(document.info.metadata),
        reading_direction=reading_direction,
        cover_duration_ms=_positive_integer(private.get("cover_duration_ms"), 10_000),
        body_duration_ms=_positive_integer(private.get("body_duration_ms"), 5_000),
    )
    book.validate()
    return book
