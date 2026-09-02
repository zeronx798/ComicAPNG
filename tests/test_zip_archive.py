"""Simple archive format, trust-boundary, and security tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from comicapng.core.exceptions import InvalidArchiveError, ResourceLimitError, UnsafeArchiveError
from comicapng.core.models import (
    ComicBook,
    ComicMetadata,
    ComicPage,
    ExifValue,
    SourceMetadata,
)
from comicapng.core.zip_archive import (
    ARCHIVE_METADATA_NAME,
    ZipMetadataStatus,
    import_zip,
    write_zip,
)


def _save(path: Path, image_format: str, color: tuple[int, int, int]) -> Path:
    Image.new("RGB", (12, 9), color).save(path, format=image_format)
    return path


def _sample_book(tmp_path: Path) -> tuple[ComicBook, dict[str, Path]]:
    paths = {
        "red": _save(tmp_path / "red.png", "PNG", (240, 10, 20)),
        "green": _save(tmp_path / "green.jpg", "JPEG", (10, 230, 30)),
        "blue": _save(tmp_path / "blue.webp", "WEBP", (20, 30, 230)),
    }
    book = ComicBook(
        pages=[
            ComicPage(
                paths["green"],
                None,
                12,
                9,
                duration_ms=111,
                source_metadata={"label": "green", "source_page_index": 7},
            ),
            ComicPage(
                paths["blue"],
                None,
                12,
                9,
                duration_ms=222,
                is_cover=True,
                source_metadata={"label": "blue", "source_page_index": 8},
            ),
            ComicPage(
                paths["red"],
                None,
                12,
                9,
                duration_ms=333,
                source_metadata={"label": "red", "source_page_index": 9},
            ),
        ],
        metadata=ComicMetadata(
            exif_fields={270: ExifValue("text", "Archive title")},
            text_fields={"Title": "Archive title", "UserTags": "edited"},
            private_metadata={"future": {"value": 3}},
            source=SourceMetadata(
                "org.comicapng.source.jmcomic",
                "123456",
                {"tags": ["tag-a", "tag-b"], "views": 42},
            ),
        ),
        reading_direction="rtl",
        cover_duration_ms=2500,
        body_duration_ms=750,
    )
    return book, paths


def _rewrite(
    source: Path,
    destination: Path,
    *,
    transform_metadata=None,
    rename: dict[str, str] | None = None,
    drop: set[str] | None = None,
    additions: dict[str, bytes] | None = None,
) -> Path:
    rename = rename or {}
    drop = drop or set()
    additions = additions or {}
    with zipfile.ZipFile(source, "r") as input_archive:
        values = {name: input_archive.read(name) for name in input_archive.namelist()}
    if transform_metadata is not None:
        metadata = json.loads(values[ARCHIVE_METADATA_NAME])
        transform_metadata(metadata)
        values[ARCHIVE_METADATA_NAME] = json.dumps(metadata).encode("utf-8")
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output_archive:
        for name, data in values.items():
            if name not in drop:
                output_archive.writestr(rename.get(name, name), data)
        for name, data in additions.items():
            output_archive.writestr(name, data)
    return destination


def test_zip_round_trip_preserves_order_bytes_metadata_and_source(tmp_path: Path) -> None:
    book, paths = _sample_book(tmp_path)
    output = tmp_path / "document.zip"
    write_zip(book, output)

    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["1.jpg", "2.webp", "3.png", ARCHIVE_METADATA_NAME]
        assert archive.read("1.jpg") == paths["green"].read_bytes()
        assert archive.read("2.webp") == paths["blue"].read_bytes()
        assert archive.read("3.png") == paths["red"].read_bytes()
        metadata = json.loads(archive.read(ARCHIVE_METADATA_NAME))
    assert metadata["format"] == "ComicAPNG"
    assert metadata["version"] == 1
    assert [page["filename"] for page in metadata["pages"]] == [
        "1.jpg",
        "2.webp",
        "3.png",
    ]
    assert metadata["cover"] == "2.webp"
    assert metadata["source"]["resource_id"] == "123456"

    result = import_zip(output, tmp_path / "imported")
    assert result.metadata_status == ZipMetadataStatus.VALID
    imported = result.book
    assert [page.source_metadata["label"] for page in imported.pages] == [
        "green",
        "blue",
        "red",
    ]
    assert [page.duration_ms for page in imported.pages] == [111, 222, 333]
    assert [page.is_cover for page in imported.pages] == [False, True, False]
    assert imported.reading_direction == "rtl"
    assert imported.cover_duration_ms == 2500
    assert imported.body_duration_ms == 750
    assert imported.metadata.text_fields["UserTags"] == "edited"
    assert imported.metadata.exif_fields[270].value == "Archive title"
    assert imported.metadata.private_metadata == {"future": {"value": 3}}
    assert imported.metadata.source is not None
    assert imported.metadata.source.plugin_id == "org.comicapng.source.jmcomic"
    assert imported.metadata.source.resource_id == "123456"
    assert imported.metadata.source.data["tags"] == ["tag-a", "tag-b"]

    assert imported.move_page(2, 0) is True
    assert [page.source_metadata["label"] for page in imported.pages] == [
        "red",
        "green",
        "blue",
    ]
    second_output = tmp_path / "document-again.zip"
    write_zip(imported, second_output)
    second = import_zip(second_output, tmp_path / "imported-again").book
    assert [page.source_metadata["label"] for page in second.pages] == [
        "red",
        "green",
        "blue",
    ]
    assert second.metadata.source is not None
    assert second.metadata.source.resource_id == "123456"


def test_zip_export_normalizes_an_unretained_format_to_png(tmp_path: Path) -> None:
    source = tmp_path / "page.gif"
    Image.new("RGB", (9, 7), (10, 20, 30)).save(source, format="GIF")
    output = tmp_path / "normalized.zip"
    write_zip(
        ComicBook(pages=[ComicPage(source, None, 9, 7, is_cover=True)]),
        output,
    )
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["1.png", ARCHIVE_METADATA_NAME]
        materialized = tmp_path / "normalized.png"
        materialized.write_bytes(archive.read("1.png"))
    with Image.open(materialized) as image:
        assert image.format == "PNG"
        assert image.size == (9, 7)


def test_zip_without_metadata_uses_natural_filename_order(tmp_path: Path) -> None:
    archive_path = tmp_path / "images.zip"
    colors = {
        "10.png": (10, 0, 0),
        "2.png": (2, 0, 0),
        "1.png": (1, 0, 0),
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, color in colors.items():
            image_path = _save(tmp_path / f"source-{name}", "PNG", color)
            archive.write(image_path, name)
        archive.writestr("README.txt", "ignored")

    result = import_zip(archive_path, tmp_path / "workspace")
    assert result.metadata_status == ZipMetadataStatus.ABSENT
    values: list[int] = []
    for page in result.book.pages:
        with Image.open(page.source_path) as image:
            values.append(image.getpixel((0, 0))[0])
    assert values == [1, 2, 10]
    assert result.book.pages[0].is_cover is True


@pytest.mark.parametrize(
    ("name", "rewrite_options"),
    [
        ("missing", {"drop": {"2.webp"}}),
        ("unexpected", {"additions": {"4.png": b"PLACEHOLDER"}}),
        ("renamed", {"rename": {"2.webp": "02.webp"}}),
        ("same-count-different", {"rename": {"2.webp": "other.webp"}}),
    ],
)
def test_one_filename_mismatch_invalidates_all_page_metadata(
    tmp_path: Path,
    name: str,
    rewrite_options: dict[str, object],
) -> None:
    book, paths = _sample_book(tmp_path)
    valid = tmp_path / "valid.zip"
    write_zip(book, valid)
    if name == "unexpected":
        rewrite_options = {
            "additions": {"4.png": paths["red"].read_bytes()},
        }
    changed = _rewrite(valid, tmp_path / f"{name}.zip", **rewrite_options)

    result = import_zip(changed, tmp_path / f"workspace-{name}")
    assert result.metadata_status == ZipMetadataStatus.MISMATCH
    assert result.differences is not None
    assert all(page.duration_ms is None for page in result.book.pages)
    assert all(page.source_metadata == {} for page in result.book.pages)
    assert result.book.metadata.text_fields == {}
    assert result.book.metadata.source is None
    assert result.book.pages[0].is_cover is True

    remaining = result.book_with_remaining_metadata()
    assert remaining.metadata.text_fields["Title"] == "Archive title"
    assert remaining.metadata.source is not None
    assert remaining.metadata.source.resource_id == "123456"
    assert remaining.metadata.private_metadata == {"future": {"value": 3}}
    assert all(page.duration_ms is None for page in remaining.pages)
    assert all(page.source_metadata == {} for page in remaining.pages)


def test_matching_set_uses_metadata_order(tmp_path: Path) -> None:
    book, _paths = _sample_book(tmp_path)
    valid = tmp_path / "valid.zip"
    write_zip(book, valid)

    def reorder(metadata: dict[str, object]) -> None:
        pages = metadata["pages"]
        assert isinstance(pages, list)
        metadata["pages"] = [pages[2], pages[0], pages[1]]

    changed = _rewrite(
        valid,
        tmp_path / "metadata-order.zip",
        transform_metadata=reorder,
    )
    result = import_zip(changed, tmp_path / "workspace")
    assert result.metadata_status == ZipMetadataStatus.VALID
    assert [page.source_metadata["label"] for page in result.book.pages] == [
        "red",
        "green",
        "blue",
    ]


def test_invalid_cover_reference_invalidates_page_metadata(tmp_path: Path) -> None:
    book, _paths = _sample_book(tmp_path)
    valid = tmp_path / "valid.zip"
    write_zip(book, valid)

    def invalid_cover(metadata: dict[str, object]) -> None:
        metadata["cover"] = "missing.png"

    changed = _rewrite(valid, tmp_path / "cover-mismatch.zip", transform_metadata=invalid_cover)
    result = import_zip(changed, tmp_path / "workspace")
    assert result.metadata_status == ZipMetadataStatus.MISMATCH
    assert result.differences is not None
    assert result.differences.invalid_references == ("missing.png",)
    assert all(page.duration_ms is None for page in result.book.pages)


def test_malformed_metadata_allows_image_only_import(tmp_path: Path) -> None:
    book, _paths = _sample_book(tmp_path)
    valid = tmp_path / "valid.zip"
    write_zip(book, valid)
    with zipfile.ZipFile(valid) as archive:
        values = {
            name: archive.read(name)
            for name in archive.namelist()
            if name != ARCHIVE_METADATA_NAME
        }
    changed = tmp_path / "malformed.zip"
    with zipfile.ZipFile(changed, "w") as archive:
        for name, data in values.items():
            archive.writestr(name, data)
        archive.writestr(ARCHIVE_METADATA_NAME, b"{not-json")

    result = import_zip(changed, tmp_path / "workspace")
    assert result.metadata_status == ZipMetadataStatus.MALFORMED
    assert len(result.book.pages) == 3
    assert result.book.metadata.source is None
    assert all(page.duration_ms is None for page in result.book.pages)


@pytest.mark.parametrize(
    "unsafe_name",
    ["../../outside.txt", "/absolute.txt", "C:/drive.txt", "..\\outside.txt"],
)
def test_zip_path_traversal_is_rejected_without_writing_outside_workspace(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    image = _save(tmp_path / "safe.png", "PNG", (1, 2, 3))
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(image, "safe.png")
        archive.writestr(unsafe_name, "unsafe")
    workspace = tmp_path / "workspace"
    with pytest.raises(UnsafeArchiveError):
        import_zip(archive_path, workspace)
    assert not (tmp_path / "outside.txt").exists()


def test_corrupted_zip_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "broken.zip"
    path.write_bytes(b"not a zip archive")
    with pytest.raises(InvalidArchiveError):
        import_zip(path, tmp_path / "workspace")


def test_archive_entry_limit_is_enforced(tmp_path: Path, monkeypatch) -> None:
    import comicapng.core.zip_archive as archive_module

    image = _save(tmp_path / "large.png", "PNG", (1, 2, 3))
    archive_path = tmp_path / "large.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(image, "large.png")
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_ENTRY_BYTES", 2)
    with pytest.raises(ResourceLimitError):
        import_zip(archive_path, tmp_path / "workspace")


def test_archive_file_count_and_total_limits_are_enforced(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import comicapng.core.zip_archive as archive_module

    image = _save(tmp_path / "image.png", "PNG", (1, 2, 3))
    archive_path = tmp_path / "limits.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(image, "image.png")
        archive.writestr("README.txt", "ignored")

    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_ENTRIES", 1)
    with pytest.raises(ResourceLimitError, match="too many"):
        import_zip(archive_path, tmp_path / "count-workspace")

    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_ENTRIES", 10)
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_TOTAL_BYTES", 2)
    with pytest.raises(ResourceLimitError, match="total"):
        import_zip(archive_path, tmp_path / "total-workspace")


def test_oversized_metadata_falls_back_to_images_only(tmp_path: Path, monkeypatch) -> None:
    import comicapng.core.zip_archive as archive_module

    image = _save(tmp_path / "image.png", "PNG", (1, 2, 3))
    archive_path = tmp_path / "metadata-limit.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(image, "image.png")
        archive.writestr(ARCHIVE_METADATA_NAME, b"{}" * 20)
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_METADATA_BYTES", 8)

    result = import_zip(archive_path, tmp_path / "workspace")
    assert result.metadata_status == ZipMetadataStatus.MALFORMED
    assert len(result.book.pages) == 1
