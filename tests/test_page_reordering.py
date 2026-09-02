"""Authoritative ComicBook page-reordering tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from comicapng.core.models import ComicBook, ComicPage


def _book(labels: str = "ABCDE") -> ComicBook:
    return ComicBook(
        pages=[ComicPage(Path(f"{label}.png"), None, 10, 10) for label in labels]
    )


def _order(book: ComicBook) -> list[str]:
    return [page.source_path.stem for page in book.pages if page.source_path is not None]


@pytest.mark.parametrize(
    ("source_index", "target_index", "expected"),
    [
        (1, 3, ["A", "C", "D", "B"]),
        (3, 1, ["A", "D", "B", "C"]),
        (0, 3, ["B", "C", "D", "A"]),
        (3, 0, ["D", "A", "B", "C"]),
        (1, 2, ["A", "C", "B", "D"]),
        (2, 1, ["A", "C", "B", "D"]),
    ],
)
def test_move_page_uses_final_index_semantics(
    source_index: int,
    target_index: int,
    expected: list[str],
) -> None:
    book = _book("ABCD")
    assert book.move_page(source_index, target_index) is True
    assert _order(book) == expected


def test_move_pages_preserves_relative_order_and_page_identity() -> None:
    book = _book()
    page_list = book.pages
    selected = (book.pages[1], book.pages[3])

    assert book.move_pages((1, 3), 2) is True

    assert book.pages is page_list
    assert _order(book) == ["A", "C", "B", "D", "E"]
    assert book.pages[2] is selected[0]
    assert book.pages[3] is selected[1]


def test_no_op_move_does_not_replace_or_modify_the_page_list() -> None:
    book = _book("ABC")
    original = book.pages
    identities = tuple(book.pages)

    assert book.move_page(1, 1) is False

    assert book.pages is original
    assert tuple(book.pages) == identities


def test_cover_identity_survives_every_move() -> None:
    book = _book("ABCD")
    cover = book.pages[2]
    book.set_cover(cover.page_id)

    book.move_page(2, 0)
    book.move_page(0, 3)
    book.move_page(3, 1)

    assert book.pages[1] is cover
    assert cover.is_cover is True
    assert sum(page.is_cover for page in book.pages) == 1
    assert book.export_pages()[0] is cover


def test_move_page_rejects_invalid_indexes() -> None:
    book = _book("ABC")
    with pytest.raises(IndexError):
        book.move_page(-1, 0)
    with pytest.raises(IndexError):
        book.move_page(0, 3)
    with pytest.raises(ValueError):
        book.move_pages((), 0)
