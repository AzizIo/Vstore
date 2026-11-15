"""Restartable, lease-fenced observer for normalized TON testnet escrow events.

No provider is enabled until the smart-contract ABI and evidence guarantees are
reviewed. This observer never treats a client transaction hash as evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Listing, ListingStatus, NFTAsset
from app.escrow.domain import (
    TERMINAL_DEAL_STATES,
    DealEvidenceSnapshot,
    EscrowChainEventType,
    EscrowDealStatus,
    EscrowDomainError,
    NormalizedEventEvidence,
    is_raw_evidence_event,
    transition_for_verified_event,
    validate_event_against_deal,
)
from app.escrow.models import (
    EscrowChainEvent,
    EscrowDeal,
    EscrowListingIntent,
    EscrowObserverCheckpoint,
)
from app.escrow.provider import (
    EscrowProviderInvalidEvidence,
    EscrowProviderUnavailable,
    FinalityVerification,
    NormalizedChainEvent,
    TerminalOwnerVerification,
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
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        default=str).encode()).hexdigest()


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
        collection_address=event.collection_address,
        amount_nanotons=int(event.amount_nanotons) if event.amount_nanotons is not None else None,
        masterchain_seqno=event.masterchain_seqno, finalized=event.finalized,
        logical_time=event.logical_time, message_hash=event.message_hash, trace_id=event.trace_id,
        phase=event.phase, attempt_id=event.attempt_id, query_id=event.query_id,
        deal_salt=event.deal_salt, observed_contract_state=event.observed_contract_state,
        attestation_accepted=event.attestation_accepted,
        contract_state_reconciled=event.contract_state_reconciled,
    )


def _deal_snapshot(deal: EscrowDeal) -> DealEvidenceSnapshot:
    snapshot = getattr(deal, "deployment_snapshot_json", None)
    execution_reserve = (
        snapshot.get("execution_reserve_nanotons")
        if isinstance(snapshot, dict)
        else None
    )
    return DealEvidenceSnapshot(
        network=deal.network,
        contract_address=deal.contract_address,
        collection_address=deal.collection_address_snapshot,
        item_address=deal.item_address,
        seller_address=deal.seller_address_snapshot,
        buyer_address=deal.buyer_address_snapshot,
        principal_nanotons=int(deal.principal_nanotons),
        execution_reserve_nanotons=(
            int(execution_reserve)
            if isinstance(execution_reserve, int) and not isinstance(execution_reserve, bool)
            else None
        ),
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
            message_hash=event.message_hash, trace_id=event.trace_id,
                logical_time=event.logical_time,
            phase=event.phase, attempt_id=event.attempt_id, query_id=event.query_id,
            operation_id=event.operation_id, deal_salt=event.deal_salt,
            account_address=event.account_address,
                observed_contract_state=event.observed_contract_state,
            contract_state_reconciled=event.contract_state_reconciled,
            event_type=event.event_type.value, contract_address=event.contract_address,
                deal_id=deal_id,
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
        "transaction_hash",
        "event_index",
        "event_type",
        "contract_address",
        "deal_id",
        "account_address",
        "observed_contract_state",
        "source_address",
        "destination_address",
        "item_address",
        "collection_address",
        "amount_nanotons",
        "message_hash",
        "trace_id",
        "logical_time",
        "phase",
        "attempt_id",
        "query_id",
        "operation_id",
        "deal_salt",
    )
    if (
        any(old.get(field) not in (None, payload.get(field)) for field in immutable_fields)
        or (old.get("finalized") and not event.finalized)
        or (
            old.get("finalized")
            and event.finalized
            and old.get("masterchain_seqno") != event.masterchain_seqno
        )
    ):
        existing.status = "manual_review"
        existing.reason_code = "event_correlation_conflict"
        return existing
    # Promotion from pending -> final is monotonic. Keep one durable row per stable
    # event identity; different trace/phase/attempt IDs remain separate events.
    if (
        existing.contract_state_reconciled and not event.contract_state_reconciled
    ) or (old.get("attestation_accepted") and not event.attestation_accepted):
        existing.status = "manual_review"
        existing.reason_code = "event_correlation_conflict"
        return existing
    existing.finalized = existing.finalized or event.finalized
    existing.contract_state_reconciled = (
        existing.contract_state_reconciled or event.contract_state_reconciled
    )
    existing.masterchain_seqno = max(existing.masterchain_seqno, event.masterchain_seqno)
    existing.evidence_sha256 = _stored_evidence_hash(event)
    existing.payload_json = payload
    existing.observed_contract_state = (
        event.observed_contract_state or existing.observed_contract_state
    )
    existing.account_address = event.account_address or existing.account_address
    existing.deal_id = deal_id or existing.deal_id
    existing.status = status
    existing.reason_code = reason_code
    return existing


async def _reconcile_terminal_listing(
    session: AsyncSession,
    deal: EscrowDeal,
    next_state: EscrowDealStatus,
    event: NormalizedChainEvent,
) -> bool:
    """Release/relist only when terminal getter state and current owner agree."""
    intent_hint = await session.scalar(
        select(EscrowListingIntent).where(EscrowListingIntent.id == deal.listing_intent_id)
    )
    if intent_hint is None:
        return False
    listing = await session.scalar(
        select(Listing)
        .where(Listing.id == intent_hint.marketplace_listing_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    intent = await session.scalar(
        select(EscrowListingIntent)
        .where(EscrowListingIntent.id == deal.listing_intent_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if listing is None or intent is None:
        return False
    asset = await session.scalar(
        select(NFTAsset)
        .where(NFTAsset.id == intent.asset_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if asset is None:
        intent.status = "manual_review"
        return False

    expected_owner = (
        deal.buyer_address_snapshot
        if next_state is EscrowDealStatus.SETTLED
        else deal.seller_address_snapshot
    )
    proof_hash = event.terminal_owner_proof_sha256 or ""
    owner_proof_valid = (
        event.terminal_owner_address == expected_owner
        and event.terminal_owner_masterchain_seqno is not None
        and event.terminal_owner_masterchain_seqno >= event.masterchain_seqno
        and len(proof_hash) == 64
        and all(char in "0123456789abcdef" for char in proof_hash.lower())
        and bool(event.terminal_owner_provider)
        and event.item_address == deal.item_address
        and intent.item_address == deal.item_address
        and asset.item_address == deal.item_address
        and listing.status is ListingStatus.RESERVED
    )
    if not owner_proof_valid:
        # Fail closed: keep the marketplace reservation and require operator review.
        intent.status = "manual_review"
        return False

    if next_state is EscrowDealStatus.SETTLED:
        listing.status = ListingStatus.SOLD
        intent.status = "cancelled"
        asset.owner_id = deal.buyer_id
    elif next_state in {EscrowDealStatus.REFUNDED, EscrowDealStatus.EXPIRED}:
        listing.status = ListingStatus.ACTIVE
        intent.status = "active"
        asset.owner_id = deal.seller_id
    else:
        intent.status = "manual_review"
        return False
    return True


async def _terminal_owner_evidence(
    session_factory: SessionFactory,
    provider: TONTestnetEscrowProvider,
    event: NormalizedChainEvent,
) -> NormalizedChainEvent:
    """Fetch current-owner proof outside transactions for confirmed terminal events."""
    if (
        not event.deal_id
        or not event.contract_state_reconciled
        or not event.observed_contract_state
    ):
        return event
    try:
        deal_id = uuid.UUID(event.deal_id)
    except ValueError:
        return event
    async with session_factory() as session:
        deal = await session.scalar(select(EscrowDeal).where(EscrowDeal.id == deal_id))
    if deal is None:
        return event
    try:
        if (
            deal.status in {state.value for state in TERMINAL_DEAL_STATES}
            and event.observed_contract_state == deal.status
        ):
            # The canonical event may already have advanced the deal while
            # listing release stayed pinned on missing owner evidence. Re-query
            # the current owner for the same terminal result on replay.
            next_state = EscrowDealStatus(deal.status)
        else:
            next_state = transition_for_verified_event(
                deal.status, event.event_type, event.observed_contract_state
            )
    except (EscrowDomainError, ValueError):
        return event
    if (
        next_state not in TERMINAL_DEAL_STATES
        or event.observed_contract_state != next_state.value
        or not event.item_address
    ):
        return event
    expected_owner = (
        deal.buyer_address_snapshot
        if next_state is EscrowDealStatus.SETTLED
        else deal.seller_address_snapshot
    )
    proof = await provider.verify_terminal_owner(
        item_address=deal.item_address,
        expected_owner_address=expected_owner,
        minimum_masterchain_seqno=event.masterchain_seqno,
    )
    if isinstance(proof, TerminalOwnerVerification) and proof.matches(
        item_address=deal.item_address,
        expected_owner_address=expected_owner,
        minimum_masterchain_seqno=event.masterchain_seqno,
    ):
        return replace(
            event,
            terminal_owner_address=proof.owner_address,
            terminal_owner_proof_sha256=proof.proof_sha256,
            terminal_owner_masterchain_seqno=proof.masterchain_seqno,
            terminal_owner_provider=proof.provider_id,
        )
    return event


async def _apply_one_event(
    session: AsyncSession, event: NormalizedChainEvent, *, provider_verified: bool,
) -> str:
    existing = await session.scalar(select(EscrowChainEvent).where(
        EscrowChainEvent.network == event.network, EscrowChainEvent.event_key == event.event_key,
    ))
    if existing is not None:
        old = existing.payload_json or {}
        new = _payload(event)
        stable = (
            "transaction_hash",
            "event_index",
            "event_type",
            "contract_address",
            "deal_id",
            "account_address",
            "observed_contract_state",
            "source_address",
            "destination_address",
            "item_address",
            "collection_address",
            "amount_nanotons",
            "message_hash",
            "trace_id",
            "logical_time",
            "phase",
            "attempt_id",
            "query_id",
            "operation_id",
            "deal_salt",
        )
        conflict = any(
            old.get(key) not in (None, new.get(key)) for key in stable
        )
        conflict = conflict or (
            old.get("finalized")
            and (
                not event.finalized
                or (
                    event.finalized
                    and old.get("masterchain_seqno") != event.masterchain_seqno
                )
            )
        )
        conflict = conflict or (
            old.get("contract_state_reconciled")
            and not event.contract_state_reconciled
        )
        conflict = conflict or (
            old.get("attestation_accepted") and not event.attestation_accepted
        )
        if conflict:
            existing.status = "manual_review"
            existing.reason_code = "event_correlation_conflict"
            return "rejected"
        if existing.status in {"applied", "manual_review", "unmatched", "rejected"}:
            if existing.status == "applied":
                # A terminal chain state may be applied while marketplace release
                # remains pinned for missing current-owner evidence. Re-query that
                # evidence on replay instead of permanently treating the event as done.
                if existing.reason_code != "terminal_listing_owner_unverified":
                    return "duplicates"
            else:
                return "rejected"

    valid_shape = (
        event.network == "testnet"
        and bool(event.transaction_hash)
        and len(event.transaction_hash) <= 128
        and event.event_index >= 0
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
    if (
        not event.masterchain_block_hash
        or not event.finality_proof_sha256
        or not event.finality_provider
        or len(event.masterchain_block_hash) != 64
        or len(event.finality_proof_sha256) != 64
        or any(char not in "0123456789abcdef" for char in event.masterchain_block_hash.lower())
        or any(char not in "0123456789abcdef" for char in event.finality_proof_sha256.lower())
        or not event.message_hash
        or not event.trace_id
    ):
        await _persist_event(
            session, event, status="pending", reason_code="finality_proof_missing",
            deal_id=None, existing=existing,
        )
        return "pending"
    if is_raw_evidence_event(event.event_type):
        # Persist forensic evidence with its deal FK when a stable deal UUID is
        # present, but never call the canonical transition function for it.
        try:
            raw_deal_id = uuid.UUID(event.deal_id) if event.deal_id else None
        except ValueError:
            raw_deal_id = None
        linked_deal_id = None
        if raw_deal_id is not None:
            linked_deal_id = await session.scalar(
                select(EscrowDeal.id).where(EscrowDeal.id == raw_deal_id)
            )
        await _persist_event(session, event, status="rejected",
            reason_code="raw_evidence_not_contract_attestation",
            deal_id=linked_deal_id, existing=existing)
        return "rejected"

    try:
        deal_uuid = uuid.UUID(event.deal_id) if event.deal_id else None
    except ValueError:
        deal_uuid = None
    if deal_uuid is None:
        await _persist_event(session, event, status="pending",
            reason_code="deal_reference_missing", deal_id=None, existing=existing)
        return "unmatched"
    deal = await session.scalar(
        select(EscrowDeal)
        .where(EscrowDeal.id == deal_uuid)
        .with_for_update()
    )
    if deal is None:
        await _persist_event(session, event, status="pending",
            reason_code="deal_not_found", deal_id=None, existing=existing)
        return "unmatched"

    if event.deal_salt != deal.deal_salt:
        await _persist_event(session, event, status="manual_review",
            reason_code="deal_salt_mismatch", deal_id=deal.id, existing=existing)
        return "rejected"
    if not deal.contract_address or event.contract_address != deal.contract_address:
        await _persist_event(session, event, status="pending",
            reason_code="contract_address_not_reconciled", deal_id=deal.id, existing=existing)
        return "pending"
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
        return "pending"

    try:
        validate_event_against_deal(_event_snapshot(event), _deal_snapshot(deal))
        if (
            deal.status in {state.value for state in TERMINAL_DEAL_STATES}
            and event.contract_state_reconciled
            and event.observed_contract_state == deal.status
        ):
            # Replayed terminal evidence may only retry owner/listing reconciliation;
            # it cannot move a terminal deal to another state.
            next_state = EscrowDealStatus(deal.status)
        else:
            next_state = transition_for_verified_event(
                deal.status, event.event_type, event.observed_contract_state
            )
    except (EscrowDomainError, ValueError):
        await _persist_event(session, event, status="manual_review",
            reason_code="event_invariant_or_transition_failure", deal_id=deal.id, existing=existing)
        if deal.status not in {s.value for s in TERMINAL_DEAL_STATES}:
            deal.status = EscrowDealStatus.MANUAL_REVIEW.value
        return "rejected"

    if next_state in TERMINAL_DEAL_STATES and (
        not event.contract_state_reconciled
        or event.observed_contract_state != next_state.value
    ):
        await _persist_event(
            session, event, status="pending", reason_code="terminal_state_not_reconciled",
            deal_id=deal.id, existing=existing,
        )
        return "pending"

    if event.event_type is EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED:
        # Provider adapter must confirm accepted oracle evidence and reconciled
        # contract state; raw NFT transfer evidence cannot reach this branch.
        if (
            event.observed_contract_state != next_state.value
            or not event.attestation_accepted
            or not event.contract_state_reconciled
        ):
            await _persist_event(session, event, status="manual_review",
                reason_code="oracle_state_not_reconciled", deal_id=deal.id, existing=existing)
            deal.status = EscrowDealStatus.MANUAL_REVIEW.value
            return "rejected"

    event_row = await _persist_event(
        session, event, status="applied", reason_code=None,
        deal_id=deal.id, existing=existing,
    )
    deal.status = next_state.value
    deal.last_chain_seqno = max(deal.last_chain_seqno or 0, event.masterchain_seqno)
    if event.logical_time is not None:
        deal.last_chain_logical_time = max(deal.last_chain_logical_time or 0, event.logical_time)
    if next_state in TERMINAL_DEAL_STATES:
        if not await _reconcile_terminal_listing(session, deal, next_state, event):
            event_row.reason_code = "terminal_listing_owner_unverified"
            # Do not advance the durable scan cursor: the same terminal evidence
            # must be rechecked until current NFT owner is cryptographically proven.
            return "pending"
    return "applied"


async def _persist_getter_snapshot(
    session_factory: SessionFactory,
    event: NormalizedChainEvent,
    proof: FinalityVerification,
) -> None:
    """Persist only getter-equivalent state tied to this verified masterchain proof."""

    snapshot = proof.getter_snapshot_json
    if snapshot is None:
        return
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if (
        digest != proof.getter_snapshot_sha256
        or proof.getter_snapshot_masterchain_seqno != proof.masterchain_seqno
        or proof.getter_snapshot_block_hash != proof.masterchain_block_hash
        or proof.getter_snapshot_provider != proof.provider_id
    ):
        raise EscrowProviderInvalidEvidence(
            "Getter snapshot is not bound to the event finality proof"
        )
    if not event.deal_id:
        raise EscrowProviderInvalidEvidence("Verified getter snapshot has no deal identity")
    try:
        deal_id = uuid.UUID(event.deal_id)
    except (ValueError, TypeError) as exc:
        raise EscrowProviderInvalidEvidence(
            "Verified getter snapshot has an invalid deal identity"
        ) from exc

    async with session_factory() as session:
        async with session.begin():
            deal = await session.scalar(
                select(EscrowDeal).where(EscrowDeal.id == deal_id).with_for_update()
            )
            if deal is None:
                raise EscrowProviderInvalidEvidence(
                    "Verified getter snapshot references an unknown deal"
                )
            current_seqno = deal.getter_snapshot_masterchain_seqno
            if current_seqno is not None and proof.masterchain_seqno < current_seqno:
                # Old events may be replayed while a newer authoritative snapshot is
                # already stored; never overwrite current state with historical data.
                return
            if current_seqno == proof.masterchain_seqno:
                if (
                    deal.getter_snapshot_sha256 != digest
                    or deal.getter_snapshot_block_hash != proof.masterchain_block_hash
                ):
                    raise EscrowProviderInvalidEvidence(
                        "Getter snapshot conflicts at an already-recorded masterchain sequence"
                    )
                return
            deal.getter_snapshot_json = snapshot
            deal.getter_snapshot_sha256 = digest
            deal.getter_snapshot_masterchain_seqno = proof.masterchain_seqno
            deal.getter_snapshot_block_hash = proof.masterchain_block_hash
            deal.getter_snapshot_provider = proof.provider_id
            deal.getter_snapshot_observed_at = datetime.now(UTC)


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
            # A boolean/indexer "finalized" flag is insufficient. The provider
            # must return a proof bound to this transaction, message, trace and
            # masterchain sequence number.
            if event.network != "testnet":
                verified_events.append((event, False))
                continue
            proof = await provider.verify_event(event)
            if isinstance(proof, FinalityVerification) and proof.matches(event):
                await _persist_getter_snapshot(session_factory, event, proof)
                event = replace(
                    event,
                    event_type=proof.verified_event_type or event.event_type,
                    source_address=(
                        proof.source_address
                        if proof.verified_event_type is not None
                        else event.source_address
                    ),
                    destination_address=(
                        proof.destination_address
                        if proof.verified_event_type is not None
                        else event.destination_address
                    ),
                    item_address=(
                        proof.item_address if proof.verified_event_type is not None
                        else event.item_address
                    ),
                    collection_address=(
                        proof.collection_address if proof.verified_event_type is not None
                        else event.collection_address
                    ),
                    amount_nanotons=(
                        proof.amount_nanotons if proof.verified_event_type is not None
                        else event.amount_nanotons
                    ),
                    observed_contract_state=(
                        proof.observed_contract_state
                        if proof.verified_event_type is not None
                        else event.observed_contract_state
                    ),
                    # A verified False is meaningful. Do not OR with untrusted
                    # indexer values or a legacy event's persisted booleans.
                    attestation_accepted=(
                        proof.attestation_accepted
                        if proof.verified_event_type is not None
                        else event.attestation_accepted
                    ),
                    contract_state_reconciled=(
                        proof.contract_state_reconciled
                        if proof.verified_event_type is not None
                        else event.contract_state_reconciled
                    ),
                    masterchain_block_hash=proof.masterchain_block_hash,
                    finality_proof_sha256=proof.proof_sha256,
                    finality_provider=proof.provider_id,
                )
                event = await _terminal_owner_evidence(session_factory, provider, event)
                verified_events.append((event, True))
            else:
                verified_events.append((event, False))
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
                processed_events: list[tuple[NormalizedChainEvent, bool]] = []
                for event, verified in verified_events:
                    applied_result = await _apply_one_event(session, event,
                        provider_verified=verified)
                    result_counts[applied_result] += 1
                    processed_events.append((event, verified))
                    if applied_result in {"pending", "unmatched"}:
                        cursor_safe = False
                        # Later messages may depend on this one. Leave them on the
                        # same page and replay them after the earlier event is final.
                        break
                # A pending/non-final/unmatched event pins the cursor at the batch
                # start. The same page is rescanned until it can be promoted safely.
                if batch.next_cursor is not None and cursor_safe:
                    checkpoint.cursor = batch.next_cursor
                if cursor_safe and processed_events:
                    latest_seqno = max(
                        (
                            event.masterchain_seqno
                            for event, verified in processed_events
                            if verified and event.finalized
                        ),
                        default=None,
                    )
                    if latest_seqno is not None:
                        checkpoint.last_masterchain_seqno = max(
                            checkpoint.last_masterchain_seqno or 0, latest_seqno
                        )
                checkpoint.lease_token = None
                checkpoint.lease_until = None
                checkpoint.next_scan_at = current_time + (
                    timedelta(seconds=10) if not cursor_safe else timedelta(0)
                )
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
