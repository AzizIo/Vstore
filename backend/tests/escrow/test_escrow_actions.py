from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.escrow.models import EscrowWalletActionRecord
from app.escrow.service import (
    EscrowActionConflict,
    canonical_request_sha256,
    claim_next_action,
    record_submission_reference,
    release_action_lease,
)


def test_wallet_action_schema_has_idempotency_and_replay_constraints() -> None:
    table = EscrowWalletActionRecord.__table__
    unique_sets = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("actor_id", "action_type", "idempotency_key") in unique_sets
    assert "request_sha256" in table.c
    assert "lease_token" in table.c
    assert "lease_until" in table.c
    assert "unsigned_boc_ref" in table.c
    assert "submission_reference_sha256" in table.c
    assert any(index.name == "uq_escrow_action_submission_reference" for index in table.indexes)


def test_request_hash_is_canonical_and_payload_sensitive() -> None:
    first = canonical_request_sha256({"deal_id": "abc", "amount": "12", "actor": "x"})
    reordered = canonical_request_sha256({"actor": "x", "amount": "12", "deal_id": "abc"})
    changed = canonical_request_sha256({"actor": "x", "amount": "13", "deal_id": "abc"})
    assert first == reordered
    assert first != changed
    assert len(first) == 64


def test_wallet_reference_is_untrusted_and_cannot_replace_existing_hint() -> None:
    action = EscrowWalletActionRecord(
        id=uuid4(), actor_id=uuid4(), deal_id=uuid4(), action_type="fund_deal",
        network="testnet", idempotency_key="action-key-1", request_sha256="a" * 64,
        status="prepared", attempt_count=0, unsigned_boc_sha256="b" * 64,
        unsigned_boc_ref="boc://testnet/sha256/" + "b" * 64,
    )
    record_submission_reference(action, reference="0:" + "c" * 64)
    assert action.status == "ambiguous"
    assert action.last_error_code == "awaiting_independent_chain_reconciliation"
    assert action.submission_reference is not None
    assert action.submission_reference_sha256 == hashlib.sha256(
        ("0:" + "c" * 64).encode("utf-8")
    ).hexdigest()
    with pytest.raises(EscrowActionConflict, match="submission_reference_conflict"):
        record_submission_reference(action, reference="0:" + "d" * 64)
    assert action.status == "manual_review"


def test_wallet_reference_requires_prepared_unsigned_payload() -> None:
    action = EscrowWalletActionRecord(
        id=uuid4(), actor_id=uuid4(), deal_id=uuid4(), action_type="fund_deal",
        network="testnet", idempotency_key="action-key-1", request_sha256="a" * 64,
        status="blocked_abi", attempt_count=0,
    )
    with pytest.raises(EscrowActionConflict, match="action_not_prepared"):
        record_submission_reference(action, reference="client-supplied-hash")


class FakeActionSession:
    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.added: list[object] = []
        self.flushed = 0
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> object:
        self.statements.append(statement)
        return self.results.pop(0) if self.results else None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed += 1


@pytest.mark.asyncio
async def test_create_or_replay_action_persists_new_intent_before_side_effect() -> None:
    from app.escrow.service import create_or_replay_action

    session = FakeActionSession()
    actor_id, deal_id = uuid4(), uuid4()
    digest = canonical_request_sha256({"actor_id": str(actor_id), "deal_id": str(deal_id)})
    action, created = await create_or_replay_action(
        session, actor_id=actor_id, deal_id=deal_id, action_type="fund_deal",
        idempotency_key="action-key-1", request_sha256=digest,
    )
    assert created is True
    assert action.status == "pending"
    assert session.added == [action]
    assert session.flushed == 1


@pytest.mark.asyncio
async def test_create_or_replay_action_reuses_exact_identity_and_rejects_payload_change() -> None:
    from app.escrow.service import create_or_replay_action

    actor_id, deal_id = uuid4(), uuid4()
    digest = canonical_request_sha256({"deal_id": str(deal_id)})
    existing = EscrowWalletActionRecord(
        id=uuid4(), actor_id=actor_id, deal_id=deal_id, action_type="fund_deal",
        network="testnet", idempotency_key="action-key-1", request_sha256=digest,
        status="blocked_abi", attempt_count=0,
    )
    session = FakeActionSession(existing)
    replay, created = await create_or_replay_action(
        session, actor_id=actor_id, deal_id=deal_id, action_type="fund_deal",
        idempotency_key="action-key-1", request_sha256=digest,
    )
    assert replay is existing
    assert created is False
    assert session.added == []

    conflict_session = FakeActionSession(existing)
    with pytest.raises(EscrowActionConflict, match="idempotency_payload_conflict"):
        await create_or_replay_action(
            conflict_session, actor_id=actor_id, deal_id=deal_id, action_type="fund_deal",
            idempotency_key="action-key-1",
            request_sha256=canonical_request_sha256({"deal_id": "different"}),
        )



@pytest.mark.asyncio
async def test_action_lease_uses_skip_locked_and_fences_stale_worker() -> None:
    now = datetime(2026, 11, 15, tzinfo=UTC)
    action = EscrowWalletActionRecord(
        id=uuid4(), actor_id=uuid4(), deal_id=uuid4(), action_type="fund_deal",
        network="testnet", idempotency_key="action-key-1", request_sha256="a" * 64,
        status="prepared", attempt_count=0, created_at=now, updated_at=now,
    )
    session = FakeActionSession(action)
    claimed = await claim_next_action(session, now=now, lease_seconds=60)
    assert claimed is action
    assert action.lease_token is not None
    assert action.lease_until == now + timedelta(seconds=60)
    compiled_query = str(
        session.statements[0].compile(dialect=postgresql.dialect())
    ).upper()
    assert "SKIP LOCKED" in compiled_query

    stale = await release_action_lease(
        FakeActionSession(action), action_id=action.id, lease_token=uuid4(),
        now=now, retry_after_seconds=5, error_code="provider_timeout",
    )
    assert stale is False
    assert action.lease_token is not None

    released = await release_action_lease(
        FakeActionSession(action), action_id=action.id, lease_token=action.lease_token,
        now=now, retry_after_seconds=5, error_code="HTTP 500", ambiguous=True,
    )
    assert released is True
    assert action.lease_token is None
    assert action.lease_until is None
    assert action.next_retry_at == now + timedelta(seconds=5)
    assert action.last_error_code == "provider_error"
    assert action.status == "ambiguous"
