"""Typed domain models for read-only TON NFT verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_DATA = "invalid_data"
    OWNER_MISMATCH = "owner_mismatch"


@dataclass(frozen=True, slots=True)
class NFTMetadata:
    """Untrusted, display-only metadata; never proof of ownership."""

    name: str | None = None
    description: str | None = None
    image: str | None = None
    attributes: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class NFTItemSnapshot:
    address: str
    initialized: bool
    index: int
    collection_address: str | None
    owner_address: str
    metadata: NFTMetadata = field(default_factory=NFTMetadata)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    item_address: str
    owner_address: str | None = None
    collection_address: str | None = None
    item_index: int | None = None
    expected_owner_address: str | None = None
    metadata: NFTMetadata = field(default_factory=NFTMetadata)
    reason: str | None = None

    @property
    def is_verified(self) -> bool:
        return self.status is VerificationStatus.VERIFIED
