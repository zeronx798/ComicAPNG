"""Exit with an error when primary source files are not ASCII-only."""

from __future__ import annotations

import sys
from pathlib import Path

from comicapng.source_policy import non_ascii_sources


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    failures = non_ascii_sources(project_root)
    if failures:
        for path in failures:
            sys.stderr.write(f"Non-ASCII source: {path.relative_to(project_root)}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
