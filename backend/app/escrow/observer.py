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
    RAW_EVIDENCE_EVENTS,
    DealEvidenceSnapshot,
    EscrowChainEventType,
    EscrowDealStatus,
    EscrowDomainError,
    is_raw_evidence_event,
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
    pending: int = 0
    lease_lost: bool = False
    provider_unavailable: bool = False
    persistence_failed: bool = False


SessionFactory = async_sessionmaker[AsyncSession]


def _payload(event: NormalizedChainEvent) -> dict[str, Any]:
    value = asdict(event)
    value["event_type"] = event.event_type.value
    return value


def _sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _stored_evidence_hash(event: NormalizedChainEvent) -> str:
    digest = event.evidence_sha256
    if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest.lower()):
        return digest.lower()
    return _sha256_json(_payload(event))


def _event_snapshot(event: NormalizedChainEvent) -> NormalizedEventEvidence:
    return NormalizedEventEvidence(
        network=event.network, contract_address=event.contract_address, event_type=event.event_type,
        source_address=event.source_address, destination_address=event.destination_address,
        item_address=event.item_address,
        amount_nanotons=int(event.amount_nanotons) if event.amount_nanotons is not None else None,
        masterchain_seqno=event.masterchain_seqno, finalized=event.finalized,
        logical_time=event.logical_time, message_hash=event.message_hash, trace_id=event.trace_id,
        phase=event.phase, attempt_id=event.attempt_id, query_id=event.query_id,
        deal_salt=event.deal_salt, observed_contract_state=event.observed_contract_state,
        attestation_accepted=event.attestation_accepted,
        contract_state_reconciled=event.contract_state_reconciled,
    )


def _deal_snapshot(deal: EscrowDeal) -> DealEvidenceSnapshot:
    return DealEvidenceSnapshot(
        network=deal.network, contract_address=deal.contract_address,
        collection_address=deal.collection_address_snapshot, item_address=deal.item_address,
        seller_address=deal.seller_address_snapshot, buyer_address=deal.buyer_address_snapshot,
        principal_nanotons=int(deal.principal_nanotons),
    )


async def _persist_event(
    session: AsyncSession, event: NormalizedChainEvent, *, status: str,
    reason_code: str | None, deal_id: uuid.UUID | None,
    existing: EscrowChainEvent | None = None,
) -> EscrowChainEvent:
    payload = _payload(event)
    if existing is None:
        row = EscrowChainEvent(
            id=uuid.uuid4(), network=event.network, event_key=event.event_key,
            transaction_hash=event.transaction_hash, event_index=event.event_index,
            message_hash=event.message_hash, trace_id=event.trace_id, logical_time=event.logical_time,
            phase=event.phase, attempt_id=event.attempt_id, query_id=event.query_id,
            operation_id=event.operation_id, deal_salt=event.deal_salt,
            account_address=event.account_address, observed_contract_state=event.observed_contract_state,
            contract_state_reconciled=event.contract_state_reconciled,
            event_type=event.event_type.value, contract_address=event.contract_address, deal_id=deal_id,
            source_address=event.source_address, destination_address=event.destination_address,
            item_address=event.item_address, amount_nanotons=event.amount_nanotons,
            masterchain_seqno=event.masterchain_seqno, finalized=event.finalized,
            evidence_sha256=_stored_evidence_hash(event), payload_json=payload,
            status=status, reason_code=reason_code,
        )
        session.add(row)
        return row

    old = existing.payload_json or {}
    immutable_fields = (
        "event_type", "contract_address", "deal_id", "source_address", "destination_address",
        "item_address", "amount_nanotons", "message_hash", "trace_id", "logical_time", "phase",
        "attempt_id", "query_id", "operation_id", "deal_salt",
    )
    if any(old.get(field) not in (None, payload.get(field)) for field in immutable_fields):
        existing.status = "manual_review"
        existing.reason_code = "event_correlation_conflict"
        return existing
    # Promotion from pending -> final is monotonic. Keep one durable row per stable
    # event identity; different trace/phase/attempt IDs remain separate events.
    existing.finalized = existing.finalized or event.finalized
    existing.masterchain_seqno = max(existing.masterchain_seqno, event.masterchain_seqno)
    existing.evidence_sha256 = _stored_evidence_hash(event)
    existing.payload_json = payload
    existing.observed_contract_state = event.observed_contract_state or existing.observed_contract_state
    existing.contract_state_reconciled = existing.contract_state_reconciled or event.contract_state_reconciled
    existing.account_address = event.account_address or existing.account_address
    existing.deal_id = deal_id or existing.deal_id
    existing.status = status
    existing.reason_code = reason_code
    return existing


async def _apply_one_event(
    session: AsyncSession, event: NormalizedChainEvent, *, provider_verified: bool,
) -> str:
    existing = await session.scalar(select(EscrowChainEvent).where(
        EscrowChainEvent.network == event.network, EscrowChainEvent.event_key == event.event_key,
    ))
    if existing is not None and existing.status in {"applied", "manual_review", "unmatched", "rejected"}:
        if existing.status == "applied":
            old = existing.payload_json or {}
            new = _payload(event)
            stable = ("event_type", "contract_address", "deal_id", "source_address", "destination_address",
                      "item_address", "amount_nanotons", "message_hash", "trace_id", "logical_time",
                      "phase", "attempt_id", "query_id", "operation_id", "deal_salt")
            if any(old.get(k) != new.get(k) for k in stable):
                existing.status = "manual_review"
                existing.reason_code = "event_correlation_conflict"
                return "rejected"
            return "duplicates"
        return "rejected"

    valid_shape = (
        event.network == "testnet" and bool(event.transaction_hash)
        and len(event.transaction_hash) <= 128 and event.event_index >= 0
        and len(event.evidence_sha256) == 64
        and all(ch in "0123456789abcdef" for ch in event.evidence_sha256.lower())
        and bool(event.event_key)
    )
    if not valid_shape:
        await _persist_event(session, event, status="rejected",
            reason_code="invalid_event_shape", deal_id=None, existing=existing)
        return "rejected"
    if not provider_verified:
        await _persist_event(session, event, status="pending",
            reason_code="awaiting_provider_verification", deal_id=None, existing=existing)
        return "pending"
    if not event.finalized or event.masterchain_seqno <= 0:
        await _persist_event(session, event, status="pending",
            reason_code="awaiting_finality", deal_id=None, existing=existing)
        return "pending"
    if is_raw_evidence_event(event.event_type):
        # Persist forensic evidence, but it is not a canonical transition and
        # does not place the deal in MANUAL_REVIEW by itself.
        await _persist_event(session, event, status="rejected",
            reason_code="raw_evidence_not_contract_attestation", deal_id=None, existing=existing)
        return "rejected"

    try:
        deal_uuid = uuid.UUID(event.deal_id) if event.deal_id else None
    except ValueError:
        deal_uuid = None
    if deal_uuid is None:
        await _persist_event(session, event, status="pending",
            reason_code="deal_reference_missing", deal_id=None, existing=existing)
        return "unmatched"
    deal = await session.scalar(select(EscrowDeal).where(EscrowDeal.id == deal_uuid).with_for_update())
    if deal is None:
        await _persist_event(session, event, status="pending",
            reason_code="deal_not_found", deal_id=deal_uuid, existing=existing)
        return "unmatched"

    if event.deal_salt != deal.deal_salt:
        await _persist_event(session, event, status="manual_review",
            reason_code="deal_salt_mismatch", deal_id=deal.id, existing=existing)
        return "rejected"
    if not deal.contract_address or event.contract_address != deal.contract_address:
        await _persist_event(session, event, status="pending",
            reason_code="contract_address_not_reconciled", deal_id=deal.id, existing=existing)
        return "rejected"
    if (
        deal.last_chain_seqno is not None
        and (
            event.masterchain_seqno < deal.last_chain_seqno
            or (
                event.masterchain_seqno == deal.last_chain_seqno
                and event.logical_time is not None
                and deal.last_chain_logical_time is not None
                and event.logical_time < deal.last_chain_logical_time
            )
        )
    ):
        await _persist_event(session, event, status="pending",
            reason_code="stale_chain_event", deal_id=deal.id, existing=existing)
        return "rejected"

    if event.event_type in RAW_EVIDENCE_EVENTS:
        # Layer A: retain provider evidence as pending only. It is not a contract
        # state transition and must not push the Deal into MANUAL_REVIEW.
        await _persist_event(
            session, event, status="pending", reason_code="raw_evidence_observed_only",
            deal_id=deal.id, existing=existing,
        )
        return "rejected"

    try:
        validate_event_against_deal(_event_snapshot(event), _deal_snapshot(deal))
        next_state = transition_for_verified_event(deal.status, event.event_type)
    except (EscrowDomainError, ValueError):
        await _persist_event(session, event, status="manual_review",
            reason_code="event_invariant_or_transition_failure", deal_id=deal.id, existing=existing)
        if deal.status not in {s.value for s in TERMINAL_DEAL_STATES}:
            deal.status = EscrowDealStatus.MANUAL_REVIEW.value
        return "rejected"

    if event.event_type is EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED:
        # Provider adapter must confirm accepted oracle evidence and reconciled
        # contract state; raw NFT transfer evidence cannot reach this branch.
        if (event.observed_contract_state != next_state.value or not event.attestation_accepted
                or not event.contract_state_reconciled):
            await _persist_event(session, event, status="manual_review",
                reason_code="oracle_state_not_reconciled", deal_id=deal.id, existing=existing)
            deal.status = EscrowDealStatus.MANUAL_REVIEW.value
            return "rejected"

    await _persist_event(session, event, status="applied",
        reason_code=None, deal_id=deal.id, existing=existing)
    deal.status = next_state.value
    deal.last_chain_seqno = max(deal.last_chain_seqno or 0, event.masterchain_seqno)
    if event.logical_time is not None:
        deal.last_chain_logical_time = max(deal.last_chain_logical_time or 0, event.logical_time)
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
        ordered_events = sorted(
            batch.events,
            key=lambda item: (
                item.masterchain_seqno,
                item.logical_time if item.logical_time is not None else -1,
                item.transaction_hash,
                item.event_index,
                item.trace_id or "",
                item.phase or "",
                item.attempt_id or "",
            ),
        )
        for event in ordered_events:
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

    result_counts = {"applied": 0, "rejected": 0, "duplicates": 0, "unmatched": 0, "pending": 0}
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
                cursor_safe = True
                for event, verified in verified_events:
                    applied_result = await _apply_one_event(session, event, provider_verified=verified)
                    result_counts[applied_result] += 1
                    if applied_result in {"pending", "unmatched"}:
                        cursor_safe = False
                # A pending/non-final/unmatched event pins the cursor at the batch
                # start. The same page is rescanned until it can be promoted safely.
                if batch.next_cursor is not None and cursor_safe:
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
                checkpoint.next_scan_at = current_time + (timedelta(seconds=10) if not cursor_safe else timedelta(0))
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
        pending=result_counts["pending"],
    )
