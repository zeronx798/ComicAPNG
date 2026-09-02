"""Metadata-independent APNG frame extraction."""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from threading import Event

from PIL import Image, PngImagePlugin

from .apng_reader import ApngDocument
from .exceptions import DestinationExistsError, InvalidMetadataError, OperationCancelledError
from .metadata import validate_text_fields

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int], None]


def _output_png_info(document: ApngDocument) -> PngImagePlugin.PngInfo:
    pnginfo = PngImagePlugin.PngInfo()
    for key, value in document.info.metadata.text_fields.items():
        try:
            validate_text_fields({key: value})
        except InvalidMetadataError:
            LOGGER.warning("Skipping invalid PNG text field during extraction")
            continue
        pnginfo.add_itxt(key, value)
    return pnginfo


def restore_frame_bounds(
    frame: Image.Image,
    geometry: dict[str, int] | None,
) -> Image.Image:
    if geometry is None:
        return frame
    left = geometry["offset_x"]
    top = geometry["offset_y"]
    right = left + geometry["render_width"]
    bottom = top + geometry["render_height"]
    restored = frame.crop((left, top, right, bottom))
    target_size = (geometry["source_width"], geometry["source_height"])
    if restored.size != target_size:
        resized = restored.resize(target_size, Image.Resampling.LANCZOS)
        restored.close()
        restored = resized
    frame.close()
    return restored


_restore_original_bounds = restore_frame_bounds


def extract_apng(
    input_path: Path,
    output_directory: Path,
    *,
    overwrite: bool = False,
    restore_original_bounds: bool = False,
    progress: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> list[Path]:
    """Extract logical APNG frames as 1.png through N.png."""
    document = ApngDocument(input_path)
    output_directory = Path(output_directory)
    destinations = [
        output_directory / f"{index + 1}.png" for index in range(document.info.frame_count)
    ]
    conflicts = [path for path in destinations if path.exists()]
    if conflicts and not overwrite:
        raise DestinationExistsError(f"Destination already exists: {conflicts[0]}")
    output_directory.mkdir(parents=True, exist_ok=True)
    pnginfo = _output_png_info(document)

    completed: list[Path] = []
    for index, destination in enumerate(destinations):
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelledError("APNG extraction was cancelled")
        frame = document.load_frame(index)
        if restore_original_bounds:
            frame = restore_frame_bounds(frame, document.original_geometry(index))
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=output_directory,
                delete=False,
            ) as stream:
                temporary_name = stream.name
                save_options: dict[str, object] = {
                    "format": "PNG",
                    "pnginfo": pnginfo,
                }
                if document.info.raw_exif:
                    save_options["exif"] = document.info.raw_exif
                frame.save(stream, **save_options)
                stream.flush()
                os.fsync(stream.fileno())
            if destination.exists() and not overwrite:
                raise DestinationExistsError(f"Destination already exists: {destination}")
            os.replace(temporary_name, destination)
            temporary_name = None
            completed.append(destination)
        finally:
            frame.close()
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Could not remove temporary extracted frame", exc_info=True)
        if progress is not None:
            progress(index + 1, document.info.frame_count)
    return completed
