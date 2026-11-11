"""Leased, fail-closed observer for persisted TON NFT delivery attempts.

The observer performs provider I/O outside database transactions. A verified
result is applied only after the lease token, order, listing, asset and immutable
delivery snapshot are revalidated under locks. Provider/indexer ambiguity never
releases a listing or marks an order completed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.delivery import (
    DeliveryEvidenceResult,
    DeliveryEvidenceStatus,
    TEP62TransferIntent,
    TONCenterDeliveryConfig,
    TONCenterDeliveryEvidenceProvider,
)
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable
from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    Order,
    OrderDeliveryAttempt,
    OrderDeliveryAttemptStatus,
    OrderEvent,
    OrderStatus,
)

logger = logging.getLogger(__name__)


class DeliveryEvidenceProvider(Protocol):
    async def verify_transfer(
        self, intent: TEP62TransferIntent
    ) -> DeliveryEvidenceResult: ...

    async def aclose(self) -> None: ...


ProviderFactory = Callable[[str], DeliveryEvidenceProvider]


@dataclass(frozen=True, slots=True)
class DeliveryObservationClaim:
    attempt_id: uuid.UUID
    order_id: uuid.UUID
    listing_id: uuid.UUID
    asset_id: uuid.UUID
    seller_id: uuid.UUID
    buyer_id: uuid.UUID
    network: str
    item_address: str
    seller_address: str
    buyer_address: str
    query_id: int
    candidate_transaction_hash: str | None
    deadline: datetime
    lease_until: datetime
    lease_token: uuid.UUID
    observer_attempt_count: int


@dataclass(frozen=True, slots=True)
class DeliveryObserverPassResult:
    claimed: int = 0
    verified: int = 0
    retried: int = 0
    manual_review: int = 0
    lease_lost: int = 0


def _build_provider(network: str) -> TONCenterDeliveryEvidenceProvider:
    settings = get_settings()
    if network == "mainnet":
        base_url = settings.ton_center_mainnet_base_url
    elif network == "testnet":
        base_url = settings.ton_center_testnet_base_url
    else:
        raise ValueError("Unsupported TON delivery network")
    api_key = (
        settings.ton_center_api_key.get_secret_value()
        if settings.ton_center_api_key is not None
        else None
    )
    return TONCenterDeliveryEvidenceProvider(
        TONCenterDeliveryConfig(
            base_url=base_url,
            network=network,
            api_key=api_key,
            timeout_seconds=settings.ton_center_timeout_seconds,
        )
    )


async def claim_due_delivery_attempts(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[DeliveryObservationClaim]:
    """Claim a bounded batch with SKIP LOCKED and a reclaimable per-attempt lease.

    Lock order is listing -> asset -> order -> attempt, matching cancellation,
    expiry and finalization paths. Candidate discovery itself is unlocked; each
    candidate is re-read and revalidated after the ordered locks are acquired.
    """

    settings = get_settings()
    current_time = now or datetime.now(UTC)
    batch_limit = limit or settings.delivery_observer_batch_size
    if batch_limit < 1:
        raise ValueError("Delivery observer batch size must be positive")
    concurrency = settings.delivery_observer_concurrency
    provider_waves = (batch_limit + concurrency - 1) // concurrency
    # TON Center may need up to five transfer pages plus one trace request.
    # Ensure the lease covers bounded provider timeouts for every wave.
    lease_seconds = max(
        settings.delivery_observer_lease_seconds,
        int(settings.ton_center_timeout_seconds * 6 * provider_waves) + 30,
    )

    claims: list[DeliveryObservationClaim] = []
    async with session.begin():
        candidates = (
            await session.execute(
                select(
                    OrderDeliveryAttempt.id,
                    Order.id,
                    Order.listing_id,
                    Listing.asset_id,
                )
                .join(Order, Order.id == OrderDeliveryAttempt.order_id)
                .join(Listing, Listing.id == Order.listing_id)
                .where(
                    OrderDeliveryAttempt.status.in_(
                        (
                            OrderDeliveryAttemptStatus.PREPARED,
                            OrderDeliveryAttemptStatus.OBSERVING,
                        )
                    ),
                    Order.status.in_(
                        (OrderStatus.AWAITING_TRANSFER, OrderStatus.OBSERVING_TRANSFER)
                    ),
                    or_(
                        OrderDeliveryAttempt.next_check_at.is_(None),
                        OrderDeliveryAttempt.next_check_at <= current_time,
                    ),
                    or_(
                        OrderDeliveryAttempt.observer_lease_until.is_(None),
                        OrderDeliveryAttempt.observer_lease_until <= current_time,
                    ),
                )
                .order_by(
                    OrderDeliveryAttempt.next_check_at.asc().nullsfirst(),
                    OrderDeliveryAttempt.created_at.asc(),
                    OrderDeliveryAttempt.id.asc(),
                )
                .limit(batch_limit * 4)
            )
        ).all()

        for attempt_id, order_id, listing_id, asset_id in candidates:
            # Match the marketplace lock order. SKIP LOCKED keeps concurrent
            # observers from waiting behind cancellation/finalization work.
            listing = await session.scalar(
                select(Listing)
                .where(Listing.id == listing_id)
                .with_for_update(skip_locked=True)
            )
            if listing is None:
                continue
            asset = await session.scalar(
                select(NFTAsset)
                .where(NFTAsset.id == asset_id)
                .with_for_update(skip_locked=True)
            )
            if asset is None:
                continue
            order = await session.scalar(
                select(Order)
                .where(Order.id == order_id)
                .with_for_update(skip_locked=True)
            )
            if (
                order is None
                or order.listing_id != listing.id
                or listing.asset_id != asset.id
                or order.status
                not in (OrderStatus.AWAITING_TRANSFER, OrderStatus.OBSERVING_TRANSFER)
            ):
                continue
            attempt = await session.scalar(
                select(OrderDeliveryAttempt)
                .where(
                    OrderDeliveryAttempt.id == attempt_id,
                    OrderDeliveryAttempt.order_id == order.id,
                )
                .with_for_update(skip_locked=True)
            )
            if (
                attempt is None
                or attempt.status
                not in (
                    OrderDeliveryAttemptStatus.PREPARED,
                    OrderDeliveryAttemptStatus.OBSERVING,
                )
                or (
                    attempt.next_check_at is not None
                    and attempt.next_check_at > current_time
                )
                or (
                    attempt.observer_lease_until is not None
                    and attempt.observer_lease_until > current_time
                )
            ):
                continue

            lease_token = uuid.uuid4()
            lease_until = current_time + timedelta(seconds=lease_seconds)
            previous_order_status = order.status
            attempt.status = OrderDeliveryAttemptStatus.OBSERVING
            attempt.observer_attempt_count += 1
            attempt.observer_lease_token = lease_token
            attempt.observer_lease_until = lease_until
            # next_check_at doubles as the due time and is advanced to the lease
            # expiry while claimed. A crash therefore makes the row reclaimable.
            attempt.next_check_at = lease_until
            if previous_order_status is OrderStatus.AWAITING_TRANSFER:
                order.status = OrderStatus.OBSERVING_TRANSFER
                session.add(
                    OrderEvent(
                        order_id=order.id,
                        from_status=previous_order_status,
                        to_status=OrderStatus.OBSERVING_TRANSFER,
                        actor_id=None,
                        actor_type="system",
                    )
                )
            claims.append(
                DeliveryObservationClaim(
                    attempt_id=attempt.id,
                    order_id=order.id,
                    listing_id=listing.id,
                    asset_id=asset.id,
                    seller_id=order.seller_id,
                    buyer_id=order.buyer_id,
                    network=attempt.network,
                    item_address=attempt.item_address,
                    seller_address=attempt.seller_address_snapshot,
                    buyer_address=attempt.buyer_address_snapshot,
                    query_id=int(attempt.query_id),
                    candidate_transaction_hash=attempt.candidate_transaction_hash,
                    deadline=attempt.deadline,
                    lease_until=lease_until,
                    lease_token=lease_token,
                    observer_attempt_count=attempt.observer_attempt_count,
                )
            )
            if len(claims) >= batch_limit:
                break
    return claims

async def _mark_manual_review(
    session: AsyncSession,
    claim: DeliveryObservationClaim,
    *,
    now: datetime,
    reason_code: str,
) -> bool:
    async with session.begin():
        attempt = await session.scalar(
            select(OrderDeliveryAttempt)
            .where(
                OrderDeliveryAttempt.id == claim.attempt_id,
                OrderDeliveryAttempt.observer_lease_token == claim.lease_token,
                OrderDeliveryAttempt.status == OrderDeliveryAttemptStatus.OBSERVING,
            )
            .with_for_update()
        )
        if attempt is None:
            return False
        attempt.status = OrderDeliveryAttemptStatus.MANUAL_REVIEW
        attempt.reason_code = reason_code[:64]
        attempt.last_checked_at = now
        attempt.next_check_at = None
        attempt.observer_lease_token = None
        attempt.observer_lease_until = None
    return True


async def _schedule_retry(
    session: AsyncSession,
    claim: DeliveryObservationClaim,
    *,
    now: datetime,
    reason_code: str,
) -> str:
    settings = get_settings()
    async with session.begin():
        attempt = await session.scalar(
            select(OrderDeliveryAttempt)
            .where(
                OrderDeliveryAttempt.id == claim.attempt_id,
                OrderDeliveryAttempt.observer_lease_token == claim.lease_token,
                OrderDeliveryAttempt.status == OrderDeliveryAttemptStatus.OBSERVING,
            )
            .with_for_update()
        )
        if attempt is None:
            return "lease_lost"

        attempt.last_checked_at = now
        attempt.reason_code = reason_code[:64]
        attempt.observer_lease_token = None
        attempt.observer_lease_until = None
        if now >= attempt.deadline or (
            attempt.observer_attempt_count >= settings.delivery_observer_max_attempts
        ):
            attempt.status = OrderDeliveryAttemptStatus.MANUAL_REVIEW
            attempt.next_check_at = None
            return "manual_review"

        exponent = min(max(attempt.observer_attempt_count - 1, 0), 30)
        delay = min(
            settings.delivery_observer_retry_base_seconds * (2**exponent),
            settings.delivery_observer_retry_max_seconds,
        )
        attempt.status = OrderDeliveryAttemptStatus.OBSERVING
        attempt.next_check_at = now + timedelta(seconds=delay)
        return "retried"


async def _apply_verified_evidence(
    session: AsyncSession,
    claim: DeliveryObservationClaim,
    evidence: DeliveryEvidenceResult,
    *,
    now: datetime,
) -> str:
    """Apply exact finalized evidence atomically, or quarantine a changed snapshot."""

    async with session.begin():
        # Match the marketplace's established lock order: listing -> asset ->
        # order. The attempt is locked last and its lease token is revalidated.
        listing = await session.scalar(
            select(Listing).where(Listing.id == claim.listing_id).with_for_update()
        )
        asset = await session.scalar(
            select(NFTAsset).where(NFTAsset.id == claim.asset_id).with_for_update()
        )
        order = await session.scalar(
            select(Order).where(Order.id == claim.order_id).with_for_update()
        )
        attempt = await session.scalar(
            select(OrderDeliveryAttempt)
            .where(OrderDeliveryAttempt.id == claim.attempt_id)
            .with_for_update()
        )
        if (
            attempt is None
            or attempt.observer_lease_token != claim.lease_token
            or attempt.status is not OrderDeliveryAttemptStatus.OBSERVING
        ):
            return "lease_lost"

        try:
            evidence_matches = (
                normalize_address(evidence.item_address)
                == normalize_address(attempt.item_address)
                == normalize_address(claim.item_address)
                and normalize_address(evidence.seller_wallet_address)
                == normalize_address(attempt.seller_address_snapshot)
                == normalize_address(claim.seller_address)
                and normalize_address(evidence.buyer_wallet_address)
                == normalize_address(attempt.buyer_address_snapshot)
                == normalize_address(claim.buyer_address)
            )
        except AddressError:
            evidence_matches = False

        evidence_matches = evidence_matches and (
            evidence.network == attempt.network == claim.network
            and evidence.query_id == int(attempt.query_id) == claim.query_id
            and evidence.status is DeliveryEvidenceStatus.VERIFIED_FINALIZED
            and bool(evidence.transaction_hash)
            and bool(evidence.trace_id)
            and evidence.masterchain_seqno is not None
            and evidence.masterchain_seqno > 0
        )
        try:
            asset_item_matches = (
                asset is not None
                and asset.item_address is not None
                and normalize_address(asset.item_address)
                == normalize_address(claim.item_address)
            )
        except AddressError:
            asset_item_matches = False

        state_matches = (
            listing is not None
            and asset is not None
            and order is not None
            and order.listing_id == listing.id
            and listing.asset_id == asset.id
            and order.seller_id == claim.seller_id
            and order.buyer_id == claim.buyer_id
            and order.status
            in (OrderStatus.AWAITING_TRANSFER, OrderStatus.OBSERVING_TRANSFER)
            and listing.status is ListingStatus.RESERVED
            and asset.asset_type is AssetType.TON_NFT
            and asset.network == claim.network
            and asset_item_matches
            and asset.owner_id == order.seller_id
            and listing.seller_id == order.seller_id
            and asset.verification_status is AssetVerificationStatus.VERIFIED
        )
        if not evidence_matches or not state_matches:
            attempt.status = OrderDeliveryAttemptStatus.MANUAL_REVIEW
            attempt.reason_code = (
                "evidence_mismatch" if not evidence_matches else "state_changed"
            )
            attempt.last_checked_at = now
            attempt.next_check_at = None
            attempt.observer_lease_token = None
            attempt.observer_lease_until = None
            return "manual_review"

        duplicate = await session.scalar(
            select(OrderDeliveryAttempt.id).where(
                OrderDeliveryAttempt.id != attempt.id,
                OrderDeliveryAttempt.status == OrderDeliveryAttemptStatus.VERIFIED,
                OrderDeliveryAttempt.network == attempt.network,
                OrderDeliveryAttempt.item_address == attempt.item_address,
                OrderDeliveryAttempt.transaction_hash == evidence.transaction_hash,
            )
        )
        if duplicate is not None:
            attempt.status = OrderDeliveryAttemptStatus.MANUAL_REVIEW
            attempt.reason_code = "transfer_already_used"
            attempt.last_checked_at = now
            attempt.next_check_at = None
            attempt.observer_lease_token = None
            attempt.observer_lease_until = None
            return "manual_review"

        previous_status = order.status
        attempt.status = OrderDeliveryAttemptStatus.VERIFIED
        attempt.transaction_hash = evidence.transaction_hash
        attempt.trace_id = evidence.trace_id
        attempt.masterchain_seqno = evidence.masterchain_seqno
        attempt.provider_source = evidence.evidence_source[:32]
        attempt.reason_code = "finalized_transfer_verified"
        attempt.verified_at = now
        attempt.last_checked_at = now
        attempt.next_check_at = None
        attempt.observer_lease_token = None
        attempt.observer_lease_until = None

        order.status = OrderStatus.COMPLETED
        listing.status = ListingStatus.SOLD
        asset.owner_id = order.buyer_id
        asset.verification_status = AssetVerificationStatus.VERIFIED
        asset.verified_at = now
        session.add(
            OrderEvent(
                order_id=order.id,
                from_status=previous_status,
                to_status=OrderStatus.COMPLETED,
                actor_id=None,
                actor_type="system",
            )
        )
    return "verified"


async def apply_delivery_observation(
    session: AsyncSession,
    claim: DeliveryObservationClaim,
    evidence: DeliveryEvidenceResult,
    *,
    now: datetime | None = None,
) -> str:
    """Persist a provider result only while the claim lease is still owned."""

    current_time = now or datetime.now(UTC)
    if evidence.status is DeliveryEvidenceStatus.VERIFIED_FINALIZED:
        return await _apply_verified_evidence(
            session, claim, evidence, now=current_time
        )
    if evidence.status is DeliveryEvidenceStatus.FAILED:
        return (
            "manual_review"
            if await _mark_manual_review(
                session,
                claim,
                now=current_time,
                reason_code="transfer_mismatch_or_failed",
            )
            else "lease_lost"
        )
    reason = (
        "transfer_not_found"
        if evidence.status is DeliveryEvidenceStatus.NOT_FOUND
        else "evidence_inconclusive"
    )
    return await _schedule_retry(
        session, claim, now=current_time, reason_code=reason
    )


async def run_delivery_observer_pass(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    provider_factory: ProviderFactory | None = None,
) -> DeliveryObserverPassResult:
    """Claim work, query TON Center outside DB locks, then apply each result."""

    current_time = now or datetime.now(UTC)
    async with session_factory() as session:
        claims = await claim_due_delivery_attempts(session, now=current_time)

    settings = get_settings()
    semaphore = asyncio.Semaphore(settings.delivery_observer_concurrency)
    make_provider = provider_factory or _build_provider

    async def process_claim(claim: DeliveryObservationClaim) -> str:
        async with semaphore:
            provider: DeliveryEvidenceProvider | None = None
            try:
                provider = make_provider(claim.network)
                evidence = await provider.verify_transfer(
                    TEP62TransferIntent(
                        item_address=claim.item_address,
                        network=claim.network,
                        seller_wallet_address=claim.seller_address,
                        buyer_wallet_address=claim.buyer_address,
                        query_id=claim.query_id,
                        candidate_transaction_hash=claim.candidate_transaction_hash,
                    )
                )
                async with session_factory() as session:
                    return await apply_delivery_observation(
                        session, claim, evidence, now=current_time
                    )
            except (ProviderUnavailable, InvalidProviderData):
                logger.warning(
                    "Delivery evidence provider returned an unavailable or invalid response "
                    "for attempt %s",
                    claim.attempt_id,
                    exc_info=True,
                )
                async with session_factory() as session:
                    return await _schedule_retry(
                        session,
                        claim,
                        now=current_time,
                        reason_code="provider_unavailable_or_invalid",
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Unexpected delivery observer failure for attempt %s",
                    claim.attempt_id,
                )
                try:
                    async with session_factory() as session:
                        return await _schedule_retry(
                            session,
                            claim,
                            now=current_time,
                            reason_code="observer_internal_error",
                        )
                except Exception:
                    logger.exception(
                        "Could not persist observer retry for attempt %s; lease will expire",
                        claim.attempt_id,
                    )
                    return "lease_lost"
            finally:
                if provider is not None:
                    try:
                        await provider.aclose()
                    except Exception:
                        logger.warning(
                            "Could not close delivery evidence provider for attempt %s",
                            claim.attempt_id,
                            exc_info=True,
                        )

    outcomes = await asyncio.gather(*(process_claim(claim) for claim in claims))
    return DeliveryObserverPassResult(
        claimed=len(claims),
        verified=outcomes.count("verified"),
        retried=outcomes.count("retried"),
        manual_review=outcomes.count("manual_review"),
        lease_lost=outcomes.count("lease_lost"),
    )
