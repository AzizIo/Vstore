from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.escrow.domain import EscrowChainEventType
from app.escrow.models import EscrowChainEvent, EscrowObserverCheckpoint
from app.escrow.observer import (
    CHECKPOINT_ID,
    _apply_one_event,
    _stored_evidence_hash,
    run_observer_pass,
)
from app.escrow.provider import (
    ChainEventBatch,
    EscrowProviderUnavailable,
    NormalizedChainEvent,
    UnconfiguredTONTestnetEscrowProvider,
)


def make_event(**overrides: object) -> NormalizedChainEvent:
    values: dict[str, Any] = {
        "network": "testnet",
        "transaction_hash": "tx-001",
        "event_index": 0,
        "event_type": EscrowChainEventType.NFT_DEPOSITED,
        "contract_address": "0:" + "a" * 64,
        "deal_id": str(uuid4()),
        "source_address": "0:" + "b" * 64,
        "destination_address": "0:" + "a" * 64,
        "item_address": "0:" + "c" * 64,
        "amount_nanotons": None,
        "masterchain_seqno": 100,
        "finalized": True,
        "evidence_sha256": "1" * 64,
        "cursor": "cursor-next",
    }
    values.update(overrides)
    return NormalizedChainEvent(**values)


class FakeSession:
    def __init__(self, *scalar_results: object) -> None:
        self.scalar_results = list(scalar_results)
        self.added: list[object] = []
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> object:
        self.statements.append(statement)
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    async def get(self, *args: object, **kwargs: object) -> object:
        return None

    def add(self, value: object) -> None:
        self.added.append(value)


@pytest.mark.asyncio
async def test_bad_provider_digest_is_stored_as_safe_hash_and_rejected() -> None:
    event = make_event(evidence_sha256="not-a-sha256")
    session = FakeSession()

    result = await _apply_one_event(session, event, provider_verified=False)

    assert result == "rejected"
    assert len(session.added) == 1
    stored = session.added[0]
    assert isinstance(stored, EscrowChainEvent)
    assert stored.status == "rejected"
    assert stored.evidence_sha256 == _stored_evidence_hash(event)
    assert len(stored.evidence_sha256) == 64


@pytest.mark.asyncio
async def test_same_chain_event_is_an_idempotent_noop() -> None:
    event = make_event()
    existing = EscrowChainEvent(
        id=uuid4(),
        network=event.network,
        transaction_hash=event.transaction_hash,
        event_index=event.event_index,
        event_type=event.event_type.value,
        contract_address=event.contract_address,
        masterchain_seqno=event.masterchain_seqno,
        finalized=True,
        evidence_sha256=event.evidence_sha256,
        payload_json={},
        status="applied",
    )
    session = FakeSession(existing)
    result = await _apply_one_event(session, event, provider_verified=True)

    assert result == "duplicates"
    assert session.added == []
    assert existing.status == "applied"


@pytest.mark.asyncio
async def test_conflicting_digest_for_same_event_goes_to_manual_review() -> None:
    event = make_event(evidence_sha256="2" * 64)
    existing = EscrowChainEvent(
        id=uuid4(),
        network=event.network,
        transaction_hash=event.transaction_hash,
        event_index=event.event_index,
        event_type=event.event_type.value,
        contract_address=event.contract_address,
        masterchain_seqno=event.masterchain_seqno,
        finalized=True,
        evidence_sha256="3" * 64,
        payload_json={},
        status="applied",
    )
    session = FakeSession(existing)
    result = await _apply_one_event(session, event, provider_verified=True)

    assert result == "rejected"
    assert existing.status == "manual_review"
    assert existing.reason_code == "event_evidence_conflict"


class FakeContext:
    def __init__(self, session: FakeEscrowSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeEscrowSession:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeEscrowSession:
    def __init__(self, checkpoint: EscrowObserverCheckpoint) -> None:
        self.checkpoint = checkpoint

    async def __aenter__(self) -> "FakeEscrowSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> FakeContext:
        return FakeContext(self)

    async def scalar(self, statement: object) -> EscrowObserverCheckpoint:
        return self.checkpoint


class OutageProvider(UnconfiguredTONTestnetEscrowProvider):
    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch:
        del cursor, limit
        raise EscrowProviderUnavailable("temporary test outage")


@pytest.mark.asyncio
async def test_provider_outage_preserves_cursor_and_releases_lease() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    checkpoint = EscrowObserverCheckpoint(
        checkpoint_id=CHECKPOINT_ID,
        network="testnet",
        cursor="durable-cursor-before-outage",
        last_masterchain_seqno=99,
        lease_token=None,
        lease_until=None,
        next_scan_at=None,
        last_error_code=None,
    )

    def factory() -> FakeEscrowSession:
        return FakeEscrowSession(checkpoint)

    result = await run_observer_pass(
        factory, OutageProvider(), now=now, limit=5  # type: ignore[arg-type]
    )

    assert result.provider_unavailable
    assert checkpoint.cursor == "durable-cursor-before-outage"
    assert checkpoint.lease_token is None
    assert checkpoint.lease_until is None
    assert checkpoint.last_error_code == "provider_unavailable"
    assert checkpoint.next_scan_at == now.replace(second=15)


def test_observer_checkpoint_table_is_durable_and_testnet_scoped() -> None:
    assert EscrowObserverCheckpoint.__tablename__ == "escrow_observer_checkpoints"
    assert EscrowObserverCheckpoint.__table__.c.cursor is not None
    assert EscrowObserverCheckpoint.__table__.c.lease_token is not None
    assert EscrowObserverCheckpoint.__table__.c.lease_until is not None
