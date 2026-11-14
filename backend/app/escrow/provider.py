"""Provider protocol for finalized TON testnet escrow evidence.

TON Center/indexer data is treated as untrusted input. A concrete implementation
must normalize contract events only after ABI review and document its finality and
trace-verification guarantees. No live provider is enabled by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.escrow.domain import EscrowChainEventType


class EscrowProviderUnavailable(RuntimeError):
    """Provider is unavailable; the observer must preserve its cursor and retry."""


class EscrowProviderInvalidEvidence(ValueError):
    """Provider data is malformed, inconsistent or not independently verified."""


@dataclass(frozen=True, slots=True)
class NormalizedChainEvent:
    network: str
    transaction_hash: str
    event_index: int
    event_type: EscrowChainEventType
    contract_address: str
    deal_id: str | None
    source_address: str | None
    destination_address: str | None
    item_address: str | None
    amount_nanotons: int | None
    masterchain_seqno: int
    finalized: bool
    evidence_sha256: str
    cursor: str

    @property
    def event_key(self) -> str:
        return f"{self.network}:{self.transaction_hash}:{self.event_index}"


@dataclass(frozen=True, slots=True)
class ChainEventBatch:
    events: tuple[NormalizedChainEvent, ...]
    next_cursor: str | None


class TONTestnetEscrowProvider(Protocol):
    async def scan_events(
        self, *, cursor: str | None, limit: int
    ) -> ChainEventBatch: ...

    async def verify_event(self, event: NormalizedChainEvent) -> bool: ...


class UnconfiguredTONTestnetEscrowProvider:
    """Default provider. It never silently switches to mainnet or synthetic data."""

    async def scan_events(
        self, *, cursor: str | None, limit: int
    ) -> ChainEventBatch:
        del cursor, limit
        raise EscrowProviderUnavailable(
            "TON testnet escrow provider is not configured for the approved contract ABI"
        )

    async def verify_event(self, event: NormalizedChainEvent) -> bool:
        del event
        raise EscrowProviderUnavailable(
            "TON testnet escrow evidence verification is not configured"
        )
