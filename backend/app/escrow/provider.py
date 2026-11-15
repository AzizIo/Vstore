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
    terminal_owner_address: str | None = None
    terminal_owner_proof_sha256: str | None = None
    terminal_owner_masterchain_seqno: int | None = None
    terminal_owner_provider: str | None = None
    # Untrusted discovery locators; never treated as finality proof.
    candidate_workchain: int | None = None
    candidate_shard: int | None = None
    candidate_block_seqno: int | None = None
    # Facts decoded from the proof-verified transaction/message and account state.
    verified_event_type: EscrowChainEventType | None = None
    verified_source_address: str | None = None
    verified_destination_address: str | None = None
    verified_item_address: str | None = None
    verified_collection_address: str | None = None
    verified_amount_nanotons: int | None = None

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
    verified_event_type: EscrowChainEventType | None = None
    verified_query_id: str | None = None
    source_address: str | None = None
    destination_address: str | None = None
    item_address: str | None = None
    collection_address: str | None = None
    amount_nanotons: int | None = None
    observed_contract_state: str | None = None
    attestation_accepted: bool = False
    contract_state_reconciled: bool = False
    getter_snapshot_json: dict[str, object] | None = None
    getter_snapshot_sha256: str | None = None
    getter_snapshot_masterchain_seqno: int | None = None
    getter_snapshot_block_hash: str | None = None
    getter_snapshot_provider: str | None = None

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
            and (
                event.masterchain_block_hash is None
                or event.masterchain_block_hash == self.masterchain_block_hash
            )
            and (
                event.finality_proof_sha256 is None
                or event.finality_proof_sha256 == self.proof_sha256
            )
            and (
                event.finality_provider is None
                or event.finality_provider == self.provider_id
            )
            and bool(self.provider_id.strip())
            and (
                self.verified_event_type is None
                or isinstance(self.verified_event_type, EscrowChainEventType)
            )
            and (
                self.verified_query_id is None
                or (
                    self.verified_query_id.isdecimal()
                    and int(self.verified_query_id) > 0
                    and (
                        event.query_id is None
                        or event.query_id == self.verified_query_id
                    )
                )
            )
            and (
                self.getter_snapshot_json is None
                or (
                    isinstance(self.getter_snapshot_sha256, str)
                    and is_sha256(self.getter_snapshot_sha256)
                    and hashlib.sha256(
                        json.dumps(
                            self.getter_snapshot_json,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode("utf-8")
                    ).hexdigest() == self.getter_snapshot_sha256
                    and self.getter_snapshot_masterchain_seqno == self.masterchain_seqno
                    and self.getter_snapshot_block_hash == self.masterchain_block_hash
                    and self.getter_snapshot_provider == self.provider_id
                    and self.contract_state_reconciled
                )
            )
        )


@dataclass(frozen=True, slots=True)
class TerminalOwnerVerification:
    """Independent testnet proof of the NFT's current owner at a masterchain height."""

    network: str
    item_address: str
    owner_address: str
    masterchain_seqno: int
    proof_sha256: str
    provider_id: str
    verified: bool

    def matches(
        self,
        *,
        item_address: str,
        expected_owner_address: str,
        minimum_masterchain_seqno: int,
    ) -> bool:
        return (
            self.verified
            and self.network == "testnet"
            and self.item_address == item_address
            and self.owner_address == expected_owner_address
            and self.masterchain_seqno >= minimum_masterchain_seqno
            and len(self.proof_sha256) == 64
            and all(char in "0123456789abcdef" for char in self.proof_sha256.lower())
            and bool(self.provider_id.strip())
        )


class TONTestnetEscrowProvider(Protocol):
    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch: ...
    async def verify_event(self, event: NormalizedChainEvent) -> FinalityVerification | None: ...
    async def verify_terminal_owner(
        self, *, item_address: str, expected_owner_address: str, minimum_masterchain_seqno: int
    ) -> TerminalOwnerVerification | None: ...


class UnconfiguredTONTestnetEscrowProvider:
    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch:
        del cursor, limit
        raise EscrowProviderUnavailable("TON escrow testnet provider is not configured")

    async def verify_event(self, event: NormalizedChainEvent) -> FinalityVerification | None:
        del event
        raise EscrowProviderUnavailable("TON testnet evidence verification is not configured")

    async def verify_terminal_owner(
        self, *, item_address: str, expected_owner_address: str,
        minimum_masterchain_seqno: int,
    ) -> TerminalOwnerVerification | None:
        del item_address, expected_owner_address, minimum_masterchain_seqno
        raise EscrowProviderUnavailable("TON testnet current-owner verification is not configured")
