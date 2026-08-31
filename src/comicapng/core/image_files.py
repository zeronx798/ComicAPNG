"""Image discovery and safe header inspection."""

from __future__ import annotations

import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .exceptions import InvalidImageError, ResourceLimitError
from .natural_sort import natural_sorted

COMMON_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}


def discover_images(entries: list[Path]) -> list[Path]:
    """Discover common image files from files and directories."""
    found: dict[str, Path] = {}
    for entry in entries:
        if entry.is_dir():
            candidates = (path for path in entry.rglob("*") if path.is_file())
        else:
            candidates = (entry,)
        for path in candidates:
            if entry.is_file() or path.suffix.casefold() in COMMON_IMAGE_SUFFIXES:
                try:
                    key = str(path.resolve()).casefold()
                except OSError:
                    key = str(path.absolute()).casefold()
                found[key] = path
    return natural_sorted(list(found.values()))


def inspect_image(path: Path) -> tuple[int, int, str]:
    """Validate an image by content and return its oriented size and format."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image_format = image.format or ""
                width, height = image.size
                try:
                    orientation = int(image.getexif().get(274, 1))
                except (AttributeError, TypeError, ValueError, OSError):
                    orientation = 1
                if orientation in {5, 6, 7, 8}:
                    width, height = height, width
                if width <= 0 or height <= 0:
                    raise InvalidImageError("Image dimensions are invalid")
                return width, height, image_format
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ResourceLimitError(f"Image dimensions exceed safe limits: {path}") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageError(f"Cannot read image: {path}") from exc
