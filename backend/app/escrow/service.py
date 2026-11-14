"""Durable idempotency primitives for testnet escrow wallet actions.

No helper in this module signs or broadcasts a transaction. Wallet references are
untrusted reconciliation hints and cannot advance the canonical deal state.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.escrow.models import EscrowWalletActionRecord


class EscrowActionConflict(ValueError):
    """An idempotency key or transaction reference conflicts with stored evidence."""


def canonical_request_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def create_or_replay_action(
    session: AsyncSession,
    *,
    actor_id: UUID,
    deal_id: UUID,
    action_type: str,
    idempotency_key: str,
    request_sha256: str,
) -> tuple[EscrowWalletActionRecord, bool]:
    """Return the existing action for an exact replay, otherwise insert a new intent.

    The caller must commit this row before any external side effect. A changed
    request under the same actor/action/key is always a conflict.
    """
    if not 8 <= len(idempotency_key) <= 128:
        raise EscrowActionConflict("invalid_idempotency_key")
    if len(request_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in request_sha256):
        raise EscrowActionConflict("invalid_request_hash")
    existing = await session.scalar(
        select(EscrowWalletActionRecord)
        .where(
            EscrowWalletActionRecord.actor_id == actor_id,
            EscrowWalletActionRecord.action_type == action_type,
            EscrowWalletActionRecord.idempotency_key == idempotency_key,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.request_sha256 != request_sha256 or existing.deal_id != deal_id:
            raise EscrowActionConflict("idempotency_payload_conflict")
        return existing, False

    action = EscrowWalletActionRecord(
        actor_id=actor_id,
        deal_id=deal_id,
        action_type=action_type,
        network="testnet",
        idempotency_key=idempotency_key,
        request_sha256=request_sha256,
        status="pending",
        attempt_count=0,
    )
    session.add(action)
    await session.flush()
    return action, True


def record_submission_reference(
    action: EscrowWalletActionRecord,
    *,
    reference: str,
) -> None:
    """Record one client-supplied hint; never treat it as transaction evidence."""
    normalized = reference.strip()
    if not normalized or len(normalized) > 512:
        raise EscrowActionConflict("invalid_submission_reference")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if action.unsigned_boc_sha256 is None or action.status not in {"prepared", "submitted", "ambiguous"}:
        raise EscrowActionConflict("action_not_prepared")
    if action.submission_reference_sha256 is not None:
        if action.submission_reference_sha256 != digest:
            action.status = "manual_review"
            action.last_error_code = "submission_reference_conflict"
            raise EscrowActionConflict("submission_reference_conflict")
        return
    action.submission_reference = normalized
    action.submission_reference_sha256 = digest
    action.status = "ambiguous"
    action.attempt_count += 1
    action.last_error_code = "awaiting_independent_chain_reconciliation"
