"""Bounded-memory APNG frame access."""

from __future__ import annotations

import struct
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from PIL import Image, UnidentifiedImageError

from .exceptions import InvalidApngError, ResourceLimitError
from .metadata import PRIVATE_FORMAT_NAME, read_metadata
from .models import ComicMetadata
from .png_chunks import PNG_SIGNATURE


def _has_animation_control(path: Path) -> bool:
    """Distinguish a one-frame APNG from an ordinary static PNG."""
    with path.open("rb") as stream:
        if stream.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
            return False
        has_animation_control = False
        for _index in range(4096):
            header = stream.read(8)
            if len(header) != 8:
                return False
            length, chunk_type = struct.unpack(">I4s", header)
            if chunk_type == b"acTL":
                if length != 8:
                    return False
                payload = stream.read(8)
                if len(payload) != 8:
                    return False
                has_animation_control = struct.unpack(">I", payload[:4])[0] > 0
                stream.seek(4, 1)
                continue
            if chunk_type == b"fcTL" and has_animation_control:
                return length == 26
            if chunk_type == b"IEND":
                return False
            stream.seek(length + 4, 1)
    return False


@dataclass(frozen=True, slots=True)
class ApngInfo:
    path: Path
    canvas_size: tuple[int, int]
    frame_count: int
    is_animated: bool
    has_default_image: bool
    metadata: ComicMetadata
    raw_exif: bytes | None


class ApngDocument:
    """A frame-access abstraction that decodes individual frames on demand."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(self.path) as image:
                    if image.format != "PNG":
                        raise InvalidApngError("The selected file is not a PNG image")
                    image.load()
                    has_default = bool(image.info.get("default_image", False))
                    physical_count = int(getattr(image, "n_frames", 1))
                    logical_count = physical_count - 1 if has_default else physical_count
                    if logical_count <= 0:
                        raise InvalidApngError("The PNG does not contain readable frames")
                    self.info = ApngInfo(
                        path=self.path,
                        canvas_size=image.size,
                        frame_count=logical_count,
                        is_animated=_has_animation_control(self.path),
                        has_default_image=has_default,
                        metadata=read_metadata(image),
                        raw_exif=image.info.get("exif")
                        if isinstance(image.info.get("exif"), bytes)
                        else None,
                    )
        except (InvalidApngError, ResourceLimitError):
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ResourceLimitError(f"PNG dimensions exceed safe limits: {self.path}") from exc
        except (UnidentifiedImageError, OSError, ValueError, EOFError) as exc:
            raise InvalidApngError(f"Cannot open PNG/APNG: {self.path}") from exc

    def _physical_index(self, logical_index: int) -> int:
        if not 0 <= logical_index < self.info.frame_count:
            raise IndexError("Frame index is out of range")
        return logical_index + (1 if self.info.has_default_image else 0)

    def load_frame(self, logical_index: int) -> Image.Image:
        """Decode and return one fully composited RGBA frame."""
        physical_index = self._physical_index(logical_index)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(self.path) as image:
                    image.seek(physical_index)
                    image.load()
                    return image.convert("RGBA").copy()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ResourceLimitError(f"Frame {logical_index + 1} exceeds safe limits") from exc
        except MemoryError as exc:
            raise ResourceLimitError(
                f"Not enough memory to decode frame {logical_index + 1}"
            ) from exc
        except (OSError, ValueError, EOFError) as exc:
            raise InvalidApngError(f"Cannot decode frame {logical_index + 1}") from exc

    def frame_duration_ms(self, logical_index: int) -> int:
        physical_index = self._physical_index(logical_index)
        try:
            with Image.open(self.path) as image:
                image.seek(physical_index)
                return max(1, round(float(image.info.get("duration", 1000))))
        except (OSError, ValueError, EOFError, TypeError) as exc:
            raise InvalidApngError(f"Cannot read frame {logical_index + 1} timing") from exc

    def original_geometry(self, logical_index: int) -> dict[str, int] | None:
        """Return validated private page geometry, when available."""
        private = self.info.metadata.private_metadata
        if private.get("format") != PRIVATE_FORMAT_NAME:
            return None
        pages = private.get("pages")
        if not isinstance(pages, list) or not 0 <= logical_index < len(pages):
            return None
        value = pages[logical_index]
        if not isinstance(value, dict):
            return None
        keys = (
            "source_width",
            "source_height",
            "render_width",
            "render_height",
            "offset_x",
            "offset_y",
        )
        if any(not isinstance(value.get(key), int) for key in keys):
            return None
        geometry = {key: int(value[key]) for key in keys}
        canvas_width, canvas_height = self.info.canvas_size
        if (
            min(
                geometry["source_width"],
                geometry["source_height"],
                geometry["render_width"],
                geometry["render_height"],
            )
            <= 0
        ):
            return None
        if geometry["offset_x"] < 0 or geometry["offset_y"] < 0:
            return None
        if geometry["offset_x"] + geometry["render_width"] > canvas_width:
            return None
        if geometry["offset_y"] + geometry["render_height"] > canvas_height:
            return None
        return geometry


class FrameCache:
    """Thread-safe least-recently-used cache for a small number of frames."""

    def __init__(self, document: ApngDocument, capacity: int = 5) -> None:
        if capacity <= 0:
            raise ValueError("Cache capacity must be positive")
        self.document = document
        self.capacity = capacity
        self._frames: OrderedDict[int, Image.Image] = OrderedDict()
        self._lock = RLock()

    def get(self, index: int) -> Image.Image:
        with self._lock:
            cached = self._frames.get(index)
            if cached is not None:
                self._frames.move_to_end(index)
                return cached.copy()
        frame = self.document.load_frame(index)
        with self._lock:
            existing = self._frames.get(index)
            if existing is not None:
                frame.close()
                self._frames.move_to_end(index)
                return existing.copy()
            self._frames[index] = frame
            while len(self._frames) > self.capacity:
                _old_index, old_frame = self._frames.popitem(last=False)
                old_frame.close()
            return frame.copy()

    def prefetch(self, indices: list[int]) -> None:
        for index in indices:
            if 0 <= index < self.document.info.frame_count:
                frame = self.get(index)
                frame.close()

    def clear(self) -> None:
        with self._lock:
            for frame in self._frames.values():
                frame.close()
            self._frames.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)

    def indices(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(self._frames)
