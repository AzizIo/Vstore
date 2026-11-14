"""TON testnet event normalization boundary.

Non-final or incomplete observations may be replayed and promoted to final. The
provider must include stable message/trace identifiers where available. No live
provider is enabled before ABI approval.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from app.escrow.domain import EscrowChainEventType


class EscrowProviderUnavailable(RuntimeError):
    """Provider outage; cursor remains durable and can be retried."""


class EscrowProviderInvalidEvidence(ValueError):
    """Malformed or inconsistent normalized chain evidence."""


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
    collection_address: str | None = None
    message_hash: str | None = None
    trace_id: str | None = None
    logical_time: int | None = None
    phase: str | None = None
    attempt_id: str | None = None
    query_id: str | None = None
    operation_id: str | None = None
    deal_salt: str | None = None
    account_address: str | None = None
    observed_contract_state: str | None = None
    attestation_accepted: bool = False
    contract_state_reconciled: bool = False

    @property
    def event_key(self) -> str:
        # Stable across pending -> final. Distinct traces/phases/attempts and
        # query/operation IDs are separate attempts, not duplicates.
        identity = (
            self.network, self.transaction_hash,
            self.message_hash or f"idx-{self.event_index}",
            self.trace_id or "trace-unknown",
            self.phase or "phase-unknown",
            self.attempt_id or "attempt-unknown",
        )
        return hashlib.sha256(
            json.dumps(identity, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ChainEventBatch:
    events: tuple[NormalizedChainEvent, ...]
    next_cursor: str | None


class TONTestnetEscrowProvider(Protocol):
    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch: ...
    async def verify_event(self, event: NormalizedChainEvent) -> bool: ...


class UnconfiguredTONTestnetEscrowProvider:
    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch:
        del cursor, limit
        raise EscrowProviderUnavailable("TON escrow testnet provider is not configured")

    async def verify_event(self, event: NormalizedChainEvent) -> bool:
        del event
        raise EscrowProviderUnavailable("TON testnet evidence verification is not configured")
