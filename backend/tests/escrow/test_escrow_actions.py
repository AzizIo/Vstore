from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from app.escrow.models import EscrowWalletActionRecord
from app.escrow.service import (
    EscrowActionConflict,
    canonical_request_sha256,
    record_submission_reference,
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
