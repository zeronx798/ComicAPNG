"""Streaming full-canvas APNG writer."""

from __future__ import annotations

import logging
import math
import os
import struct
import tempfile
import warnings
import zlib
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import BinaryIO

from PIL import Image, ImageOps

from .exceptions import (
    DestinationExistsError,
    InvalidImageError,
    InvalidMetadataError,
    OperationCancelledError,
    ResourceLimitError,
)
from .image_files import inspect_image
from .image_layout import PageLayout, calculate_canvas, calculate_fit, render_to_canvas
from .metadata import (
    PRIVATE_FORMAT_NAME,
    PRIVATE_METADATA_KEY,
    PRIVATE_SCHEMA_VERSION,
    encode_private_metadata,
    serialize_exif,
    validate_text_fields,
)
from .models import ComicBook, ComicPage
from .png_chunks import PNG_SIGNATURE, make_itxt, write_chunk

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int], None]
MAX_CHUNK_BYTES = 1_048_576


def _delay_fraction(duration_ms: int) -> tuple[int, int]:
    if not 1 <= duration_ms <= 65_535_000:
        raise ValueError("Frame duration is outside the APNG range")
    divisor = math.gcd(duration_ms, 1000)
    numerator = duration_ms // divisor
    denominator = 1000 // divisor
    if numerator > 65535:
        numerator = 65535
        denominator = max(1, round(numerator * 1000 / duration_ms))
    return numerator, denominator


def _frame_control(sequence: int, size: tuple[int, int], duration_ms: int) -> bytes:
    delay_num, delay_den = _delay_fraction(duration_ms)
    width, height = size
    return struct.pack(
        ">IIIIIHHBB",
        sequence,
        width,
        height,
        0,
        0,
        delay_num,
        delay_den,
        0,
        0,
    )


def _write_compressed_frame(
    stream: BinaryIO,
    image: Image.Image,
    first_frame: bool,
    sequence: int,
    cancel_event: Event | None,
) -> int:
    compressor = zlib.compressobj(level=6)
    pending = bytearray()

    def flush_chunks(force: bool = False) -> None:
        nonlocal sequence
        while len(pending) >= MAX_CHUNK_BYTES or (force and pending):
            count = min(len(pending), MAX_CHUNK_BYTES)
            payload = bytes(pending[:count])
            del pending[:count]
            if first_frame:
                write_chunk(stream, b"IDAT", payload)
            else:
                write_chunk(stream, b"fdAT", struct.pack(">I", sequence) + payload)
                sequence += 1

    width, height = image.size
    for y in range(height):
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelledError("APNG export was cancelled")
        row_image = image.crop((0, y, width, y + 1))
        try:
            row = b"\x00" + row_image.tobytes("raw", "RGBA")
        finally:
            row_image.close()
        pending.extend(compressor.compress(row))
        flush_chunks()
    pending.extend(compressor.flush())
    flush_chunks(force=True)
    return sequence


def _private_document(
    book: ComicBook,
    pages: list[ComicPage],
    layouts: list[PageLayout],
    durations: list[int],
) -> dict[str, object]:
    document = dict(book.metadata.private_metadata)
    document.update(
        {
            "format": PRIVATE_FORMAT_NAME,
            "version": PRIVATE_SCHEMA_VERSION,
            "cover_index": 0,
            "reading_direction": book.reading_direction,
            "pages": [
                {
                    "source_width": layout.source_width,
                    "source_height": layout.source_height,
                    "render_width": layout.render_width,
                    "render_height": layout.render_height,
                    "offset_x": layout.offset_x,
                    "offset_y": layout.offset_y,
                    "duration_ms": duration,
                }
                for _page, layout, duration in zip(pages, layouts, durations, strict=True)
            ],
        }
    )
    return document


def _load_page(page: ComicPage) -> Image.Image:
    if page.source_path is None:
        raise InvalidImageError("Creator pages require source image paths")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(page.source_path) as source:
                source.load()
                return ImageOps.exif_transpose(source).convert("RGBA")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ResourceLimitError(
            f"Image dimensions exceed safe limits: {page.source_path}"
        ) from exc
    except MemoryError as exc:
        raise ResourceLimitError(f"Not enough memory to decode image: {page.source_path}") from exc
    except (OSError, ValueError) as exc:
        raise InvalidImageError(f"Cannot decode image: {page.source_path}") from exc


def write_apng(
    book: ComicBook,
    output_path: Path,
    *,
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> Path:
    """Write a standards-compliant APNG with complete independent RGBA frames."""
    book.validate()
    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        raise DestinationExistsError(f"Destination already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pages = book.export_pages()
    actual_sizes = [
        inspect_image(page.source_path)[0:2]
        if page.source_path is not None
        else (page.source_width, page.source_height)
        for page in pages
    ]
    canvas_size = calculate_canvas(actual_sizes)
    layouts = [calculate_fit(source_size, canvas_size) for source_size in actual_sizes]
    durations = [book.duration_for_export_index(page, index) for index, page in enumerate(pages)]
    validate_text_fields(book.metadata.text_fields)
    if PRIVATE_METADATA_KEY in book.metadata.text_fields:
        raise InvalidMetadataError("The ComicAPNG metadata key is reserved")
    exif_data = serialize_exif(book.metadata.exif_fields) if book.metadata.exif_fields else b""
    private_json = encode_private_metadata(_private_document(book, pages, layouts, durations))

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as stream:
            temporary_name = stream.name
            stream.write(PNG_SIGNATURE)
            width, height = canvas_size
            write_chunk(stream, b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            if exif_data:
                if exif_data.startswith(b"Exif\x00\x00"):
                    exif_data = exif_data[6:]
                write_chunk(stream, b"eXIf", exif_data)
            for key, value in book.metadata.text_fields.items():
                if key == PRIVATE_METADATA_KEY:
                    continue
                write_chunk(stream, b"iTXt", make_itxt(key, value))
            write_chunk(stream, b"iTXt", make_itxt(PRIVATE_METADATA_KEY, private_json))
            write_chunk(stream, b"acTL", struct.pack(">II", len(pages), 0))

            sequence = 0
            for index, page in enumerate(pages):
                if cancel_event is not None and cancel_event.is_set():
                    raise OperationCancelledError("APNG export was cancelled")
                write_chunk(
                    stream,
                    b"fcTL",
                    _frame_control(sequence, canvas_size, durations[index]),
                )
                sequence += 1
                source = _load_page(page)
                try:
                    frame, _layout = render_to_canvas(source, canvas_size)
                    try:
                        sequence = _write_compressed_frame(
                            stream,
                            frame,
                            index == 0,
                            sequence,
                            cancel_event,
                        )
                    finally:
                        frame.close()
                finally:
                    source.close()
                if progress is not None:
                    progress(index + 1, len(pages))
            write_chunk(stream, b"IEND", b"")
            stream.flush()
            os.fsync(stream.fileno())
        if output_path.exists() and not overwrite:
            raise DestinationExistsError(f"Destination already exists: {output_path}")
        os.replace(temporary_name, output_path)
        temporary_name = None
        return output_path
    except OperationCancelledError:
        LOGGER.info("APNG export cancelled")
        raise
    except Exception:
        LOGGER.exception("APNG export failed")
        raise
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Could not remove temporary export file", exc_info=True)
