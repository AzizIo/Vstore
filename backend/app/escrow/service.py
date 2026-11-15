"""Durable idempotency primitives for testnet escrow wallet actions.

No helper in this module signs or broadcasts a transaction. Wallet references are
untrusted reconciliation hints and cannot advance the canonical deal state.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
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
    if action.submission_reference_sha256 is not None:
        if action.submission_reference_sha256 == digest:
            # A duplicate client report is harmless and remains idempotent even if
            # the observer has already reconciled/finalized the real chain event.
            return
        # Conflicting claims are suspicious, but they cannot rewrite a finalized
        # chain fact. For non-terminal actions, park the action for manual review.
        if action.status != "finalized":
            action.status = "manual_review"
            action.last_error_code = "submission_reference_conflict"
        raise EscrowActionConflict("submission_reference_conflict")
    if action.unsigned_boc_sha256 is None or action.status not in {
        "prepared", "submitted", "ambiguous"
    }:
        raise EscrowActionConflict("action_not_prepared")
    action.submission_reference = normalized
    action.submission_reference_sha256 = digest
    action.status = "ambiguous"
    action.attempt_count += 1
    action.last_error_code = "awaiting_independent_chain_reconciliation"



async def claim_next_action(
    session: AsyncSession,
    *,
    now: datetime,
    lease_seconds: int = 90,
) -> EscrowWalletActionRecord | None:
    """Claim one due action using PostgreSQL SKIP LOCKED and a fencing token.

    The caller commits the lease before any provider/broadcast operation. A
    second worker skips this row; a stale worker cannot release a newer lease.
    """
    if lease_seconds < 1 or lease_seconds > 900:
        raise ValueError("invalid_lease_seconds")
    action = await session.scalar(
        select(EscrowWalletActionRecord)
        .where(
            EscrowWalletActionRecord.status.in_(
                ("pending", "prepared", "submitted", "ambiguous")
            ),
            or_(
                EscrowWalletActionRecord.next_retry_at.is_(None),
                EscrowWalletActionRecord.next_retry_at <= now,
            ),
            or_(
                EscrowWalletActionRecord.lease_until.is_(None),
                EscrowWalletActionRecord.lease_until <= now,
            ),
        )
        .order_by(EscrowWalletActionRecord.created_at, EscrowWalletActionRecord.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if action is None:
        return None
    action.lease_token = uuid4()
    action.lease_until = now + timedelta(seconds=lease_seconds)
    return action


async def release_action_lease(
    session: AsyncSession,
    *,
    action_id: UUID,
    lease_token: UUID,
    now: datetime,
    retry_after_seconds: int,
    error_code: str | None,
    ambiguous: bool = False,
) -> bool:
    """Release only the lease still owned by this worker and schedule recovery."""
    if retry_after_seconds < 0 or retry_after_seconds > 86_400:
        raise ValueError("invalid_retry_after_seconds")
    action = await session.scalar(
        select(EscrowWalletActionRecord)
        .where(EscrowWalletActionRecord.id == action_id)
        .with_for_update()
    )
    if action is None or action.lease_token != lease_token:
        return False
    action.lease_token = None
    action.lease_until = None
    action.next_retry_at = now + timedelta(seconds=retry_after_seconds)
    if error_code is not None and (
        not 1 <= len(error_code) <= 64
        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in error_code)
    ):
        error_code = "provider_error"
    action.last_error_code = error_code
    if ambiguous:
        action.status = "ambiguous"
    return True
