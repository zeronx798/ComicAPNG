"""Deterministic visual reorder-fixture tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from comicapng.extensions.test_source.reorder_fixtures import (
    REORDER_FIXTURE_SPECS,
    generate_reorder_fixtures,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generator_creates_ten_varied_pages_in_stable_order(tmp_path: Path) -> None:
    first = generate_reorder_fixtures(tmp_path / "first")
    second = generate_reorder_fixtures(tmp_path / "second")

    assert [path.name for path in first] == [f"page-{index:02d}.png" for index in range(1, 11)]
    assert [_digest(path) for path in first] == [_digest(path) for path in second]
    assert len({_digest(path) for path in first}) == 10

    actual_sizes: list[tuple[int, int]] = []
    for path, spec in zip(first, REORDER_FIXTURE_SPECS, strict=True):
        with Image.open(path) as image:
            image.load()
            actual_sizes.append(image.size)
            assert image.mode == "RGBA"
            assert image.getpixel((image.width // 2, image.height // 2))[:3] == spec.probe_color
    assert actual_sizes == [spec.size for spec in REORDER_FIXTURE_SPECS]
    assert len(set(actual_sizes)) == 10
