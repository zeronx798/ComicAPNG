"""Tests for natural page ordering."""

from pathlib import Path

from comicapng.core.natural_sort import natural_sorted


def test_numeric_filename_runs_sort_as_numbers() -> None:
    values = [Path(name) for name in ("10.png", "2.png", "20.png", "1.png", "3.png")]
    assert [path.name for path in natural_sorted(values)] == [
        "1.png",
        "2.png",
        "3.png",
        "10.png",
        "20.png",
    ]


def test_prefixed_page_names_sort_naturally() -> None:
    values = [Path("page10.png"), Path("page2.png"), Path("page1.png")]
    assert [path.name for path in natural_sorted(values)] == [
        "page1.png",
        "page2.png",
        "page10.png",
    ]
