"""APNG-to-Create materialization tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from comicapng.core.apng_importer import import_apng
from comicapng.core.apng_reader import ApngDocument
from comicapng.core.apng_writer import write_apng
from comicapng.core.exceptions import InvalidApngError
from comicapng.core.metadata import PRIVATE_METADATA_KEY, encode_private_metadata
from comicapng.core.models import ComicBook, ComicMetadata, ComicPage, SourceMetadata


def _image(path: Path, size: tuple[int, int], color: tuple[int, int, int, int]) -> Path:
    Image.new("RGBA", size, color).save(path)
    return path


def test_comicapng_import_creates_normal_pages_and_preserves_private_data(
    tmp_path: Path,
) -> None:
    first = _image(tmp_path / "first.png", (20, 40), (210, 10, 20, 255))
    second = _image(tmp_path / "second.png", (50, 20), (10, 220, 30, 192))
    original = ComicBook(
        pages=[
            ComicPage(
                first,
                None,
                20,
                40,
                duration_ms=321,
                source_metadata={"source_page_index": 1},
            ),
            ComicPage(
                second,
                None,
                50,
                20,
                duration_ms=654,
                is_cover=True,
                source_metadata={"source_page_index": 2},
            ),
        ],
        metadata=ComicMetadata(
            text_fields={"Title": "Editable document"},
            private_metadata={"future": {"kept": True}},
            source=SourceMetadata(
                "org.comicapng.source.test",
                "fixture-comic",
                {"tags": ["fixture", "offline"]},
            ),
        ),
        reading_direction="rtl",
        cover_duration_ms=1800,
        body_duration_ms=900,
    )
    exported = tmp_path / "source.apng"
    write_apng(original, exported)

    imported = import_apng(exported, tmp_path / "workspace")
    assert all(type(page) is ComicPage for page in imported.pages)
    assert [
        (page.source_width, page.source_height) for page in imported.pages
    ] == [(50, 20), (20, 40)]
    assert [page.duration_ms for page in imported.pages] == [654, 321]
    assert [page.source_metadata["source_page_index"] for page in imported.pages] == [2, 1]
    assert imported.pages[0].is_cover is True
    assert imported.metadata.source is not None
    assert imported.metadata.source.resource_id == "fixture-comic"
    assert imported.metadata.source.data["tags"] == ["fixture", "offline"]
    assert imported.metadata.private_metadata["future"] == {"kept": True}
    assert imported.reading_direction == "rtl"
    assert imported.cover_duration_ms == 1800
    assert imported.body_duration_ms == 900

    cover = imported.pages[0]
    assert imported.move_page(0, 1) is True
    assert imported.pages[1] is cover
    assert cover.is_cover is True
    extra = _image(tmp_path / "extra.png", (30, 30), (10, 20, 230, 255))
    imported.pages.insert(1, ComicPage(extra, None, 30, 30, duration_ms=777))
    second_export = tmp_path / "edited.apng"
    write_apng(imported, second_export)

    document = ApngDocument(second_export)
    assert document.info.frame_count == 3
    assert document.info.canvas_size == (50, 40)
    assert [document.frame_duration_ms(index) for index in range(3)] == [654, 321, 777]
    assert document.info.metadata.source is not None
    assert document.info.metadata.source.resource_id == "fixture-comic"
    frame = document.load_frame(0)
    try:
        assert frame.getpixel((25, 25))[:3] == (10, 220, 30)
    finally:
        frame.close()


def test_generic_apng_import_uses_composited_canvas_and_durations(tmp_path: Path) -> None:
    output = tmp_path / "generic.apng"
    frames = [
        Image.new("RGBA", (24, 18), (240, 20, 30, 255)),
        Image.new("RGBA", (24, 18), (20, 220, 40, 128)),
    ]
    try:
        frames[0].save(
            output,
            format="PNG",
            save_all=True,
            append_images=frames[1:],
            duration=[125, 375],
            loop=0,
            disposal=[0, 0],
            blend=[0, 0],
        )
    finally:
        for frame in frames:
            frame.close()

    book = import_apng(output, tmp_path / "generic-workspace")
    assert len(book.pages) == 2
    assert [(page.source_width, page.source_height) for page in book.pages] == [
        (24, 18),
        (24, 18),
    ]
    assert [page.duration_ms for page in book.pages] == [125, 375]
    assert book.metadata.source is None
    assert book.pages[0].is_cover is True
    with Image.open(book.pages[1].source_path) as materialized:
        assert materialized.size == (24, 18)
        assert materialized.getpixel((12, 9)) == (20, 220, 40, 128)


def test_static_png_is_rejected_by_apng_import(tmp_path: Path) -> None:
    path = _image(tmp_path / "static.png", (8, 8), (1, 2, 3, 255))
    with pytest.raises(InvalidApngError, match="not animated"):
        import_apng(path, tmp_path / "workspace")


def test_one_page_comicapng_is_importable_but_static_png_is_not(tmp_path: Path) -> None:
    page_path = _image(tmp_path / "page.png", (11, 13), (20, 30, 40, 255))
    output = tmp_path / "one-page.apng"
    write_apng(
        ComicBook(pages=[ComicPage(page_path, None, 11, 13, is_cover=True)]),
        output,
    )
    assert ApngDocument(output).info.is_animated is True
    imported = import_apng(output, tmp_path / "one-page-workspace")
    assert len(imported.pages) == 1
    assert imported.pages[0].is_cover is True


def test_malformed_private_geometry_keeps_full_canvas_without_alpha_trim(
    tmp_path: Path,
) -> None:
    output = tmp_path / "malformed-geometry.apng"
    frames = [Image.new("RGBA", (30, 20)), Image.new("RGBA", (30, 20))]
    for index, frame in enumerate(frames):
        frame.paste((200 - index * 100, 20, 30, 255), (10, 5, 20, 15))
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_itxt(
        PRIVATE_METADATA_KEY,
        encode_private_metadata(
            {
                "format": "ComicAPNG",
                "version": 2,
                "pages": [
                    {
                        "source_width": 10,
                        "source_height": 10,
                        "render_width": 10,
                        "render_height": 10,
                        "offset_x": 1000,
                        "offset_y": 1000,
                    },
                    {},
                ],
            }
        ),
    )
    try:
        frames[0].save(
            output,
            format="PNG",
            save_all=True,
            append_images=frames[1:],
            duration=[100, 200],
            loop=0,
            pnginfo=pnginfo,
        )
    finally:
        for frame in frames:
            frame.close()

    imported = import_apng(output, tmp_path / "workspace")
    assert [(page.source_width, page.source_height) for page in imported.pages] == [
        (30, 20),
        (30, 20),
    ]
    with Image.open(imported.pages[0].source_path) as frame:
        assert frame.size == (30, 20)
        assert frame.getpixel((0, 0))[3] == 0
