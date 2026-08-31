"""Small PNG chunk-writing helpers used by the APNG encoder."""

from __future__ import annotations

import binascii
import struct
from typing import BinaryIO

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_chunk(stream: BinaryIO, chunk_type: bytes, data: bytes) -> None:
    if len(chunk_type) != 4:
        raise ValueError("PNG chunk type must contain four bytes")
    stream.write(struct.pack(">I", len(data)))
    stream.write(chunk_type)
    stream.write(data)
    checksum = binascii.crc32(chunk_type)
    checksum = binascii.crc32(data, checksum) & 0xFFFFFFFF
    stream.write(struct.pack(">I", checksum))


def make_itxt(key: str, value: str) -> bytes:
    keyword = key.encode("latin-1")
    text = value.encode("utf-8")
    return keyword + b"\x00\x00\x00\x00\x00" + text
