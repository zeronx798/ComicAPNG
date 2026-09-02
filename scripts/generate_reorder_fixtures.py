"""Generate visually varied local pages for manual Create reordering tests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from comicapng.extensions.test_source.reorder_fixtures import (  # noqa: E402
    generate_reorder_fixtures,
)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic ComicAPNG page-reordering fixtures."
    )
    parser.add_argument("--output", required=True, type=Path, help="Destination directory")
    options = parser.parse_args(arguments)
    generated = generate_reorder_fixtures(options.output.resolve())
    print(f"Generated {len(generated)} reorder fixtures in {options.output.resolve()}")
    for path in generated:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
