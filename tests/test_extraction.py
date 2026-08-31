"""Tests for metadata-independent numeric APNG extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from comicapng.core.apng_reader import ApngDocument
from comicapng.core.apng_writer import write_apng
from comicapng.core.exceptions import DestinationExistsError
from comicapng.core.extractor import extract_apng
from comicapng.core.models import ComicBook, ComicMetadata, ComicPage, ExifValue


def test_generic_apng_extracts_without_comicapng_metadata(tmp_path: Path) -> None:
    input_path = tmp_path / "generic.png"
    first = Image.new("RGBA", (6, 6), (255, 0, 0, 255))
    second = Image.new("RGBA", (6, 6), (0, 255, 0, 255))
    first.save(
        input_path,
        save_all=True,
        append_images=[second],
        duration=[200, 300],
        loop=0,
    )
    first.close()
    second.close()

    output = tmp_path / "pages"
    paths = extract_apng(input_path, output)
    assert [path.name for path in paths] == ["1.png", "2.png"]
    assert Image.open(paths[0]).getpixel((3, 3))[:3] == (255, 0, 0)
    assert Image.open(paths[1]).getpixel((3, 3))[:3] == (0, 255, 0)


def test_metadata_geometry_can_restore_original_bounds(tmp_path: Path) -> None:
    portrait = tmp_path / "portrait.png"
    landscape = tmp_path / "landscape.png"
    Image.new("RGBA", (10, 20), (255, 0, 0, 255)).save(portrait)
    Image.new("RGBA", (20, 10), (0, 255, 0, 255)).save(landscape)
    comic = tmp_path / "comic.apng"
    write_apng(
        ComicBook(
            pages=[
                ComicPage(portrait, None, 10, 20),
                ComicPage(landscape, None, 20, 10),
            ]
        ),
        comic,
    )
    paths = extract_apng(comic, tmp_path / "restored", restore_original_bounds=True)
    with Image.open(paths[0]) as first, Image.open(paths[1]) as second:
        assert first.size == (10, 20)
        assert second.size == (20, 10)


def test_extraction_refuses_unsafe_overwrite_by_default(tmp_path: Path) -> None:
    input_path = tmp_path / "static.png"
    Image.new("RGBA", (3, 3), (1, 2, 3, 4)).save(input_path)
    output = tmp_path / "pages"
    output.mkdir()
    existing = output / "1.png"
    existing.write_bytes(b"keep")
    with pytest.raises(DestinationExistsError):
        extract_apng(input_path, output)
    assert existing.read_bytes() == b"keep"


def test_extraction_preserves_user_metadata_but_not_container_json(tmp_path: Path) -> None:
    source = tmp_path / "metadata-source.png"
    Image.new("RGBA", (4, 5), (40, 50, 60, 255)).save(source)
    comic = tmp_path / "metadata-comic.apng"
    write_apng(
        ComicBook(
            pages=[ComicPage(source, None, 4, 5)],
            metadata=ComicMetadata(
                exif_fields={270: ExifValue("text", "Page description")},
                text_fields={"Publisher": "Example"},
            ),
        ),
        comic,
    )
    extracted = extract_apng(comic, tmp_path / "metadata-pages")[0]
    metadata = ApngDocument(extracted).info.metadata
    assert metadata.exif_fields[270].value == "Page description"
    assert metadata.text_fields == {"Publisher": "Example"}
    assert metadata.private_metadata == {}
