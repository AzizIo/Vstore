from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.db.models import ListingStatus
from app.escrow.domain import EscrowChainEventType, EscrowDealStatus
from app.escrow.models import (
    EscrowChainEvent,
    EscrowObserverCheckpoint,
)
from app.escrow.observer import (
    CHECKPOINT_ID,
    _apply_one_event,
    _payload,
    _reconcile_terminal_listing,
    _reconcile_wallet_action_finality,
    _sha256_json,
    _stored_evidence_hash,
    _terminal_owner_evidence,
    run_observer_pass,
)
from app.escrow.provider import (
    ChainEventBatch,
    EscrowProviderInvalidEvidence,
    EscrowProviderUnavailable,
    FinalityVerification,
    NormalizedChainEvent,
    TerminalOwnerVerification,
    UnconfiguredTONTestnetEscrowProvider,
)


def make_event(**overrides: object) -> NormalizedChainEvent:
    values: dict[str, Any] = {
        "network": "testnet",
        "transaction_hash": "tx-001",
        "event_index": 0,
        "event_type": EscrowChainEventType.CONTRACT_ACTIVATED,
        "contract_address": "0:" + "a" * 64,
        "deal_id": str(uuid4()),
        "source_address": None,
        "destination_address": None,
        "item_address": None,
        "collection_address": None,
        "amount_nanotons": None,
        "masterchain_seqno": 100,
        "finalized": True,
        "evidence_sha256": "1" * 64,
        "cursor": "cursor-next",
        "message_hash": "message-001",
        "trace_id": "trace-001",
        "logical_time": 500,
        "phase": "transaction",
        "attempt_id": "attempt-001",
        "query_id": "query-001",
        "operation_id": "operation-001",
        "deal_salt": "d" * 64,
        "observed_contract_state": None,
        "attestation_accepted": False,
        "contract_state_reconciled": False,
        "masterchain_block_hash": "a" * 64,
        "finality_proof_sha256": "b" * 64,
        "finality_provider": "fixture-masterchain-verifier",
    }
    values.update(overrides)
    return NormalizedChainEvent(**values)


def stored_row(event: NormalizedChainEvent, *, status: str = "applied") -> EscrowChainEvent:
    return EscrowChainEvent(
        id=uuid4(), network=event.network, event_key=event.event_key,
        transaction_hash=event.transaction_hash, event_index=event.event_index,
        message_hash=event.message_hash, trace_id=event.trace_id, logical_time=event.logical_time,
        phase=event.phase, attempt_id=event.attempt_id, query_id=event.query_id,
        operation_id=event.operation_id, deal_salt=event.deal_salt,
        account_address=event.account_address,
            observed_contract_state=event.observed_contract_state,
        contract_state_reconciled=event.contract_state_reconciled,
        event_type=event.event_type.value, contract_address=event.contract_address,
        deal_id=uuid4(), source_address=event.source_address,
            destination_address=event.destination_address,
        item_address=event.item_address, collection_address=event.collection_address,
        amount_nanotons=event.amount_nanotons,
        masterchain_seqno=event.masterchain_seqno, finalized=event.finalized,
        evidence_sha256=event.evidence_sha256, payload_json=_payload(event),
        status=status, reason_code=None,
    )


class FakeSession:
    def __init__(self, *scalar_results: object) -> None:
        self.scalar_results = list(scalar_results)
        self.added: list[object] = []
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> object:
        self.statements.append(statement)
        return self.scalar_results.pop(0) if self.scalar_results else None

    async def get(self, *args: object, **kwargs: object) -> object:
        return None

    def add(self, value: object) -> None:
        self.added.append(value)


@pytest.mark.asyncio
async def test_bad_provider_digest_is_stored_as_safe_hash_and_rejected() -> None:
    event = make_event(evidence_sha256="not-a-sha256")
    session = FakeSession(None)
    result = await _apply_one_event(session, event, provider_verified=True)
    assert result == "rejected"
    stored = session.added[0]
    assert isinstance(stored, EscrowChainEvent)
    assert stored.status == "rejected"
    assert stored.evidence_sha256 == _stored_evidence_hash(event)
    assert len(stored.evidence_sha256) == 64


@pytest.mark.asyncio
async def test_nonfinal_event_is_pending_then_promoted_once_when_final() -> None:
    deal_id = uuid4()
    pending = make_event(deal_id=str(deal_id), finalized=False)
    first = FakeSession(None)
    assert await _apply_one_event(first, pending, provider_verified=True) == "pending"
    row = first.added[0]
    assert isinstance(row, EscrowChainEvent)
    assert row.status == "pending"
    assert row.reason_code == "awaiting_finality"

    deal = SimpleNamespace(
        id=deal_id, network="testnet", contract_address=pending.contract_address,
        collection_address_snapshot="0:" + "f" * 64,
        deal_salt=pending.deal_salt, item_address="0:" + "b" * 64,
        seller_address_snapshot="0:" + "c" * 64, buyer_address_snapshot="0:" + "e" * 64,
        principal_nanotons=2_000_000_000, status=EscrowDealStatus.INTENT_CREATED.value,
        last_chain_seqno=None, last_chain_logical_time=None,
    )
    finalized = replace(pending, finalized=True, masterchain_seqno=101)
    second = FakeSession(row, deal)
    assert await _apply_one_event(second, finalized, provider_verified=True) == "applied"
    assert row.status == "applied"
    assert row.finalized is True
    assert row.masterchain_seqno == 101
    assert deal.status == EscrowDealStatus.AWAITING_NFT.value


@pytest.mark.asyncio
async def test_raw_nft_transfer_evidence_is_persisted_without_deal_transition() -> None:
    deal_id = uuid4()
    event = make_event(
        deal_id=str(deal_id),
        event_type=EscrowChainEventType.NFT_TRANSFER_CONFIRMED,
    )
    session = FakeSession(None, deal_id)
    assert await _apply_one_event(session, event, provider_verified=True) == "rejected"
    row = session.added[0]
    assert isinstance(row, EscrowChainEvent)
    assert row.status == "rejected"
    assert row.reason_code == "raw_evidence_not_contract_attestation"
    assert row.deal_id == deal_id
    # No deal lookup/update was attempted after persisting raw evidence.
    assert len(session.statements) == 2


@pytest.mark.asyncio
async def test_duplicate_final_event_is_idempotent_after_restart() -> None:
    event = make_event()
    existing = stored_row(event)
    session = FakeSession(existing)
    assert await _apply_one_event(session, event, provider_verified=True) == "duplicates"
    assert session.added == []
    assert existing.status == "applied"


@pytest.mark.asyncio
async def test_conflicting_parameters_for_same_identity_go_to_manual_review() -> None:
    event = make_event(source_address="0:" + "c" * 64)
    existing = stored_row(event)
    conflict = replace(event, source_address="0:" + "f" * 64)
    session = FakeSession(existing)
    assert await _apply_one_event(session, conflict, provider_verified=True) == "rejected"
    assert existing.status == "manual_review"
    assert existing.reason_code == "event_correlation_conflict"


def test_trace_and_attempt_ids_are_part_of_event_correlation_identity() -> None:
    event = make_event()
    assert replace(event, attempt_id="attempt-002").event_key != event.event_key
    assert replace(event, trace_id="trace-002").event_key != event.event_key
    assert replace(event, message_hash="message-002").event_key != event.event_key
    # Late enrichment with logical time / deal salt must not split a pending
    # event from its final copy; those values are compared as immutable facts.
    assert replace(event, logical_time=501).event_key == event.event_key
    assert replace(event, deal_salt="e" * 64).event_key == event.event_key


class FakeContext:
    def __init__(self, session: FakeEscrowSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeEscrowSession:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeEscrowSession:
    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def __aenter__(self) -> FakeEscrowSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> FakeContext:
        return FakeContext(self)

    async def scalar(self, statement: object) -> object:
        return self.results.pop(0) if self.results else None


class BatchProvider(UnconfiguredTONTestnetEscrowProvider):
    def __init__(self, event: NormalizedChainEvent) -> None:
        self.event = event
        self.received_cursors: list[str | None] = []

    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch:
        del limit
        self.received_cursors.append(cursor)
        return ChainEventBatch(events=(self.event,), next_cursor="cursor-after-event")

    async def verify_event(self, event: NormalizedChainEvent) -> FinalityVerification:
        return FinalityVerification(
            network=event.network,
            transaction_hash=event.transaction_hash,
            masterchain_seqno=event.masterchain_seqno,
            masterchain_block_hash="a" * 64,
            message_hash=event.message_hash or "",
            trace_id=event.trace_id or "",
            proof_sha256="b" * 64,
            provider_id="fixture-masterchain-verifier",
            finalized=event.finalized,
            masterchain_inclusion_verified=event.finalized,
            trace_binding_verified=event.finalized,
        )

    async def verify_terminal_owner(
        self, *, item_address: str, expected_owner_address: str,
        minimum_masterchain_seqno: int,
    ) -> TerminalOwnerVerification:
        return TerminalOwnerVerification(
            network="testnet",
            item_address=item_address,
            owner_address=expected_owner_address,
            masterchain_seqno=minimum_masterchain_seqno + 1,
            proof_sha256="c" * 64,
            provider_id="fixture-owner-verifier",
            verified=True,
        )


class OutageProvider(UnconfiguredTONTestnetEscrowProvider):
    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch:
        del cursor, limit
        raise EscrowProviderUnavailable("temporary test outage")


@pytest.mark.asyncio
async def test_nonfinal_event_pins_durable_cursor_for_requery() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    checkpoint = EscrowObserverCheckpoint(
        checkpoint_id=CHECKPOINT_ID, network="testnet", cursor="cursor-before",
        last_masterchain_seqno=99, lease_token=None, lease_until=now - timedelta(seconds=1),
        next_scan_at=None, last_error_code=None, failure_count=4,
    )
    pending = make_event(finalized=False)
    sessions = [FakeEscrowSession(checkpoint), FakeEscrowSession(checkpoint, None)]
    provider = BatchProvider(pending)

    def factory() -> FakeEscrowSession:
        return sessions.pop(0)

    result = await run_observer_pass(
        factory, provider, now=now, limit=5
    )  # type: ignore[arg-type]
    assert result.pending == 1
    assert provider.received_cursors == ["cursor-before"]
    assert checkpoint.cursor == "cursor-before"
    assert checkpoint.lease_token is None
    assert checkpoint.lease_until is None
    assert checkpoint.next_scan_at == now + timedelta(seconds=10)
    assert checkpoint.failure_count == 0


@pytest.mark.asyncio
async def test_provider_outage_preserves_cursor_and_releases_lease() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    checkpoint = EscrowObserverCheckpoint(
        checkpoint_id=CHECKPOINT_ID, network="testnet", cursor="durable-cursor-before-outage",
        last_masterchain_seqno=99, lease_token=None, lease_until=None,
        next_scan_at=None, last_error_code=None,
    )
    sessions = [FakeEscrowSession(checkpoint), FakeEscrowSession(checkpoint)]

    def factory() -> FakeEscrowSession:
        return sessions.pop(0)

    result = await run_observer_pass(
        factory, OutageProvider(), now=now, limit=5
    )  # type: ignore[arg-type]
    assert result.provider_unavailable
    assert checkpoint.cursor == "durable-cursor-before-outage"
    assert checkpoint.lease_token is None
    assert checkpoint.lease_until is None
    assert checkpoint.last_error_code == "provider_unavailable"
    assert checkpoint.failure_count == 1
    assert checkpoint.next_scan_at == now + timedelta(seconds=5)


def test_observer_checkpoint_table_is_durable_and_testnet_scoped() -> None:
    assert EscrowObserverCheckpoint.__tablename__ == "escrow_observer_checkpoints"
    assert EscrowObserverCheckpoint.__table__.c.cursor is not None
    assert EscrowObserverCheckpoint.__table__.c.lease_token is not None
    assert EscrowObserverCheckpoint.__table__.c.lease_until is not None


@pytest.mark.asyncio
async def test_expired_observer_lease_requeries_the_durable_cursor() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    checkpoint = EscrowObserverCheckpoint(
        checkpoint_id=CHECKPOINT_ID,
        network="testnet",
        cursor="cursor-before-expired-lease",
        last_masterchain_seqno=99,
        lease_token=uuid4(),
        lease_until=now - timedelta(seconds=1),
        next_scan_at=None,
        last_error_code=None,
    )

    class RecordingOutageProvider(OutageProvider):
        def __init__(self) -> None:
            self.received_cursor: str | None = None

        async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch:
            self.received_cursor = cursor
            return await super().scan_events(cursor=cursor, limit=limit)

    sessions = [
        FakeEscrowSession(checkpoint),
        FakeEscrowSession(checkpoint),
        FakeEscrowSession(checkpoint),
    ]

    def factory() -> FakeEscrowSession:
        return sessions.pop(0)

    provider = RecordingOutageProvider()
    result = await run_observer_pass(
        factory, provider, now=now, limit=5
    )  # type: ignore[arg-type]

    assert result.provider_unavailable
    assert provider.received_cursor == "cursor-before-expired-lease"
    assert checkpoint.cursor == "cursor-before-expired-lease"
    assert checkpoint.lease_token is None
    assert checkpoint.lease_until is None


@pytest.mark.asyncio
async def test_unknown_deal_event_is_pending_without_invalid_foreign_key() -> None:
    missing_deal_id = uuid4()
    event = make_event(deal_id=str(missing_deal_id))
    session = FakeSession(None, None)

    assert await _apply_one_event(session, event, provider_verified=True) == "unmatched"
    row = session.added[0]
    assert isinstance(row, EscrowChainEvent)
    assert row.status == "pending"
    assert row.reason_code == "deal_not_found"
    assert row.deal_id is None
    assert row.payload_json["deal_id"] == str(missing_deal_id)


@pytest.mark.asyncio
async def test_database_disconnect_during_batch_keeps_cursor_for_replay() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    checkpoint = EscrowObserverCheckpoint(
        checkpoint_id=CHECKPOINT_ID,
        network="testnet",
        cursor="cursor-before-db-disconnect",
        last_masterchain_seqno=99,
        lease_token=None,
        lease_until=None,
        next_scan_at=None,
        last_error_code=None,
    )

    class CommitFailingContext(FakeContext):
        async def __aenter__(self) -> FakeEscrowSession:
            self.before = (
                checkpoint.cursor,
                checkpoint.lease_token,
                checkpoint.lease_until,
                checkpoint.next_scan_at,
                checkpoint.last_error_code,
            )
            return await super().__aenter__()

        async def __aexit__(self, *args: object) -> None:
            (
                checkpoint.cursor,
                checkpoint.lease_token,
                checkpoint.lease_until,
                checkpoint.next_scan_at,
                checkpoint.last_error_code,
            ) = self.before
            raise RuntimeError("simulated database disconnect during commit")

    class CommitFailingSession(FakeEscrowSession):
        def begin(self) -> CommitFailingContext:
            return CommitFailingContext(self)

    sessions = [
        FakeEscrowSession(checkpoint),
        CommitFailingSession(checkpoint, None, None),
        FakeEscrowSession(checkpoint),
    ]

    def factory() -> FakeEscrowSession:
        return sessions.pop(0)

    provider = BatchProvider(
        make_event(event_type=EscrowChainEventType.NFT_TRANSFER_CONFIRMED)
    )
    result = await run_observer_pass(
        factory, provider, now=now, limit=5
    )  # type: ignore[arg-type]

    assert result.persistence_failed
    assert checkpoint.cursor == "cursor-before-db-disconnect"
    assert checkpoint.lease_token is None
    assert checkpoint.lease_until is None
    assert checkpoint.last_error_code == "batch_persistence_failed"


@pytest.mark.asyncio
async def test_unreconciled_contract_address_pins_event_for_requery() -> None:
    deal_id = uuid4()
    deal = SimpleNamespace(
        id=deal_id, network="testnet", contract_address=None,
        collection_address_snapshot="0:" + "f" * 64,
        item_address="0:" + "b" * 64,
        seller_address_snapshot="0:" + "c" * 64,
        buyer_address_snapshot="0:" + "d" * 64,
        principal_nanotons=2_500_000_000, deal_salt="d" * 64,
        status="intent_created", last_chain_seqno=None, last_chain_logical_time=None,
    )
    event = make_event(
        deal_id=str(deal_id), event_type=EscrowChainEventType.CONTRACT_ACTIVATED,
        deal_salt="d" * 64,
    )
    session = FakeSession(None, deal)

    assert await _apply_one_event(session, event, provider_verified=True) == "pending"
    assert session.added[0].reason_code == "contract_address_not_reconciled"


@pytest.mark.asyncio
async def test_stale_logical_time_pins_event_instead_of_advancing_cursor() -> None:
    deal_id = uuid4()
    deal = SimpleNamespace(
        id=deal_id, network="testnet", contract_address="0:" + "a" * 64,
        collection_address_snapshot="0:" + "f" * 64,
        item_address="0:" + "b" * 64,
        seller_address_snapshot="0:" + "c" * 64,
        buyer_address_snapshot="0:" + "d" * 64,
        principal_nanotons=2_500_000_000, deal_salt="d" * 64,
        status="intent_created", last_chain_seqno=100, last_chain_logical_time=600,
    )
    event = make_event(
        deal_id=str(deal_id), event_type=EscrowChainEventType.CONTRACT_ACTIVATED,
        deal_salt="d" * 64, masterchain_seqno=100, logical_time=599,
    )
    session = FakeSession(None, deal)

    assert await _apply_one_event(session, event, provider_verified=True) == "pending"
    assert session.added[0].reason_code == "stale_chain_event"


@pytest.mark.asyncio
async def test_replay_cannot_remove_previously_accepted_attestation() -> None:
    event = make_event(
        event_type=EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED,
        attestation_accepted=False,
        contract_state_reconciled=False,
    )
    existing = stored_row(event, status="pending")
    existing.payload_json["attestation_accepted"] = True
    existing.payload_json["contract_state_reconciled"] = True
    existing.payload_json["finalized"] = True
    existing.payload_json["masterchain_seqno"] = 99
    existing.finalized = True
    event = replace(event, finalized=False)
    session = FakeSession(existing)

    assert await _apply_one_event(session, event, provider_verified=True) == "rejected"
    assert existing.status == "manual_review"
    assert existing.reason_code == "event_correlation_conflict"


def test_event_identity_survives_pending_metadata_enrichment() -> None:
    pending = make_event(
        logical_time=None,
        deal_salt=None,
        observed_contract_state=None,
        account_address=None,
    )
    finalized = replace(
        pending,
        logical_time=987654,
        deal_salt="f" * 64,
        observed_contract_state="awaiting_nft",
        account_address="0:" + "a" * 64,
    )

    assert pending.event_key == finalized.event_key
    assert len(pending.event_key) == 64


@pytest.mark.asyncio
async def test_replay_with_conflicting_final_masterchain_seqno_requires_review() -> None:
    event = make_event()
    existing = stored_row(event, status="applied")
    existing.payload_json["finalized"] = True
    existing.payload_json["masterchain_seqno"] = 100
    session = FakeSession(existing)
    replay = replace(event, masterchain_seqno=101)

    assert await _apply_one_event(session, replay, provider_verified=True) == "rejected"
    assert existing.status == "manual_review"
    assert existing.reason_code == "event_correlation_conflict"


@pytest.mark.asyncio
async def test_boolean_indexer_finality_claim_is_not_accepted() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    checkpoint = EscrowObserverCheckpoint(
        checkpoint_id=CHECKPOINT_ID, network="testnet", cursor="cursor-before",
        last_masterchain_seqno=99, lease_token=None, lease_until=now - timedelta(seconds=1),
        next_scan_at=None, last_error_code=None,
    )

    class BooleanOnlyProvider(BatchProvider):
        async def verify_event(self, event: NormalizedChainEvent) -> bool:
            return True

    acquire_session = FakeEscrowSession(checkpoint)
    persist_session = FakeEscrowSession(checkpoint, None)
    sessions = [acquire_session, persist_session]
    provider = BooleanOnlyProvider(make_event())

    def factory() -> FakeEscrowSession:
        return sessions.pop(0)

    result = await run_observer_pass(factory, provider, now=now, limit=5)  # type: ignore[arg-type]
    assert result.rejected == 1
    assert result.pending == 0
    assert checkpoint.cursor == "cursor-after-event"
    stored = persist_session.added
    assert len(stored) == 1
    assert isinstance(stored[0], EscrowChainEvent)
    assert stored[0].status == "rejected"
    assert stored[0].reason_code == "invalid_verification_result"


@pytest.mark.asyncio
async def test_mismatched_finality_proof_is_not_accepted() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    checkpoint = EscrowObserverCheckpoint(
        checkpoint_id=CHECKPOINT_ID, network="testnet", cursor="cursor-before",
        last_masterchain_seqno=99, lease_token=None, lease_until=now - timedelta(seconds=1),
        next_scan_at=None, last_error_code=None,
    )

    class MismatchedProofProvider(BatchProvider):
        async def verify_event(self, event: NormalizedChainEvent) -> FinalityVerification:
            return FinalityVerification(
                network=event.network,
                transaction_hash="different-transaction",
                masterchain_seqno=event.masterchain_seqno,
                masterchain_block_hash="a" * 64,
                message_hash=event.message_hash or "",
                trace_id=event.trace_id or "",
                proof_sha256="b" * 64,
                provider_id="fixture-masterchain-verifier",
                finalized=True,
                masterchain_inclusion_verified=True,
                trace_binding_verified=True,
            )

    acquire_session = FakeEscrowSession(checkpoint)
    persist_session = FakeEscrowSession(checkpoint, None)
    sessions = [acquire_session, persist_session]
    provider = MismatchedProofProvider(make_event())

    def factory() -> FakeEscrowSession:
        return sessions.pop(0)

    result = await run_observer_pass(factory, provider, now=now, limit=5)  # type: ignore[arg-type]
    assert result.rejected == 1
    assert result.pending == 0
    assert checkpoint.cursor == "cursor-after-event"
    stored = persist_session.added
    assert len(stored) == 1
    assert isinstance(stored[0], EscrowChainEvent)
    assert stored[0].status == "rejected"
    assert stored[0].reason_code == "cryptographic_proof_mismatch"


@pytest.mark.asyncio
async def test_invalid_candidate_does_not_block_checkpoint() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    checkpoint = EscrowObserverCheckpoint(
        checkpoint_id=CHECKPOINT_ID,
        network="testnet",
        cursor="cursor-before",
        last_masterchain_seqno=99,
        lease_token=None,
        lease_until=now - timedelta(seconds=1),
        next_scan_at=None,
        last_error_code=None,
    )

    class InvalidEvidenceProvider(BatchProvider):
        async def verify_event(self, event: NormalizedChainEvent) -> FinalityVerification:
            del event
            raise EscrowProviderInvalidEvidence("fixture proof does not bind to candidate")

    acquire_session = FakeEscrowSession(checkpoint)
    persist_session = FakeEscrowSession(checkpoint, None)
    sessions = [acquire_session, persist_session]
    provider = InvalidEvidenceProvider(make_event())

    def factory() -> FakeEscrowSession:
        return sessions.pop(0)

    result = await run_observer_pass(factory, provider, now=now, limit=5)  # type: ignore[arg-type]
    assert result.rejected == 1
    assert result.pending == 0
    assert result.provider_unavailable is False
    assert checkpoint.cursor == "cursor-after-event"
    assert checkpoint.failure_count == 0
    stored = persist_session.added
    assert len(stored) == 1
    assert isinstance(stored[0], EscrowChainEvent)
    assert stored[0].status == "rejected"
    assert stored[0].reason_code == "cryptographic_proof_invalid"


@pytest.mark.asyncio
async def test_conflicting_event_finality_metadata_is_not_accepted() -> None:
    event = make_event(masterchain_block_hash="c" * 64)

    proof = FinalityVerification(
        network=event.network,
        transaction_hash=event.transaction_hash,
        masterchain_seqno=event.masterchain_seqno,
        masterchain_block_hash="a" * 64,
        message_hash=event.message_hash or "",
        trace_id=event.trace_id or "",
        proof_sha256="b" * 64,
        provider_id="fixture-masterchain-verifier",
        finalized=True,
        masterchain_inclusion_verified=True,
        trace_binding_verified=True,
    )

    assert proof.matches(event) is False


@pytest.mark.asyncio
async def test_finalized_event_without_finality_proof_remains_pending() -> None:
    event = make_event(finality_proof_sha256=None)
    session = FakeSession(None)
    result = await _apply_one_event(session, event, provider_verified=True)
    assert result == "pending"
    stored = session.added[0]
    assert isinstance(stored, EscrowChainEvent)
    assert stored.status == "pending"
    assert stored.reason_code == "finality_proof_missing"


@pytest.mark.asyncio
async def test_terminal_owner_provider_is_requeried_after_deal_is_already_terminal() -> None:
    deal_id = uuid4()
    deal = SimpleNamespace(
        id=deal_id,
        status=EscrowDealStatus.SETTLED.value,
        item_address="nft-item",
        buyer_address_snapshot="buyer-wallet",
        seller_address_snapshot="seller-wallet",
    )
    event = make_event(
        deal_id=str(deal_id),
        event_type=EscrowChainEventType.SELLER_PAYOUT_RECONCILED,
        item_address="nft-item",
        observed_contract_state=EscrowDealStatus.SETTLED.value,
        contract_state_reconciled=True,
        masterchain_seqno=200,
    )
    session = FakeEscrowSession(deal)
    calls: list[tuple[str, str, int]] = []

    class OwnerProvider(BatchProvider):
        async def verify_terminal_owner(
            self,
            *,
            item_address: str,
            expected_owner_address: str,
            minimum_masterchain_seqno: int,
        ) -> TerminalOwnerVerification:
            calls.append((item_address, expected_owner_address, minimum_masterchain_seqno))
            return TerminalOwnerVerification(
                network="testnet",
                item_address=item_address,
                owner_address=expected_owner_address,
                masterchain_seqno=minimum_masterchain_seqno + 1,
                proof_sha256="c" * 64,
                provider_id="fixture-owner-verifier",
                verified=True,
            )

    result = await _terminal_owner_evidence(
        lambda: session, OwnerProvider(event), event
    )  # type: ignore[arg-type]

    assert calls == [("nft-item", "buyer-wallet", 200)]
    assert result.terminal_owner_address == "buyer-wallet"
    assert result.terminal_owner_masterchain_seqno == 201


@pytest.mark.asyncio
async def test_terminal_event_retries_owner_reconciliation_after_restart() -> None:
    buyer_id, seller_id, asset_id, listing_id = uuid4(), uuid4(), uuid4(), uuid4()
    deal_id = uuid4()
    contract_address = "0:" + "a" * 64
    event = make_event(
        event_type=EscrowChainEventType.SELLER_PAYOUT_RECONCILED,
        contract_address=contract_address,
        deal_id=str(deal_id),
        source_address=contract_address,
        destination_address="seller-wallet",
        amount_nanotons=2_500_000_000,
        item_address="nft-item",
        collection_address="nft-collection",
        observed_contract_state=EscrowDealStatus.SETTLED.value,
        contract_state_reconciled=True,
        terminal_owner_address="buyer-wallet",
        terminal_owner_proof_sha256="c" * 64,
        terminal_owner_masterchain_seqno=101,
        terminal_owner_provider="fixture-owner-verifier",
    )
    existing = stored_row(event, status="applied")
    existing.reason_code = "terminal_listing_owner_unverified"
    existing.deal_id = deal_id
    deal = SimpleNamespace(
        id=deal_id,
        network="testnet",
        contract_address=contract_address,
        collection_address_snapshot="nft-collection",
        item_address="nft-item",
        seller_address_snapshot="seller-wallet",
        buyer_address_snapshot="buyer-wallet",
        principal_nanotons=2_500_000_000,
        deal_salt="d" * 64,
        status=EscrowDealStatus.SETTLED.value,
        last_chain_seqno=100,
        last_chain_logical_time=499,
        listing_intent_id=uuid4(),
        buyer_id=buyer_id,
        seller_id=seller_id,
    )
    intent = SimpleNamespace(
        id=deal.listing_intent_id,
        marketplace_listing_id=listing_id,
        asset_id=asset_id,
        item_address="nft-item",
        status="manual_review",
    )
    listing = SimpleNamespace(id=listing_id, status=ListingStatus.RESERVED)
    asset = SimpleNamespace(id=asset_id, item_address="nft-item", owner_id=seller_id)
    session = FakeSession(existing, deal, intent, listing, intent, asset)

    result = await _apply_one_event(session, event, provider_verified=True)

    assert result == "applied"
    assert deal.status == EscrowDealStatus.SETTLED.value
    assert listing.status is ListingStatus.SOLD
    assert intent.status == "cancelled"
    assert asset.owner_id == buyer_id
    assert existing.reason_code is None


@pytest.mark.asyncio
async def test_terminal_listing_is_sold_only_after_buyer_owner_proof() -> None:
    buyer_id, seller_id, asset_id, listing_id = uuid4(), uuid4(), uuid4(), uuid4()
    intent = SimpleNamespace(
        id=uuid4(), marketplace_listing_id=listing_id, asset_id=asset_id,
        item_address="nft-item", status="reserved",
    )
    listing = SimpleNamespace(id=listing_id, status=ListingStatus.RESERVED)
    asset = SimpleNamespace(id=asset_id, item_address="nft-item", owner_id=seller_id)
    deal = SimpleNamespace(
        listing_intent_id=intent.id, buyer_address_snapshot="buyer-wallet",
        seller_address_snapshot="seller-wallet", item_address="nft-item",
        buyer_id=buyer_id, seller_id=seller_id,
    )
    event = make_event(
        item_address="nft-item",
        terminal_owner_address="buyer-wallet",
        terminal_owner_proof_sha256="c" * 64,
        terminal_owner_masterchain_seqno=101,
        terminal_owner_provider="fixture-owner-verifier",
    )
    session = FakeEscrowSession(intent, listing, intent, asset)

    reconciled = await _reconcile_terminal_listing(
        session, deal, EscrowDealStatus.SETTLED, event
    )

    assert reconciled is True
    assert listing.status is ListingStatus.SOLD
    assert intent.status == "cancelled"
    assert asset.owner_id == buyer_id


@pytest.mark.asyncio
async def test_terminal_listing_stays_reserved_without_current_owner_proof() -> None:
    buyer_id, seller_id, asset_id, listing_id = uuid4(), uuid4(), uuid4(), uuid4()
    intent = SimpleNamespace(
        id=uuid4(), marketplace_listing_id=listing_id, asset_id=asset_id,
        item_address="nft-item", status="reserved",
    )
    listing = SimpleNamespace(id=listing_id, status=ListingStatus.RESERVED)
    asset = SimpleNamespace(id=asset_id, item_address="nft-item", owner_id=seller_id)
    deal = SimpleNamespace(
        listing_intent_id=intent.id, buyer_address_snapshot="buyer-wallet",
        seller_address_snapshot="seller-wallet", item_address="nft-item",
        buyer_id=buyer_id, seller_id=seller_id,
    )
    event = make_event(item_address="nft-item")
    session = FakeEscrowSession(intent, listing, intent, asset)

    reconciled = await _reconcile_terminal_listing(
        session, deal, EscrowDealStatus.SETTLED, event
    )

    assert reconciled is False
    assert listing.status is ListingStatus.RESERVED
    assert intent.status == "manual_review"
    assert asset.owner_id == seller_id

class _ActionScalars:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class _ActionFinalitySession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    async def __aenter__(self) -> _ActionFinalitySession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _ActionFinalitySession:
        return self

    async def scalars(self, _query: object) -> _ActionScalars:
        return _ActionScalars(self.rows)


@pytest.mark.asyncio
async def test_proof_verified_query_finalizes_only_matching_durable_action() -> None:
    deal_id = uuid4()
    action = SimpleNamespace(
        id=uuid4(),
        deal_id=deal_id,
        action_type="fund_deal",
        network="testnet",
        query_id="77",
        status="ambiguous",
        unsigned_payload_json={"validUntil": 1, "messages": [{"address": "0:" + "a" * 64}]},
        unsigned_payload_sha256="1" * 64,
        unsigned_bocs_json={"format": "tonconnect-message-bocs-v1", "messages": [{}]},
        unsigned_boc_sha256="2" * 64,
        unsigned_boc_ref="db://escrow_wallet_actions/action/unsigned_bocs_json",
        finalized_transaction_hash=None,
        finality_masterchain_seqno=None,
        finality_masterchain_block_hash=None,
        finality_proof_sha256=None,
        finality_provider=None,
        last_error_code="awaiting_independent_chain_reconciliation",
        next_retry_at=datetime.now(UTC),
        lease_token=uuid4(),
        lease_until=datetime.now(UTC) + timedelta(seconds=5),
    )
    event = make_event(
        deal_id=str(deal_id),
        transaction_hash="a" * 64,
        event_type=EscrowChainEventType.BUYER_PAYMENT_ACCEPTED,
        query_id="77",
        masterchain_block_hash="b" * 64,
        finality_proof_sha256="c" * 64,
        finality_provider="pytoniq-trust0-testnet-v1",
    )
    proof = FinalityVerification(
        network="testnet",
        transaction_hash=event.transaction_hash,
        masterchain_seqno=event.masterchain_seqno,
        masterchain_block_hash="b" * 64,
        message_hash=event.message_hash or "",
        trace_id=event.trace_id or "",
        proof_sha256="c" * 64,
        provider_id="pytoniq-trust0-testnet-v1",
        finalized=True,
        masterchain_inclusion_verified=True,
        trace_binding_verified=True,
        verified_event_type=EscrowChainEventType.BUYER_PAYMENT_ACCEPTED,
        verified_query_id="77",
        observed_contract_state=EscrowDealStatus.FUNDED_REVIEW.value,
        contract_state_reconciled=True,
        getter_snapshot_json={"contract_state": 3, "observed_chain_time_unix": 1},
        getter_snapshot_sha256=_sha256_json(
            {"contract_state": 3, "observed_chain_time_unix": 1}
        ),
        getter_snapshot_masterchain_seqno=event.masterchain_seqno,
        getter_snapshot_block_hash="b" * 64,
        getter_snapshot_provider="pytoniq-trust0-testnet-v1",
    )

    await _reconcile_wallet_action_finality(
        lambda: _ActionFinalitySession([action]),  # type: ignore[arg-type]
        event,
        proof,
    )

    assert action.status == "finalized"
    assert action.finalized_transaction_hash == event.transaction_hash
    assert action.finality_masterchain_seqno == proof.masterchain_seqno
    assert action.finality_masterchain_block_hash == proof.masterchain_block_hash
    assert action.finality_proof_sha256 == proof.proof_sha256
    assert action.finality_provider == proof.provider_id
    assert action.last_error_code is None
    assert action.next_retry_at is None
    assert action.lease_token is None
    assert action.lease_until is None


@pytest.mark.asyncio
async def test_query_id_mismatch_never_finalizes_an_action() -> None:
    deal_id = uuid4()
    action = SimpleNamespace(
        id=uuid4(),
        deal_id=deal_id,
        action_type="fund_deal",
        network="testnet",
        query_id="77",
        status="prepared",
        unsigned_payload_json={"messages": [{}]},
        unsigned_payload_sha256="1" * 64,
        unsigned_bocs_json={"messages": [{}]},
        unsigned_boc_sha256="2" * 64,
        unsigned_boc_ref="db://escrow_wallet_actions/action/unsigned_bocs_json",
        finalized_transaction_hash=None,
        finality_masterchain_seqno=None,
        finality_masterchain_block_hash=None,
        finality_proof_sha256=None,
        finality_provider=None,
        last_error_code=None,
        next_retry_at=None,
        lease_token=None,
        lease_until=None,
    )
    event = make_event(
        deal_id=str(deal_id),
        transaction_hash="a" * 64,
        event_type=EscrowChainEventType.BUYER_PAYMENT_ACCEPTED,
        query_id="77",
    )
    proof = FinalityVerification(
        network="testnet",
        transaction_hash=event.transaction_hash,
        masterchain_seqno=event.masterchain_seqno,
        masterchain_block_hash="b" * 64,
        message_hash=event.message_hash or "",
        trace_id=event.trace_id or "",
        proof_sha256="c" * 64,
        provider_id="pytoniq-trust0-testnet-v1",
        finalized=True,
        masterchain_inclusion_verified=True,
        trace_binding_verified=True,
        verified_event_type=EscrowChainEventType.BUYER_PAYMENT_ACCEPTED,
        verified_query_id="78",
    )

    await _reconcile_wallet_action_finality(
        lambda: _ActionFinalitySession([action]),  # type: ignore[arg-type]
        event,
        proof,
    )

    assert action.status == "prepared"
    assert action.finalized_transaction_hash is None




@pytest.mark.asyncio
async def test_unmatched_proof_verified_bounce_is_audited_without_mutating_deal_state() -> None:
    event = make_event(
        event_type=EscrowChainEventType.OUTBOUND_BOUNCE_UNMATCHED,
        phase="bounce",
        attempt_id=None,
        query_id=None,
        bounce_match_reason="outbound_action_descriptor_not_found",
    )
    deal_id = uuid4()
    event = replace(event, deal_id=str(deal_id))
    deal = SimpleNamespace(
        id=deal_id,
        network="testnet",
        contract_address=event.contract_address,
        deal_salt=event.deal_salt,
        status=EscrowDealStatus.AWAITING_NFT.value,
        last_chain_seqno=None,
        last_chain_logical_time=None,
    )
    session = FakeSession(None, deal)

    result = await _apply_one_event(session, event, provider_verified=True)

    assert result == "rejected"
    assert deal.status == EscrowDealStatus.AWAITING_NFT.value
    row = session.added[0]
    assert isinstance(row, EscrowChainEvent)
    assert row.status == "manual_review"
    assert row.reason_code == "outbound_action_descriptor_not_found"
    assert row.deal_id == deal_id



@pytest.mark.asyncio
async def test_pending_bounce_candidate_can_be_proof_reclassified_as_unmatched() -> None:
    deal_id = uuid4()
    candidate = make_event(
        deal_id=str(deal_id),
        event_type=EscrowChainEventType.OUTBOUND_ACTION_BOUNCED,
        phase="bounce",
        attempt_id=None,
        query_id=None,
        operation_id="0xfffffffe",
        source_address=None,
        destination_address=None,
        amount_nanotons=None,
    )
    existing = stored_row(candidate, status="pending")
    existing.deal_id = deal_id
    unmatched = replace(
        candidate,
        event_type=EscrowChainEventType.OUTBOUND_BOUNCE_UNMATCHED,
        source_address="0:" + "b" * 64,
        destination_address=candidate.contract_address,
        observed_contract_state=EscrowDealStatus.AWAITING_NFT.value,
        contract_state_reconciled=True,
        bounce_match_reason="outbound_action_descriptor_not_found",
    )
    deal = SimpleNamespace(
        id=deal_id,
        network="testnet",
        contract_address=candidate.contract_address,
        deal_salt=candidate.deal_salt,
        status=EscrowDealStatus.AWAITING_NFT.value,
        last_chain_seqno=None,
        last_chain_logical_time=None,
    )
    session = FakeSession(existing, deal)

    result = await _apply_one_event(session, unmatched, provider_verified=True)

    assert result == "rejected"
    assert existing.event_type == EscrowChainEventType.OUTBOUND_BOUNCE_UNMATCHED.value
    assert existing.status == "manual_review"
    assert existing.reason_code == "outbound_action_descriptor_not_found"
    assert deal.status == EscrowDealStatus.AWAITING_NFT.value
