"""Application version synchronization tests."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from comicapng import __version__


def test_application_version_sources_match() -> None:
    project_root = Path(__file__).resolve().parents[1]
    with (project_root / "pyproject.toml").open("rb") as stream:
        project_version = tomllib.load(stream)["project"]["version"]

    assert project_version == __version__
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", __version__)
