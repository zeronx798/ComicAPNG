"""Classify GitHub workflow contexts under the ComicAPNG release policy."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Literal

ReleaseKind = Literal["none", "stable", "rc"]

STABLE_TAG_PATTERN = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
RC_TAG_PATTERN = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+$")


class InvalidReleaseTag(ValueError):
    """Raised when a pushed tag is not a supported ComicAPNG release tag."""


def classify_release_context(event_name: str, ref: str) -> ReleaseKind:
    """Return the release kind for a GitHub event, or reject a malformed tag."""
    if event_name != "push" or not ref.startswith("refs/tags/"):
        return "none"

    tag = ref.removeprefix("refs/tags/")
    if STABLE_TAG_PATTERN.fullmatch(tag):
        return "stable"
    if RC_TAG_PATTERN.fullmatch(tag):
        return "rc"
    raise InvalidReleaseTag(
        f"Unsupported ComicAPNG release tag '{tag}'. "
        "Expected vX.Y.Z or vX.Y.Z-rc.N with numeric components. "
        "The tag was not changed."
    )


def _write_github_output(release_kind: ReleaseKind) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as stream:
        stream.write(f"release_kind={release_kind}\n")


def main() -> int:
    try:
        release_kind = classify_release_context(
            os.environ.get("GITHUB_EVENT_NAME", ""),
            os.environ.get("GITHUB_REF", ""),
        )
    except InvalidReleaseTag as exc:
        print(f"::error title=Invalid ComicAPNG release tag::{exc}", file=sys.stderr)
        return 2

    _write_github_output(release_kind)
    print(f"ComicAPNG release kind: {release_kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
