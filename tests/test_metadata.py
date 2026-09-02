"""Tests for independent EXIF, text, and private metadata paths."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from comicapng.core.apng_reader import ApngDocument
from comicapng.core.apng_writer import write_apng
from comicapng.core.exceptions import InvalidMetadataError
from comicapng.core.metadata import (
    PRIVATE_METADATA_KEY,
    PRIVATE_SCHEMA_VERSION,
    encode_private_metadata,
    serialize_exif,
)
from comicapng.core.models import (
    ComicBook,
    ComicMetadata,
    ComicPage,
    ExifValue,
    SourceMetadata,
)


def _page(tmp_path: Path) -> Path:
    path = tmp_path / "page.png"
    Image.new("RGBA", (5, 7), (10, 20, 30, 255)).save(path)
    return path


def test_png_without_metadata_remains_readable(tmp_path: Path) -> None:
    path = _page(tmp_path)
    metadata = ApngDocument(path).info.metadata
    assert metadata.exif_fields == {}
    assert metadata.text_fields == {}
    assert metadata.private_metadata == {}


def test_exif_only_and_text_only_are_independent(tmp_path: Path) -> None:
    exif_path = tmp_path / "exif.png"
    text_path = tmp_path / "text.png"
    image = Image.new("RGB", (4, 4), (1, 2, 3))
    image.save(exif_path, exif=serialize_exif({270: ExifValue("text", "Description")}))
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_itxt("Publisher", "Example")
    image.save(text_path, pnginfo=pnginfo)
    image.close()

    exif_metadata = ApngDocument(exif_path).info.metadata
    text_metadata = ApngDocument(text_path).info.metadata
    assert exif_metadata.exif_fields[270].value == "Description"
    assert exif_metadata.text_fields == {}
    assert text_metadata.exif_fields == {}
    assert text_metadata.text_fields == {"Publisher": "Example"}


def test_malformed_private_json_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "malformed.png"
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_itxt(PRIVATE_METADATA_KEY, "{not-json")
    Image.new("RGBA", (3, 3)).save(path, pnginfo=pnginfo)
    assert ApngDocument(path).info.metadata.private_metadata == {}


def test_all_metadata_categories_round_trip_with_unicode_and_unknown_fields(
    tmp_path: Path,
) -> None:
    source = _page(tmp_path)
    output = tmp_path / "metadata.apng"
    unicode_value = "\u6d4b\u8bd5\u51fa\u7248\u793e"
    metadata = ComicMetadata(
        exif_fields={
            270: ExifValue("text", "Comic title"),
            271: ExifValue("text", "Custom maker"),
            37510: ExifValue("text", unicode_value),
        },
        text_fields={
            "Publisher": "Example Publisher",
            "CustomField": unicode_value,
        },
        private_metadata={"future_field": {"enabled": True}},
    )
    write_apng(
        ComicBook(pages=[ComicPage(source, None, 5, 7)], metadata=metadata),
        output,
    )

    result = ApngDocument(output).info.metadata
    assert result.exif_fields[270].value == "Comic title"
    assert result.exif_fields[271].value == "Custom maker"
    assert result.exif_fields[37510].value == unicode_value
    assert result.text_fields["Publisher"] == "Example Publisher"
    assert result.text_fields["CustomField"] == unicode_value
    assert result.private_metadata["future_field"] == {"enabled": True}
    assert result.private_metadata["format"] == "ComicAPNG"
    assert result.private_metadata["version"] == PRIVATE_SCHEMA_VERSION


def test_reserved_private_text_key_is_not_silently_discarded(tmp_path: Path) -> None:
    source = _page(tmp_path)
    book = ComicBook(
        pages=[ComicPage(source, None, 5, 7)],
        metadata=ComicMetadata(text_fields={PRIVATE_METADATA_KEY: "user value"}),
    )
    try:
        write_apng(book, tmp_path / "invalid.apng")
    except InvalidMetadataError:
        pass
    else:
        raise AssertionError("Reserved metadata key was accepted")


def test_source_metadata_accepts_only_json_values(tmp_path: Path) -> None:
    valid = SourceMetadata(
        "org.example.source",
        "resource-1",
        {
            "empty": None,
            "enabled": True,
            "count": 3,
            "ratio": 1.5,
            "tags": ["a", "b"],
            "nested": {"value": "safe"},
        },
    )
    valid.validate()
    with_path = SourceMetadata(
        "org.example.source",
        "resource-1",
        {"path": tmp_path},
    )
    with pytest.raises(ValueError, match="JSON values"):
        with_path.validate()
    not_finite = SourceMetadata(
        "org.example.source",
        "resource-1",
        {"value": float("nan")},
    )
    with pytest.raises(ValueError, match="finite"):
        not_finite.validate()


def test_private_metadata_rejects_non_finite_json_numbers() -> None:
    with pytest.raises(InvalidMetadataError, match="JSON serializable"):
        encode_private_metadata({"value": float("inf")})


def test_source_block_is_ignored_without_comicapng_format(tmp_path: Path) -> None:
    path = tmp_path / "foreign-private.png"
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_itxt(
        PRIVATE_METADATA_KEY,
        encode_private_metadata(
            {
                "format": "OtherFormat",
                "source": {
                    "plugin_id": "org.example.source",
                    "resource_id": "unsafe-assumption",
                },
            }
        ),
    )
    Image.new("RGBA", (3, 3)).save(path, pnginfo=pnginfo)
    metadata = ApngDocument(path).info.metadata
    assert metadata.source is None
    assert metadata.private_metadata["source"]["resource_id"] == "unsafe-assumption"
