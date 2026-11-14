"""TON testnet event normalization boundary.

Non-final or incomplete observations may be replayed and promoted to final. The
provider must preserve the transaction/message/trace/phase/attempt identity tuple
across scans; logical time and deal salt are payload facts that may be enriched.
No live provider is enabled before ABI approval.
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
    masterchain_block_hash: str | None = None
    finality_proof_sha256: str | None = None
    finality_provider: str | None = None

    @property
    def event_key(self) -> str:
        # Stable across pending -> final. Trace, phase and attempt distinguish
        # separate messages; logical time and deal salt may be enriched later.
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


@dataclass(frozen=True, slots=True)
class FinalityVerification:
    """Provider-verified inclusion/finality result bound to one exact trace event.

    Implementations must derive this result from independently verified
    masterchain inclusion/finality evidence, not from an indexer status flag.
    """

    network: str
    transaction_hash: str
    masterchain_seqno: int
    masterchain_block_hash: str
    message_hash: str
    trace_id: str
    proof_sha256: str
    provider_id: str
    finalized: bool
    masterchain_inclusion_verified: bool
    trace_binding_verified: bool

    def matches(self, event: NormalizedChainEvent) -> bool:
        def is_sha256(value: str) -> bool:
            return len(value) == 64 and all(
                char in "0123456789abcdef" for char in value.lower()
            )

        return (
            self.finalized
            and self.masterchain_inclusion_verified
            and self.trace_binding_verified
            and event.finalized
            and self.network == "testnet"
            and event.network == self.network
            and self.transaction_hash == event.transaction_hash
            and self.masterchain_seqno == event.masterchain_seqno
            and self.masterchain_seqno > 0
            and bool(event.message_hash)
            and self.message_hash == event.message_hash
            and bool(event.trace_id)
            and self.trace_id == event.trace_id
            and is_sha256(self.masterchain_block_hash)
            and is_sha256(self.proof_sha256)
            and bool(self.provider_id.strip())
        )


class TONTestnetEscrowProvider(Protocol):
    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch: ...
    async def verify_event(self, event: NormalizedChainEvent) -> FinalityVerification | None: ...


class UnconfiguredTONTestnetEscrowProvider:
    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch:
        del cursor, limit
        raise EscrowProviderUnavailable("TON escrow testnet provider is not configured")

    async def verify_event(self, event: NormalizedChainEvent) -> FinalityVerification | None:
        del event
        raise EscrowProviderUnavailable("TON testnet evidence verification is not configured")
