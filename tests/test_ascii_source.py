"""Tests for the source and emoji character policies."""

from __future__ import annotations

import re
from pathlib import Path

from comicapng.source_policy import non_ascii_sources

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EMOJI_PATTERN = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f]")
TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".spec",
    ".ps1",
    ".sh",
    ".cmd",
    ".md",
    ".json",
    ".txt",
    ".yaml",
    ".yml",
}


def test_primary_source_files_are_ascii_only() -> None:
    assert non_ascii_sources(PROJECT_ROOT) == []


def test_project_text_contains_no_emoji() -> None:
    failures: list[Path] = []
    for path in PROJECT_ROOT.rglob("*"):
        if any(part in {".git", ".venv"} for part in path.parts):
            continue
        if path.is_file() and path.suffix.casefold() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            if EMOJI_PATTERN.search(text):
                failures.append(path.relative_to(PROJECT_ROOT))
    assert failures == []
