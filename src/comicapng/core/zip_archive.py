"""Secure import and common export for the simple ComicAPNG ZIP format."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Any, BinaryIO

from PIL import Image, ImageOps

from .exceptions import (
    ArchiveWriteError,
    DestinationExistsError,
    InvalidArchiveError,
    InvalidMetadataError,
    OperationCancelledError,
    ResourceLimitError,
    UnsafeArchiveError,
)
from .image_files import COMMON_IMAGE_SUFFIXES, inspect_image
from .metadata import (
    PRIVATE_METADATA_KEY,
    encode_private_metadata,
    serialize_exif,
    validate_text_fields,
)
from .models import (
    ComicBook,
    ComicMetadata,
    ComicPage,
    ExifValue,
    ReadingDirection,
    SourceMetadata,
)
from .natural_sort import natural_sort_key

LOGGER = logging.getLogger(__name__)
ARCHIVE_METADATA_NAME = "metadata.json"
ARCHIVE_FORMAT_NAME = "ComicAPNG"
ARCHIVE_SCHEMA_VERSION = 1
MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_ENTRY_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_METADATA_BYTES = 8 * 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024

_PRIVATE_STRUCTURAL_KEYS = {
    "format",
    "version",
    "cover_index",
    "reading_direction",
    "cover_duration_ms",
    "body_duration_ms",
    "pages",
    "source",
}
_FORMAT_EXTENSIONS = {
    "BMP": ".bmp",
    "JPEG": ".jpg",
    "MPO": ".jpg",
    "PNG": ".png",
    "TIFF": ".tiff",
    "WEBP": ".webp",
}


class ZipMetadataStatus(StrEnum):
    ABSENT = "absent"
    VALID = "valid"
    MISMATCH = "mismatch"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class ArchiveDifferences:
    found: tuple[str, ...]
    referenced: tuple[str, ...]
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    invalid_references: tuple[str, ...] = ()


@dataclass(slots=True)
class _BookSettings:
    metadata: ComicMetadata
    reading_direction: ReadingDirection
    cover_duration_ms: int
    body_duration_ms: int


@dataclass(slots=True)
class ZipImportResult:
    """A prepared import that has not yet mutated the current document."""

    book: ComicBook
    metadata_status: ZipMetadataStatus
    differences: ArchiveDifferences | None = None
    metadata_error: str | None = None
    _remaining_settings: _BookSettings | None = None

    @property
    def can_import_remaining_metadata(self) -> bool:
        return self.metadata_status == ZipMetadataStatus.MISMATCH and self._remaining_settings is not None

    def book_with_remaining_metadata(self) -> ComicBook:
        if not self.can_import_remaining_metadata or self._remaining_settings is None:
            raise ValueError("No trusted non-page metadata is available")
        result = copy.deepcopy(self.book)
        settings = self._remaining_settings
        result.metadata = copy.deepcopy(settings.metadata)
        result.reading_direction = settings.reading_direction
        result.cover_duration_ms = settings.cover_duration_ms
        result.body_duration_ms = settings.body_duration_ms
        result.validate()
        return result


def _archive_name_is_safe(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name or len(name) > 4096:
        return False
    if name.startswith("/") or name.startswith("//"):
        return False
    candidate = name[:-1] if name.endswith("/") else name
    raw_parts = candidate.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return False
    return not (path.parts and ":" in path.parts[0])


def _natural_names(names: list[str]) -> list[str]:
    return sorted(names, key=lambda name: (natural_sort_key(name), name.casefold(), name))


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def _copy_stream(
    source: BinaryIO,
    destination: BinaryIO,
    cancel_event: Event | None,
    maximum_bytes: int | None = None,
) -> int:
    written = 0
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelledError("ZIP operation was cancelled")
        chunk = source.read(COPY_CHUNK_BYTES)
        if not chunk:
            return written
        if maximum_bytes is not None and written + len(chunk) > maximum_bytes:
            raise ResourceLimitError("A ZIP archive entry exceeds the size limit")
        destination.write(chunk)
        written += len(chunk)


@contextmanager
def _page_payload(page: ComicPage, temporary_directory: Path) -> Iterator[tuple[Path, str]]:
    if page.source_path is None:
        raise ArchiveWriteError("Editable pages must have materialized image files")
    source_path = Path(page.source_path)
    _width, _height, image_format = inspect_image(source_path)
    extension = _FORMAT_EXTENSIONS.get(image_format.upper())
    if extension is not None:
        yield source_path, extension
        return

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".comicapng-zip-page-",
            suffix=".png",
            dir=temporary_directory,
            delete=False,
        ) as stream:
            temporary_name = stream.name
        with Image.open(source_path) as image:
            normalized = ImageOps.exif_transpose(image).convert("RGBA")
            try:
                normalized.save(temporary_name, format="PNG")
            finally:
                normalized.close()
        yield Path(temporary_name), ".png"
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Could not remove temporary ZIP image", exc_info=True)


def _safe_private_metadata(metadata: ComicMetadata) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.private_metadata.items()
        if key not in _PRIVATE_STRUCTURAL_KEYS
    }


def _book_document(book: ComicBook) -> dict[str, Any]:
    value: dict[str, Any] = {
        "reading_direction": book.reading_direction,
        "cover_duration_ms": book.cover_duration_ms,
        "body_duration_ms": book.body_duration_ms,
    }
    if book.metadata.exif_fields:
        value["exif"] = {
            str(tag_id): {"type": field.value_type, "value": field.value}
            for tag_id, field in sorted(book.metadata.exif_fields.items())
        }
    if book.metadata.text_fields:
        value["text"] = dict(book.metadata.text_fields)
    private = _safe_private_metadata(book.metadata)
    if private:
        value["private"] = private
    return value


def _metadata_document(book: ComicBook, filenames: list[str]) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    cover: str | None = None
    for page, filename in zip(book.pages, filenames, strict=True):
        width, height, _image_format = inspect_image(page.source_path)  # type: ignore[arg-type]
        value: dict[str, Any] = {
            "filename": filename,
            "source_width": width,
            "source_height": height,
        }
        if page.duration_ms is not None:
            value["duration_ms"] = page.duration_ms
        if page.source_metadata:
            value["source"] = page.source_metadata
        pages.append(value)
        if page.is_cover:
            cover = filename
    document: dict[str, Any] = {
        "format": ARCHIVE_FORMAT_NAME,
        "version": ARCHIVE_SCHEMA_VERSION,
        "book": _book_document(book),
        "pages": pages,
    }
    if cover is not None:
        document["cover"] = cover
    if book.metadata.source is not None:
        document["source"] = book.metadata.source.to_dict()
    return document


def write_zip(
    book: ComicBook,
    output_path: Path,
    *,
    overwrite: bool = False,
    progress: Callable[[int, int], None] | None = None,
    cancel_event: Event | None = None,
) -> Path:
    """Write current editable order through the one common ZIP exporter."""
    book.validate()
    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        raise DestinationExistsError(f"Destination already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as stream:
            temporary_name = stream.name

        filenames: list[str] = []
        total_payload_bytes = 0
        with zipfile.ZipFile(
            temporary_name,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for index, page in enumerate(book.pages):
                with _page_payload(page, output_path.parent) as (payload_path, extension):
                    payload_size = payload_path.stat().st_size
                    if payload_size > MAX_ARCHIVE_ENTRY_BYTES:
                        raise ResourceLimitError("An image exceeds the ZIP entry size limit")
                    total_payload_bytes += payload_size
                    if total_payload_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                        raise ResourceLimitError("The ZIP output exceeds the total size limit")
                    filename = f"{index + 1}{extension}"
                    filenames.append(filename)
                    with (
                        payload_path.open("rb") as source,
                        archive.open(_zip_info(filename), "w", force_zip64=True) as target,
                    ):
                        _copy_stream(
                            source,
                            target,
                            cancel_event,
                            MAX_ARCHIVE_ENTRY_BYTES,
                        )
                if progress is not None:
                    progress(index + 1, len(book.pages))

            metadata = _metadata_document(book, filenames)
            validate_text_fields(book.metadata.text_fields)
            if book.metadata.exif_fields:
                serialize_exif(book.metadata.exif_fields)
            if _safe_private_metadata(book.metadata):
                encode_private_metadata(_safe_private_metadata(book.metadata))
            encoded_metadata = json.dumps(
                metadata,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8") + b"\n"
            if len(encoded_metadata) > MAX_ARCHIVE_METADATA_BYTES:
                raise InvalidMetadataError("Archive metadata is too large")
            if total_payload_bytes + len(encoded_metadata) > MAX_ARCHIVE_TOTAL_BYTES:
                raise ResourceLimitError("The ZIP output exceeds the total size limit")
            with archive.open(_zip_info(ARCHIVE_METADATA_NAME), "w") as target:
                target.write(encoded_metadata)

        if output_path.exists() and not overwrite:
            raise DestinationExistsError(f"Destination already exists: {output_path}")
        os.replace(temporary_name, output_path)
        temporary_name = None
        return output_path
    except (DestinationExistsError, InvalidMetadataError, OperationCancelledError):
        raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ArchiveWriteError("The ZIP archive could not be written") from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Could not remove temporary ZIP output", exc_info=True)


def _parse_positive(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Duration must be a positive integer")
    return value


def _parse_book_settings(value: object, source_value: object) -> _BookSettings:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("Book metadata must be an object")
    direction = value.get("reading_direction", "ltr")
    if direction not in ("ltr", "rtl"):
        raise ValueError("Reading direction is invalid")

    raw_exif = value.get("exif", {})
    if not isinstance(raw_exif, dict):
        raise ValueError("EXIF metadata must be an object")
    exif_fields: dict[int, ExifValue] = {}
    for raw_tag, raw_field in raw_exif.items():
        if not isinstance(raw_tag, str) or not raw_tag.isdecimal() or not isinstance(raw_field, dict):
            raise ValueError("EXIF metadata is invalid")
        value_type = raw_field.get("type")
        field_value = raw_field.get("value")
        if value_type not in ("text", "integer", "rational", "bytes"):
            raise ValueError("EXIF metadata type is invalid")
        if not isinstance(field_value, str):
            raise ValueError("EXIF metadata value is invalid")
        tag_id = int(raw_tag)
        if tag_id in exif_fields:
            raise ValueError("EXIF tag IDs must be unique")
        exif_fields[tag_id] = ExifValue(value_type, field_value)
    if exif_fields:
        serialize_exif(exif_fields)

    raw_text = value.get("text", {})
    if not isinstance(raw_text, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in raw_text.items()
    ):
        raise ValueError("PNG text metadata is invalid")
    text_fields = dict(raw_text)
    validate_text_fields(text_fields)
    if PRIVATE_METADATA_KEY in text_fields:
        raise ValueError("The reserved private metadata key cannot be used as PNG text")

    raw_private = value.get("private", {})
    if not isinstance(raw_private, dict):
        raise ValueError("Private metadata must be an object")
    private_metadata = dict(raw_private)
    if private_metadata:
        encode_private_metadata(private_metadata)

    source = None if source_value is None else SourceMetadata.from_dict(source_value)
    reading_direction: ReadingDirection = "rtl" if direction == "rtl" else "ltr"
    return _BookSettings(
        metadata=ComicMetadata(
            exif_fields=exif_fields,
            text_fields=text_fields,
            private_metadata=private_metadata,
            source=source,
        ),
        reading_direction=reading_direction,
        cover_duration_ms=_parse_positive(value.get("cover_duration_ms"), 10_000),
        body_duration_ms=_parse_positive(value.get("body_duration_ms"), 5_000),
    )


def _parse_metadata(value: object) -> tuple[_BookSettings, list[dict[str, Any]], str | None]:
    if not isinstance(value, dict):
        raise ValueError("Archive metadata must be an object")
    if value.get("format") != ARCHIVE_FORMAT_NAME:
        raise ValueError("Archive metadata format is unsupported")
    version = value.get("version")
    if isinstance(version, bool) or version != ARCHIVE_SCHEMA_VERSION:
        raise ValueError("Archive metadata version is unsupported")
    settings = _parse_book_settings(value.get("book"), value.get("source"))
    raw_pages = value.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise ValueError("Archive page metadata must be a non-empty list")
    pages: list[dict[str, Any]] = []
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict):
            raise ValueError("Archive page metadata is invalid")
        filename = raw_page.get("filename")
        if not isinstance(filename, str) or not _archive_name_is_safe(filename):
            raise ValueError("Archive page filename is invalid")
        duration = raw_page.get("duration_ms")
        if duration is not None:
            _parse_positive(duration, 1)
        for dimension_key in ("source_width", "source_height"):
            dimension = raw_page.get(dimension_key)
            if dimension is not None and (
                isinstance(dimension, bool)
                or not isinstance(dimension, int)
                or dimension <= 0
            ):
                raise ValueError("Archive page geometry is invalid")
        source = raw_page.get("source", {})
        if not isinstance(source, dict):
            raise ValueError("Archive page source metadata is invalid")
        pages.append(dict(raw_page))
    cover = value.get("cover")
    if cover is not None and (not isinstance(cover, str) or not _archive_name_is_safe(cover)):
        raise ValueError("Archive cover reference is invalid")
    return settings, pages, cover


def _new_image_book(names: list[str], paths: dict[str, Path]) -> ComicBook:
    pages: list[ComicPage] = []
    for name in names:
        width, height, _image_format = inspect_image(paths[name])
        pages.append(
            ComicPage(
                source_path=paths[name],
                source_width=width,
                source_height=height,
                is_cover=not pages,
            )
        )
    book = ComicBook(pages=pages)
    book.validate()
    return book


def _trusted_book(
    settings: _BookSettings,
    records: list[dict[str, Any]],
    cover: str | None,
    paths: dict[str, Path],
) -> ComicBook:
    pages: list[ComicPage] = []
    for record in records:
        filename = str(record["filename"])
        width, height, _image_format = inspect_image(paths[filename])
        page = ComicPage(
            source_path=paths[filename],
            source_width=width,
            source_height=height,
            duration_ms=record.get("duration_ms"),
            is_cover=filename == cover,
            source_metadata=dict(record.get("source", {})),
        )
        page.validate()
        pages.append(page)
    book = ComicBook(
        pages=pages,
        metadata=copy.deepcopy(settings.metadata),
        reading_direction=settings.reading_direction,
        cover_duration_ms=settings.cover_duration_ms,
        body_duration_ms=settings.body_duration_ms,
    )
    book.validate()
    return book


def _metadata_bytes(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > MAX_ARCHIVE_METADATA_BYTES:
        raise ValueError("metadata.json is too large")
    try:
        with archive.open(info, "r") as stream:
            data = stream.read(MAX_ARCHIVE_METADATA_BYTES + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ValueError("metadata.json could not be read") from exc
    if len(data) > MAX_ARCHIVE_METADATA_BYTES:
        raise ValueError("metadata.json is too large")
    return data


def _inspect_entries(archive: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], zipfile.ZipInfo | None]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ResourceLimitError("The ZIP archive contains too many files")
    total = 0
    names: set[str] = set()
    image_infos: list[zipfile.ZipInfo] = []
    metadata_info: zipfile.ZipInfo | None = None
    for info in infos:
        name = info.filename
        if not _archive_name_is_safe(name.rstrip("/")):
            raise UnsafeArchiveError("The ZIP archive contains an unsafe path")
        if info.is_dir():
            continue
        if name in names:
            raise InvalidArchiveError("The ZIP archive contains duplicate file names")
        names.add(name)
        if info.file_size < 0 or info.file_size > MAX_ARCHIVE_ENTRY_BYTES:
            raise ResourceLimitError("A ZIP archive entry exceeds the size limit")
        total += info.file_size
        if total > MAX_ARCHIVE_TOTAL_BYTES:
            raise ResourceLimitError("The ZIP archive exceeds the total size limit")
        if name == ARCHIVE_METADATA_NAME:
            metadata_info = info
        elif PurePosixPath(name).suffix.casefold() in COMMON_IMAGE_SUFFIXES:
            if info.flag_bits & 0x1:
                raise InvalidArchiveError("Encrypted image entries are not supported")
            image_infos.append(info)
    if not image_infos:
        raise InvalidArchiveError("The ZIP archive contains no supported images")
    return image_infos, metadata_info


def import_zip(
    input_path: Path,
    workspace: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancel_event: Event | None = None,
) -> ZipImportResult:
    """Prepare a secure all-or-nothing ZIP metadata import."""
    input_path = Path(input_path)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    metadata_info: zipfile.ZipInfo | None = None
    metadata_data: bytes | None = None
    actual_total_bytes = 0
    try:
        with zipfile.ZipFile(input_path, "r", allowZip64=True) as archive:
            image_infos, metadata_info = _inspect_entries(archive)
            for index, info in enumerate(image_infos):
                if cancel_event is not None and cancel_event.is_set():
                    raise OperationCancelledError("ZIP import was cancelled")
                suffix = PurePosixPath(info.filename).suffix.casefold()
                destination = workspace / f"image-{index + 1}{suffix}"
                actual_bytes = 0
                try:
                    with archive.open(info, "r") as source, destination.open("xb") as target:
                        actual_bytes = _copy_stream(
                            source,
                            target,
                            cancel_event,
                            MAX_ARCHIVE_ENTRY_BYTES,
                        )
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    raise InvalidArchiveError("A ZIP image entry could not be read") from exc
                if actual_bytes > MAX_ARCHIVE_ENTRY_BYTES:
                    raise ResourceLimitError("A ZIP archive entry exceeds the size limit")
                actual_total_bytes += actual_bytes
                if actual_total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ResourceLimitError("The ZIP archive exceeds the total size limit")
                inspect_image(destination)
                paths[info.filename] = destination
                if progress is not None:
                    progress(index + 1, len(image_infos))
            if metadata_info is not None:
                try:
                    metadata_data = _metadata_bytes(archive, metadata_info)
                    actual_total_bytes += len(metadata_data)
                    if actual_total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                        raise ResourceLimitError(
                            "The ZIP archive exceeds the total size limit"
                        )
                except ValueError:
                    metadata_data = None
    except (InvalidArchiveError, OperationCancelledError, ResourceLimitError):
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise InvalidArchiveError("The ZIP archive could not be opened") from exc

    natural_names = _natural_names(list(paths))
    image_only = _new_image_book(natural_names, paths)
    if metadata_info is None:
        return ZipImportResult(image_only, ZipMetadataStatus.ABSENT)
    if metadata_data is None:
        return ZipImportResult(
            image_only,
            ZipMetadataStatus.MALFORMED,
            metadata_error="metadata.json could not be read safely",
        )

    try:
        raw_metadata = json.loads(metadata_data.decode("utf-8"))
        settings, records, cover = _parse_metadata(raw_metadata)
    except (InvalidMetadataError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        return ZipImportResult(
            image_only,
            ZipMetadataStatus.MALFORMED,
            metadata_error=str(exc),
        )

    referenced = [str(record["filename"]) for record in records]
    found_set = set(paths)
    referenced_set = set(referenced)
    invalid_references: list[str] = []
    binding_matches = len(referenced) == len(referenced_set) and referenced_set == found_set
    if cover is not None and cover not in referenced_set:
        binding_matches = False
        invalid_references.append(cover)
    if binding_matches:
        try:
            book = _trusted_book(settings, records, cover, paths)
        except (InvalidMetadataError, ValueError):
            return ZipImportResult(
                image_only,
                ZipMetadataStatus.MALFORMED,
                metadata_error="Page metadata could not be validated",
            )
        return ZipImportResult(book, ZipMetadataStatus.VALID)

    differences = ArchiveDifferences(
        found=tuple(natural_names),
        referenced=tuple(referenced),
        missing=tuple(name for name in referenced if name not in found_set),
        unexpected=tuple(name for name in natural_names if name not in referenced_set),
        invalid_references=tuple(invalid_references),
    )
    remaining = copy.deepcopy(settings)
    return ZipImportResult(
        image_only,
        ZipMetadataStatus.MISMATCH,
        differences=differences,
        _remaining_settings=remaining,
    )
