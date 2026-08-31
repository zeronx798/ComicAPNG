"""APNG geometry, ordering, timing, transparency, and cache tests."""

from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

from comicapng.core.apng_reader import ApngDocument, FrameCache
from comicapng.core.apng_writer import write_apng
from comicapng.core.models import ComicBook, ComicPage


def _save(path: Path, size: tuple[int, int], color: tuple[int, int, int, int]) -> None:
    Image.new("RGBA", size, color).save(path)


def _frame_controls(path: Path) -> list[tuple[int, ...]]:
    data = path.read_bytes()
    offset = 8
    controls: list[tuple[int, ...]] = []
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        if chunk_type == b"fcTL":
            controls.append(struct.unpack(">IIIIIHHBB", payload))
        offset += length + 12
    return controls


def test_two_frame_round_trip_is_full_canvas_cover_first(tmp_path: Path) -> None:
    portrait = tmp_path / "portrait.png"
    landscape = tmp_path / "landscape.png"
    output = tmp_path / "comic.apng"
    _save(portrait, (10, 20), (250, 20, 30, 255))
    _save(landscape, (20, 10), (20, 240, 30, 128))
    book = ComicBook(
        pages=[
            ComicPage(portrait, None, 10, 20),
            ComicPage(landscape, None, 20, 10, is_cover=True),
        ],
        cover_duration_ms=3000,
        body_duration_ms=1000,
    )

    write_apng(book, output)
    document = ApngDocument(output)
    assert document.info.frame_count == 2
    assert document.info.canvas_size == (20, 20)
    assert document.frame_duration_ms(0) == 3000
    assert document.frame_duration_ms(1) == 1000

    controls = _frame_controls(output)
    assert len(controls) == 2
    assert all(control[1:5] == (20, 20, 0, 0) for control in controls)
    assert all(control[-2:] == (0, 0) for control in controls)

    cover = document.load_frame(0)
    body = document.load_frame(1)
    try:
        assert cover.getpixel((10, 10)) == (20, 240, 30, 128)
        assert cover.getpixel((10, 0))[3] == 0
        assert body.getpixel((10, 10)) == (250, 20, 30, 255)
        assert body.getpixel((0, 10))[3] == 0
    finally:
        cover.close()
        body.close()


def test_many_frame_round_trip_preserves_order_and_per_page_timing(tmp_path: Path) -> None:
    pages: list[ComicPage] = []
    for index in range(12):
        path = tmp_path / f"{index}.png"
        _save(path, (8, 8), (index * 15, 10, 200, 255))
        pages.append(ComicPage(path, None, 8, 8, duration_ms=100 + index))
    output = tmp_path / "many.apng"
    write_apng(ComicBook(pages=pages), output)

    document = ApngDocument(output)
    assert document.info.frame_count == 12
    for index in range(12):
        frame = document.load_frame(index)
        try:
            assert frame.getpixel((4, 4))[0] == index * 15
            assert document.frame_duration_ms(index) == 100 + index
        finally:
            frame.close()


def test_frame_cache_remains_bounded(tmp_path: Path) -> None:
    pages: list[ComicPage] = []
    for index in range(6):
        path = tmp_path / f"cache-{index}.png"
        _save(path, (4, 4), (index, 0, 0, 255))
        pages.append(ComicPage(path, None, 4, 4))
    output = tmp_path / "cache.apng"
    write_apng(ComicBook(pages=pages), output)
    cache = FrameCache(ApngDocument(output), capacity=3)
    for index in range(6):
        frame = cache.get(index)
        frame.close()
    assert len(cache) == 3
    assert cache.indices() == (3, 4, 5)
    cache.clear()
