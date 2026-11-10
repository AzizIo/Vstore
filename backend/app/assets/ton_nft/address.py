"""TON account address parsing and canonicalization (raw form)."""

from __future__ import annotations

import base64
import binascii
import re

_RAW_ADDRESS_RE = re.compile(r"^(-?\\d+):([0-9a-fA-F]{64})$")

class AddressError(ValueError):
    """An address is not a valid TON account address."""

def _crc16_xmodem(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def normalize_address(value: str) -> str:
    """Return a validated TON address as workchain:64-lowercase-hex."""
    if not isinstance(value, str):
        raise AddressError("Address must be a string")
    candidate = value.strip()
    match = _RAW_ADDRESS_RE.fullmatch(candidate)
    if match:
        workchain = int(match.group(1))
        if not -128 <= workchain <= 127:
            raise AddressError("Workchain is outside the TON address range")
        return f"{workchain}:{match.group(2).lower()}"
    try:
        encoded = candidate.replace("-", "+").replace("_", "/")
        payload = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AddressError("Address is neither raw nor valid friendly base64") from exc
    if len(payload) != 36:
        raise AddressError("Friendly address must decode to 36 bytes")
    body, checksum = payload[:34], payload[34:]
    if _crc16_xmodem(body).to_bytes(2, "big") != checksum:
        raise AddressError("Friendly address checksum is invalid")
    if (body[0] & 0x7F) not in (0x11, 0x51):
        raise AddressError("Unsupported friendly address tag")
    workchain = int.from_bytes(body[1:2], "big", signed=True)
    return f"{workchain}:{body[2:].hex()}"
