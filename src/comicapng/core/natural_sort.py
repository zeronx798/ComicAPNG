"""Natural filename sorting."""

from __future__ import annotations

import re
from pathlib import Path

_PARTS = re.compile(r"(\d+)")


def natural_sort_key(value: str | Path) -> tuple[object, ...]:
    """Return a case-insensitive key with numeric runs compared as integers."""
    text = Path(value).name if isinstance(value, Path) else value
    return tuple(int(part) if part.isdigit() else part.casefold() for part in _PARTS.split(text))


def natural_sorted(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=lambda path: (natural_sort_key(path.name), str(path).casefold()))
