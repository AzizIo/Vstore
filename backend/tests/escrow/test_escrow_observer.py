from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.escrow.domain import EscrowChainEventType, EscrowDealStatus
from app.escrow.models import EscrowChainEvent, EscrowObserverCheckpoint
from app.escrow.observer import (
    CHECKPOINT_ID, _apply_one_event, _payload, _stored_evidence_hash, run_observer_pass,
)
from app.escrow.provider import (
    ChainEventBatch, EscrowProviderUnavailable, NormalizedChainEvent,
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
        account_address=event.account_address, observed_contract_state=event.observed_contract_state,
        contract_state_reconciled=event.contract_state_reconciled,
        event_type=event.event_type.value, contract_address=event.contract_address,
        deal_id=uuid4(), source_address=event.source_address, destination_address=event.destination_address,
        item_address=event.item_address, amount_nanotons=event.amount_nanotons,
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
    event = make_event()
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

    async def verify_event(self, event: NormalizedChainEvent) -> bool:
        return True


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
        next_scan_at=None, last_error_code=None,
    )
    pending = make_event(finalized=False)
    sessions = [FakeEscrowSession(checkpoint), FakeEscrowSession(checkpoint, None)]
    provider = BatchProvider(pending)

    def factory() -> FakeEscrowSession:
        return sessions.pop(0)

    result = await run_observer_pass(factory, provider, now=now, limit=5)  # type: ignore[arg-type]
    assert result.pending == 1
    assert provider.received_cursors == ["cursor-before"]
    assert checkpoint.cursor == "cursor-before"
    assert checkpoint.lease_token is None
    assert checkpoint.lease_until is None
    assert checkpoint.next_scan_at == now + timedelta(seconds=10)


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

    result = await run_observer_pass(factory, OutageProvider(), now=now, limit=5)  # type: ignore[arg-type]
    assert result.provider_unavailable
    assert checkpoint.cursor == "durable-cursor-before-outage"
    assert checkpoint.lease_token is None
    assert checkpoint.lease_until is None
    assert checkpoint.last_error_code == "provider_unavailable"


def test_observer_checkpoint_table_is_durable_and_testnet_scoped() -> None:
    assert EscrowObserverCheckpoint.__tablename__ == "escrow_observer_checkpoints"
    assert EscrowObserverCheckpoint.__table__.c.cursor is not None
    assert EscrowObserverCheckpoint.__table__.c.lease_token is not None
    assert EscrowObserverCheckpoint.__table__.c.lease_until is not None
