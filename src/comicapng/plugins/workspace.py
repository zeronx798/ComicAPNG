"""Explicit session ownership for source materialization directories."""

from __future__ import annotations

import re
import shutil
from contextlib import suppress
from pathlib import Path
from threading import RLock

from platformdirs import user_cache_path

SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class SourceWorkspaceStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or user_cache_path("ComicAPNG", appauthor=False) / "sources").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.owned: set[Path] = set()
        self.retained: set[Path] = set()
        self.lock = RLock()

    def create(self, plugin_id: str, task_id: str) -> Path:
        plugin_component = SAFE_COMPONENT.sub("_", plugin_id).strip("._") or "plugin"
        task_component = SAFE_COMPONENT.sub("_", task_id).strip("._") or "task"
        destination = (self.root / plugin_component / task_component).resolve()
        with self.lock:
            self._require_owned_target(destination)
            destination.mkdir(parents=True, exist_ok=False)
            self.owned.add(destination)
        return destination

    def retain(self, path: Path) -> None:
        target = path.resolve()
        with self.lock:
            if target not in self.owned:
                raise ValueError("Only an owned source workspace can be retained")
            self.retained.add(target)

    def cleanup(self, path: Path) -> None:
        target = path.resolve()
        with self.lock:
            self._require_owned_target(target)
            if target not in self.owned:
                return
            shutil.rmtree(target, ignore_errors=False)
            self.owned.discard(target)
            self.retained.discard(target)
            parent = target.parent
            if parent != self.root:
                with suppress(OSError):
                    parent.rmdir()

    def cleanup_unretained(self) -> None:
        with self.lock:
            paths = tuple(self.owned - self.retained)
        for path in paths:
            self.cleanup(path)

    def close(self) -> None:
        with self.lock:
            paths = tuple(self.owned)
        for path in paths:
            with suppress(OSError):
                self.cleanup(path)

    def _require_owned_target(self, target: Path) -> None:
        if target == self.root or self.root not in target.parents:
            raise ValueError("Source workspace target is outside the cache root")
