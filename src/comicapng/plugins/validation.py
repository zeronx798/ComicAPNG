"""Validation for files returned by source materialization."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from comicapng.core.exceptions import InvalidImageError, ResourceLimitError
from comicapng.core.image_files import inspect_image

from .api import MaterializedChapter
from .errors import PluginError, PluginErrorCode, PluginOperationError


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def validate_materialized_file(path: Path, destination: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PluginOperationError(
            PluginError(
                PluginErrorCode.PARTIAL_DOWNLOAD,
                "A source image is missing from the materialized result",
                str(path),
            )
        ) from exc
    if not resolved.is_file():
        raise PluginOperationError(
            PluginError(
                PluginErrorCode.PARTIAL_DOWNLOAD,
                "A source image is missing from the materialized result",
                str(path),
            )
        )
    if not _inside(resolved, destination):
        raise PluginOperationError(
            PluginError(
                PluginErrorCode.INVALID_SOURCE_DATA,
                "A plugin returned a file outside the provided destination",
                str(path),
            )
        )
    try:
        inspect_image(resolved)
        with Image.open(resolved) as image:
            image.load()
    except (InvalidImageError, ResourceLimitError, OSError, ValueError) as exc:
        raise PluginOperationError(
            PluginError(
                PluginErrorCode.PARTIAL_DOWNLOAD,
                "A materialized source image is not readable",
                str(path),
            )
        ) from exc
    return resolved


def validate_materialized_chapter(
    materialized: MaterializedChapter,
    destination: Path,
) -> MaterializedChapter:
    destination = destination.resolve(strict=True)
    if not materialized.pages:
        raise PluginOperationError(
            PluginError(
                PluginErrorCode.PARTIAL_DOWNLOAD,
                "The source returned no pages for the requested chapter",
            )
        )
    expected = list(range(1, len(materialized.pages) + 1))
    if [page.index for page in materialized.pages] != expected:
        raise PluginOperationError(
            PluginError(
                PluginErrorCode.INVALID_SOURCE_DATA,
                "The source returned invalid page indexes",
            )
        )
    pages = tuple(
        type(page)(
            plugin_id=page.plugin_id,
            source_id=page.source_id,
            chapter_id=page.chapter_id,
            index=page.index,
            local_path=validate_materialized_file(page.local_path, destination),
            metadata=page.metadata,
        )
        for page in materialized.pages
    )
    cover = (
        validate_materialized_file(materialized.cover_path, destination)
        if materialized.cover_path is not None
        else None
    )
    return MaterializedChapter(
        chapter=materialized.chapter,
        pages=pages,
        cover_path=cover,
        metadata=materialized.metadata,
    )
