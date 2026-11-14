"""Restartable, lease-fenced observer for normalized TON testnet escrow events.

No provider is enabled until the smart-contract ABI and evidence guarantees are
reviewed. This observer never treats a client transaction hash as evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.escrow.domain import (
    TERMINAL_DEAL_STATES,
    DealEvidenceSnapshot,
    EscrowDealStatus,
    EscrowDomainError,
    NormalizedEventEvidence,
    transition_for_verified_event,
    validate_event_against_deal,
)
from app.escrow.models import EscrowChainEvent, EscrowDeal, EscrowObserverCheckpoint
from app.escrow.provider import (
    EscrowProviderInvalidEvidence,
    EscrowProviderUnavailable,
    NormalizedChainEvent,
    TONTestnetEscrowProvider,
)

logger = logging.getLogger(__name__)
CHECKPOINT_ID = "ton-testnet-escrow"
LEASE_SECONDS = 90
MAX_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class EscrowObserverPassResult:
    scanned: int = 0
    applied: int = 0
    rejected: int = 0
    duplicates: int = 0
    unmatched: int = 0
    lease_lost: bool = False
    provider_unavailable: bool = False
    persistence_failed: bool = False


SessionFactory = async_sessionmaker[AsyncSession]


def _payload(event: NormalizedChainEvent) -> dict[str, Any]:
    value = asdict(event)
    value["event_type"] = event.event_type.value
    return value


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _stored_evidence_hash(event: NormalizedChainEvent) -> str:
    """Return a valid digest even when the provider supplies malformed metadata."""
    supplied = event.evidence_sha256
    if len(supplied) == 64 and all(char in "0123456789abcdef" for char in supplied.lower()):
        return supplied.lower()
    return _sha256_json(_payload(event))


def _event_snapshot(event: NormalizedChainEvent) -> NormalizedEventEvidence:
    return NormalizedEventEvidence(
        network=event.network,
        contract_address=event.contract_address,
        event_type=event.event_type,
        source_address=event.source_address,
        destination_address=event.destination_address,
        item_address=event.item_address,
        amount_nanotons=(
            int(event.amount_nanotons) if event.amount_nanotons is not None else None
        ),
        masterchain_seqno=event.masterchain_seqno,
        finalized=event.finalized,
    )


def _deal_snapshot(deal: EscrowDeal) -> DealEvidenceSnapshot:
    return DealEvidenceSnapshot(
        network=deal.network,
        contract_address=deal.contract_address,
        item_address=deal.item_address,
        seller_address=deal.seller_address_snapshot,
        buyer_address=deal.buyer_address_snapshot,
        principal_nanotons=int(deal.principal_nanotons),
    )


async def _persist_unapplied_event(
    session: AsyncSession,
    event: NormalizedChainEvent,
    *,
    status: str,
    reason_code: str | None,
    deal_id: uuid.UUID | None = None,
) -> None:
    existing = await session.scalar(
        select(EscrowChainEvent).where(
            EscrowChainEvent.network == event.network,
            EscrowChainEvent.transaction_hash == event.transaction_hash,
            EscrowChainEvent.event_index == event.event_index,
        )
    )
    if existing is not None:
        if existing.evidence_sha256 != _stored_evidence_hash(event):
            existing.status = "manual_review"
            existing.reason_code = "event_evidence_conflict"
        return
    session.add(
        EscrowChainEvent(
            network=event.network,
            transaction_hash=event.transaction_hash,
            event_index=event.event_index,
            event_type=event.event_type.value,
            contract_address=event.contract_address,
            deal_id=deal_id,
            source_address=event.source_address,
            destination_address=event.destination_address,
            item_address=event.item_address,
            amount_nanotons=event.amount_nanotons,
            masterchain_seqno=event.masterchain_seqno,
            finalized=event.finalized,
            evidence_sha256=_stored_evidence_hash(event),
            payload_json=_payload(event),
            status=status,
            reason_code=reason_code,
        )
    )


async def _apply_one_event(
    session: AsyncSession,
    event: NormalizedChainEvent,
    *,
    provider_verified: bool,
) -> str:
    existing = await session.scalar(
        select(EscrowChainEvent).where(
            EscrowChainEvent.network == event.network,
            EscrowChainEvent.transaction_hash == event.transaction_hash,
            EscrowChainEvent.event_index == event.event_index,
        )
    )
    if existing is not None:
        if existing.evidence_sha256 != _stored_evidence_hash(event):
            existing.status = "manual_review"
            existing.reason_code = "event_evidence_conflict"
            if existing.deal_id is not None:
                deal = await session.get(EscrowDeal, existing.deal_id, with_for_update=True)
                if deal is not None and deal.status not in {s.value for s in TERMINAL_DEAL_STATES}:
                    deal.status = EscrowDealStatus.MANUAL_REVIEW.value
            return "rejected"
        return "duplicates"

    if (
        event.network != "testnet"
        or event.event_index < 0
        or not event.transaction_hash
        or len(event.transaction_hash) > 128
        or len(event.evidence_sha256) != 64
        or any(char not in "0123456789abcdef" for char in event.evidence_sha256.lower())
        or event.masterchain_seqno <= 0
        or not event.finalized
        or not provider_verified
    ):
        await _persist_unapplied_event(
            session,
            event,
            status="rejected",
            reason_code="unverified_or_non_final_event",
        )
        return "rejected"

    try:
        deal_uuid = uuid.UUID(event.deal_id) if event.deal_id else None
    except ValueError:
        deal_uuid = None
    if deal_uuid is None:
        await _persist_unapplied_event(
            session, event, status="unmatched", reason_code="deal_reference_missing"
        )
        return "unmatched"

    deal = await session.scalar(
        select(EscrowDeal).where(EscrowDeal.id == deal_uuid).with_for_update()
    )
    if deal is None:
        await _persist_unapplied_event(
            session, event, status="unmatched", reason_code="deal_not_found", deal_id=deal_uuid
        )
        return "unmatched"

    # Without an ABI-approved deploy/factory reference, there is no trusted
    # contract address to bind to this intent. Never learn the address from an
    # arbitrary event or from a client-provided transaction hash.
    if not deal.contract_address or event.contract_address != deal.contract_address:
        await _persist_unapplied_event(
            session,
            event,
            status="rejected",
            reason_code="contract_address_mismatch_or_unbound",
            deal_id=deal.id,
        )
        return "rejected"

    if deal.last_chain_seqno is not None and event.masterchain_seqno < deal.last_chain_seqno:
        await _persist_unapplied_event(
            session, event, status="rejected", reason_code="stale_chain_event", deal_id=deal.id
        )
        return "rejected"

    try:
        validate_event_against_deal(_event_snapshot(event), _deal_snapshot(deal))
        target = transition_for_verified_event(deal.status, event.event_type)
    except (EscrowDomainError, ValueError):
        await _persist_unapplied_event(
            session,
            event,
            status="manual_review",
            reason_code="event_invariant_or_transition_failure",
            deal_id=deal.id,
        )
        if deal.status not in {state.value for state in TERMINAL_DEAL_STATES}:
            deal.status = EscrowDealStatus.MANUAL_REVIEW.value
        return "rejected"

    await _persist_unapplied_event(
        session, event, status="applied", reason_code=None, deal_id=deal.id
    )
    deal.status = target.value
    deal.last_chain_seqno = max(deal.last_chain_seqno or 0, event.masterchain_seqno)
    return "applied"


async def _release_lease(
    session_factory: SessionFactory,
    lease_token: uuid.UUID,
    *,
    error_code: str | None,
    now: datetime,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            checkpoint = await session.scalar(
                select(EscrowObserverCheckpoint)
                .where(EscrowObserverCheckpoint.checkpoint_id == CHECKPOINT_ID)
                .with_for_update()
            )
            if checkpoint is None or checkpoint.lease_token != lease_token:
                return
            checkpoint.lease_token = None
            checkpoint.lease_until = None
            checkpoint.last_error_code = error_code
            checkpoint.next_scan_at = now + timedelta(seconds=15) if error_code else now


async def run_observer_pass(
    session_factory: SessionFactory,
    provider: TONTestnetEscrowProvider,
    *,
    now: datetime | None = None,
    limit: int = 25,
) -> EscrowObserverPassResult:
    """Scan one bounded testnet batch with a durable cursor and fenced lease.

    The checkpoint row is created by the escrow migration. Provider I/O happens
    outside SQL transactions. Cursor advancement and event projection commit in
    one transaction so a process restart replays safely rather than skipping rows.
    """
    if limit < 1 or limit > MAX_BATCH_SIZE:
        raise ValueError(f"Observer limit must be between 1 and {MAX_BATCH_SIZE}")
    current_time = now or datetime.now(UTC)
    lease_token = uuid.uuid4()
    async with session_factory() as session:
        async with session.begin():
            checkpoint = await session.scalar(
                select(EscrowObserverCheckpoint)
                .where(EscrowObserverCheckpoint.checkpoint_id == CHECKPOINT_ID)
                .with_for_update()
            )
            if checkpoint is None:
                raise RuntimeError("Escrow observer checkpoint is missing; migration is required")
            if checkpoint.network != "testnet":
                raise RuntimeError("Escrow observer refuses a non-testnet checkpoint")
            if checkpoint.next_scan_at and checkpoint.next_scan_at > current_time:
                return EscrowObserverPassResult()
            if checkpoint.lease_until and checkpoint.lease_until > current_time:
                return EscrowObserverPassResult(lease_lost=True)
            cursor = checkpoint.cursor
            checkpoint.lease_token = lease_token
            checkpoint.lease_until = current_time + timedelta(seconds=LEASE_SECONDS)

    try:
        batch = await provider.scan_events(cursor=cursor, limit=limit)
        if batch.events and (not batch.next_cursor or batch.next_cursor == cursor):
            raise EscrowProviderInvalidEvidence(
                "A non-empty batch must provide a progressing, restartable next cursor"
            )
        verified_events: list[tuple[NormalizedChainEvent, bool]] = []
        for event in batch.events:
            # Reject obvious network / hash malformation before provider work.
            if event.network != "testnet":
                verified_events.append((event, False))
                continue
            verified_events.append((event, await provider.verify_event(event)))
    except EscrowProviderUnavailable:
        await _release_lease(
            session_factory, lease_token, error_code="provider_unavailable", now=current_time
        )
        return EscrowObserverPassResult(provider_unavailable=True)
    except Exception:
        logger.exception("Escrow provider scan failed; cursor remains unchanged")
        await _release_lease(
            session_factory, lease_token, error_code="provider_or_evidence_error", now=current_time
        )
        return EscrowObserverPassResult(provider_unavailable=True)

    result_counts = {"applied": 0, "rejected": 0, "duplicates": 0, "unmatched": 0}
    try:
        async with session_factory() as session:
            async with session.begin():
                checkpoint = await session.scalar(
                    select(EscrowObserverCheckpoint)
                    .where(EscrowObserverCheckpoint.checkpoint_id == CHECKPOINT_ID)
                    .with_for_update()
                )
                if checkpoint is None or checkpoint.lease_token != lease_token:
                    return EscrowObserverPassResult(scanned=len(batch.events), lease_lost=True)
                for event, verified in verified_events:
                    applied_result = await _apply_one_event(
                        session, event, provider_verified=verified
                    )
                    result_counts[applied_result] += 1
                # A no-event provider response may omit its cursor. Never erase a
                # previously durable cursor as a side effect of an empty scan.
                if batch.next_cursor is not None:
                    checkpoint.cursor = batch.next_cursor
                if verified_events:
                    latest_seqno = max(
                        (
                            event.masterchain_seqno
                            for event, verified in verified_events
                            if verified
                        ),
                        default=None,
                    )
                    if latest_seqno is not None:
                        checkpoint.last_masterchain_seqno = max(
                            checkpoint.last_masterchain_seqno or 0, latest_seqno
                        )
                checkpoint.lease_token = None
                checkpoint.lease_until = None
                checkpoint.next_scan_at = current_time
                checkpoint.last_error_code = None
    except Exception:
        # The event writes and cursor are one transaction; on any DB failure the
        # cursor rolls back. Release the fencing lease so the same batch can retry.
        logger.exception("Escrow event batch could not be persisted; cursor remains unchanged")
        await _release_lease(
            session_factory,
            lease_token,
            error_code="batch_persistence_failed",
            now=current_time,
        )
        return EscrowObserverPassResult(
            scanned=len(batch.events), persistence_failed=True
        )

    return EscrowObserverPassResult(
        scanned=len(batch.events),
        applied=result_counts["applied"],
        rejected=result_counts["rejected"],
        duplicates=result_counts["duplicates"],
        unmatched=result_counts["unmatched"],
    )
