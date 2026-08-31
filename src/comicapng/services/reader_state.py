"""Stable comic identity and external reading-position storage."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from .settings import AppSettings

FINGERPRINT_SAMPLE_SIZE = 65_536


def book_fingerprint(path: Path) -> str:
    """Fingerprint a file using size plus samples from both ends."""
    path = Path(path)
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(struct.pack(">Q", stat.st_size))
    with path.open("rb") as stream:
        digest.update(stream.read(FINGERPRINT_SAMPLE_SIZE))
        if stat.st_size > FINGERPRINT_SAMPLE_SIZE:
            stream.seek(max(0, stat.st_size - FINGERPRINT_SAMPLE_SIZE))
            digest.update(stream.read(FINGERPRINT_SAMPLE_SIZE))
    return digest.hexdigest()


class ReaderStateStore:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def position(self, fingerprint: str, frame_count: int) -> int:
        value = self._settings.integer(f"reader/positions/{fingerprint}", 0)
        return max(0, min(value, max(0, frame_count - 1)))

    def set_position(self, fingerprint: str, index: int) -> None:
        self._settings.set_value(f"reader/positions/{fingerprint}", max(0, index))
