"""Safe EXIF, PNG text, and ComicAPNG metadata handling."""

from __future__ import annotations

import json
import re
import struct
from collections.abc import Mapping
from datetime import datetime
from fractions import Fraction
from typing import Any

from PIL import Image, TiffImagePlugin

from .exceptions import InvalidMetadataError
from .models import ComicMetadata, ExifValue

PRIVATE_METADATA_KEY = "ComicAPNG.Metadata"
PRIVATE_FORMAT_NAME = "ComicAPNG"
PRIVATE_SCHEMA_VERSION = 1
MAX_METADATA_FIELDS = 128
MAX_TEXT_VALUE_BYTES = 1_048_576
MAX_METADATA_TOTAL_BYTES = 4_194_304
MAX_PRIVATE_JSON_BYTES = 1_048_576
MAX_JSON_DEPTH = 20

STANDARD_EXIF_TAGS = {
    "description": 270,
    "artist": 315,
    "copyright": 33432,
    "software": 305,
    "datetime": 306,
    "user_comment": 37510,
}

_SPACE_RUN = re.compile(r" {2,}")


def validate_text_key(key: str) -> None:
    try:
        encoded = key.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise InvalidMetadataError("PNG text keys must use Latin-1 characters") from exc
    if not 1 <= len(encoded) <= 79:
        raise InvalidMetadataError("PNG text keys must contain 1 to 79 bytes")
    if b"\x00" in encoded:
        raise InvalidMetadataError("PNG text keys cannot contain null bytes")
    if key.startswith(" ") or key.endswith(" ") or _SPACE_RUN.search(key):
        raise InvalidMetadataError("PNG text keys have invalid spacing")


def validate_text_fields(fields: Mapping[str, str]) -> None:
    if len(fields) > MAX_METADATA_FIELDS:
        raise InvalidMetadataError("Too many PNG text fields")
    total = 0
    seen: set[bytes] = set()
    for key, value in fields.items():
        validate_text_key(key)
        folded = key.encode("latin-1").lower()
        if folded in seen:
            raise InvalidMetadataError("PNG text keys must be unique")
        seen.add(folded)
        encoded_value = value.encode("utf-8")
        if len(encoded_value) > MAX_TEXT_VALUE_BYTES:
            raise InvalidMetadataError("PNG text value is too long")
        total += len(key.encode("latin-1")) + len(encoded_value)
    if total > MAX_METADATA_TOTAL_BYTES:
        raise InvalidMetadataError("PNG text metadata is too large")


def _json_depth(value: Any, current: int = 0) -> int:
    if current > MAX_JSON_DEPTH:
        return current
    if isinstance(value, dict):
        return max((_json_depth(item, current + 1) for item in value.values()), default=current)
    if isinstance(value, list):
        return max((_json_depth(item, current + 1) for item in value), default=current)
    return current


def encode_private_metadata(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidMetadataError("ComicAPNG metadata is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_PRIVATE_JSON_BYTES:
        raise InvalidMetadataError("ComicAPNG metadata is too large")
    if _json_depth(value) > MAX_JSON_DEPTH:
        raise InvalidMetadataError("ComicAPNG metadata is nested too deeply")
    return encoded


def decode_private_metadata(value: str | None) -> dict[str, Any]:
    if not value or len(value.encode("utf-8")) > MAX_PRIVATE_JSON_BYTES:
        return {}
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, RecursionError):
        return {}
    if not isinstance(decoded, dict) or _json_depth(decoded) > MAX_JSON_DEPTH:
        return {}
    return decoded


def _encode_user_comment(value: str) -> bytes:
    try:
        ascii_value = value.encode("ascii")
    except UnicodeEncodeError:
        return b"UNICODE\x00" + value.encode("utf-16-be")
    return b"ASCII\x00\x00\x00" + ascii_value


def _decode_user_comment(value: bytes) -> str:
    if value.startswith(b"ASCII\x00\x00\x00"):
        return value[8:].decode("ascii", errors="replace")
    if value.startswith(b"UNICODE\x00"):
        return value[8:].decode("utf-16-be", errors="replace")
    return value.hex()


def parse_exif_value(tag_id: int, field: ExifValue) -> Any:
    if not 1 <= tag_id <= 65535:
        raise InvalidMetadataError("EXIF tag ID must be between 1 and 65535")
    if len(field.value.encode("utf-8")) > MAX_TEXT_VALUE_BYTES:
        raise InvalidMetadataError("EXIF value is too long")
    try:
        if field.value_type == "text":
            if "\x00" in field.value:
                raise ValueError
            if tag_id == 306:
                datetime.strptime(field.value, "%Y:%m:%d %H:%M:%S")
            return _encode_user_comment(field.value) if tag_id == 37510 else field.value
        if field.value_type == "integer":
            value = int(field.value, 10)
            if not -(2**31) <= value <= 2**32 - 1:
                raise ValueError
            return value
        if field.value_type == "rational":
            fraction = Fraction(field.value)
            if fraction.denominator == 0:
                raise ValueError
            return TiffImagePlugin.IFDRational(fraction.numerator, fraction.denominator)
        if field.value_type == "bytes":
            return bytes.fromhex(field.value)
    except (ValueError, ZeroDivisionError) as exc:
        raise InvalidMetadataError(f"Invalid value for EXIF tag {tag_id}") from exc
    raise InvalidMetadataError(f"Unsupported value type for EXIF tag {tag_id}")


def serialize_exif(fields: Mapping[int, ExifValue]) -> bytes:
    if len(fields) > MAX_METADATA_FIELDS:
        raise InvalidMetadataError("Too many EXIF fields")
    exif = Image.Exif()
    try:
        for tag_id, field in fields.items():
            exif[tag_id] = parse_exif_value(tag_id, field)
        data = exif.tobytes()
    except InvalidMetadataError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, struct.error) as exc:
        raise InvalidMetadataError("One or more EXIF fields cannot be serialized") from exc
    return data


def _exif_to_model(tag_id: int, value: Any) -> ExifValue:
    if isinstance(value, bytes):
        if tag_id == 37510:
            return ExifValue("text", _decode_user_comment(value))
        return ExifValue("bytes", value.hex())
    if isinstance(value, int):
        return ExifValue("integer", str(value))
    if isinstance(value, TiffImagePlugin.IFDRational):
        return ExifValue("rational", f"{value.numerator}/{value.denominator}")
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(item, int) for item in value)
    ):
        return ExifValue("rational", f"{value[0]}/{value[1]}")
    return ExifValue("text", str(value))


def read_metadata(image: Image.Image) -> ComicMetadata:
    exif_fields: dict[int, ExifValue] = {}
    try:
        for tag_id, value in image.getexif().items():
            exif_fields[int(tag_id)] = _exif_to_model(int(tag_id), value)
    except (AttributeError, OSError, TypeError, ValueError):
        exif_fields = {}

    raw_text = getattr(image, "text", {})
    text_fields: dict[str, str] = {}
    private_metadata: dict[str, Any] = {}
    if isinstance(raw_text, dict):
        for key, value in raw_text.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            if key == PRIVATE_METADATA_KEY:
                private_metadata = decode_private_metadata(value)
            elif len(text_fields) < MAX_METADATA_FIELDS:
                text_fields[key] = value
    return ComicMetadata(
        exif_fields=exif_fields,
        text_fields=text_fields,
        private_metadata=private_metadata,
    )
