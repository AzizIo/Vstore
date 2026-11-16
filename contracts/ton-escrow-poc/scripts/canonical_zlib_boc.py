#!/usr/bin/env python3
"""Build the canonical RFC 1950 / DEFLATE stream used for frozen DealEscrow BOCs.

This deliberately uses DEFLATE stored blocks (BTYPE=00). The stream is valid
zlib, byte-for-byte deterministic, and independent of the host zlib compressor
implementation/version. The trade-off is a small increase in artifact size.
"""
from __future__ import annotations

import struct
import zlib

_BLOCK_SIZE = 65_535
_ZLIB_HEADER = b"\x78\x01"


def canonical_zlib_boc(data: bytes) -> bytes:
    """Return the canonical zlib wrapper around *data* using stored DEFLATE blocks."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")

    output = bytearray(_ZLIB_HEADER)
    blocks = [
        data[offset : offset + _BLOCK_SIZE]
        for offset in range(0, len(data), _BLOCK_SIZE)
    ] or [b""]

    for index, block in enumerate(blocks):
        # A stored block starts on a byte boundary. BFINAL is the low bit;
        # BTYPE=00 and the remaining alignment bits are zero.
        output.append(0x01 if index == len(blocks) - 1 else 0x00)
        length = len(block)
        output.extend(struct.pack("<HH", length, length ^ 0xFFFF))
        output.extend(block)

    # RFC 1950 stores the Adler-32 checksum in network byte order.
    output.extend(struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF))
    return bytes(output)
