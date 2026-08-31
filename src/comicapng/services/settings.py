"""Persistent application settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings


class AppSettings:
    """Typed facade over QSettings."""

    def __init__(self, backend: QSettings | None = None) -> None:
        self._settings = backend or QSettings("ComicAPNG", "ComicAPNG")

    def value(self, key: str, default: Any = None) -> Any:
        return self._settings.value(key, default)

    def set_value(self, key: str, value: Any) -> None:
        self._settings.setValue(key, value)

    def integer(self, key: str, default: int) -> int:
        try:
            return int(self.value(key, default))
        except (TypeError, ValueError):
            return default

    def boolean(self, key: str, default: bool) -> bool:
        value = self.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).casefold() in {"1", "true", "yes"}

    def last_directory(self, purpose: str) -> Path:
        value = str(self.value(f"directories/{purpose}", "") or "")
        path = Path(value) if value else Path.home()
        return path if path.exists() else Path.home()

    def set_last_directory(self, purpose: str, path: Path) -> None:
        directory = path if path.is_dir() else path.parent
        self.set_value(f"directories/{purpose}", str(directory))

    def recent_files(self) -> list[Path]:
        value = str(self.value("recent/files", "[]") or "[]")
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(decoded, list):
            return []
        return [Path(item) for item in decoded if isinstance(item, str)][:10]

    def add_recent_file(self, path: Path) -> None:
        normalized = str(path.resolve())
        files = [item for item in self.recent_files() if str(item) != normalized]
        files.insert(0, Path(normalized))
        self.set_value("recent/files", json.dumps([str(item) for item in files[:10]]))

    def sync(self) -> None:
        self._settings.sync()
