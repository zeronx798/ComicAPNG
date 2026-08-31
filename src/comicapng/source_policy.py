"""Automated source character policy checks."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

PRIMARY_SUFFIXES = {".py", ".toml", ".spec", ".ps1", ".sh", ".cmd", ".yml", ".yaml"}
PRIMARY_ROOTS = (".github", "src", "tests", "scripts")


def iter_primary_sources(project_root: Path) -> Iterator[Path]:
    for path in project_root.iterdir():
        if path.is_file() and path.suffix.casefold() in PRIMARY_SUFFIXES:
            yield path
    for relative in PRIMARY_ROOTS:
        directory = project_root / relative
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.casefold() in PRIMARY_SUFFIXES:
                yield path


def non_ascii_sources(project_root: Path) -> list[Path]:
    failures: list[Path] = []
    for path in iter_primary_sources(project_root):
        try:
            path.read_bytes().decode("ascii")
        except UnicodeDecodeError:
            failures.append(path)
    return sorted(failures)
