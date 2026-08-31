"""Disk-backed thumbnail cache for source images and APNG frames."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
import warnings
from pathlib import Path

from PIL import Image, ImageOps
from platformdirs import user_cache_path

from comicapng.core.apng_reader import ApngDocument
from comicapng.core.exceptions import ResourceLimitError

LOGGER = logging.getLogger(__name__)
DEFAULT_MAX_AGE_DAYS = 60


class ThumbnailCache:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or user_cache_path("ComicAPNG", appauthor=False) / "thumbnails"
        self.directory.mkdir(parents=True, exist_ok=True)

    def _source_key(self, path: Path, size: tuple[int, int]) -> str:
        stat = path.stat()
        value = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{size[0]}x{size[1]}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _frame_key(self, identity: str, index: int, size: tuple[int, int]) -> str:
        value = f"{identity}|{index}|{size[0]}x{size[1]}"
        return hashlib.sha256(value.encode("ascii")).hexdigest()

    def _save(self, image: Image.Image, destination: Path, size: tuple[int, int]) -> Path:
        thumbnail = image.convert("RGBA")
        thumbnail.thumbnail(size, Image.Resampling.LANCZOS)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=self.directory,
                delete=False,
            ) as stream:
                temporary_name = stream.name
                thumbnail.save(stream, format="PNG")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
            return destination
        finally:
            thumbnail.close()
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

    def source_thumbnail(self, path: Path, size: tuple[int, int]) -> Path:
        destination = self.directory / f"{self._source_key(path, size)}.png"
        if destination.exists():
            return destination
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    image.draft("RGBA", size)
                    image.load()
                    oriented = ImageOps.exif_transpose(image)
                    return self._save(oriented, destination, size)
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ResourceLimitError(f"Image dimensions exceed safe limits: {path}") from exc
        except MemoryError as exc:
            raise ResourceLimitError(f"Not enough memory to create thumbnail: {path}") from exc

    def frame_thumbnail(
        self,
        document: ApngDocument,
        identity: str,
        index: int,
        size: tuple[int, int],
    ) -> Path:
        destination = self.directory / f"{self._frame_key(identity, index, size)}.png"
        if destination.exists():
            return destination
        frame = document.load_frame(index)
        try:
            return self._save(frame, destination, size)
        finally:
            frame.close()

    def prune(self, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> None:
        cutoff = time.time() - max_age_days * 86400
        for path in self.directory.glob("*.png"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                LOGGER.debug("Could not prune thumbnail", exc_info=True)
