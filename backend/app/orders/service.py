from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.models import VerificationResult, VerificationStatus
from app.assets.ton_nft.verifier import TONNFTVerifier
from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    Order,
    OrderEvent,
    OrderStatus,
    TelegramNotificationOutbox,
    User,
    Wallet,
)


class OrderConflict(Exception):
    """The listing or idempotency key cannot be used for this order."""


class OrderVerificationUnavailable(Exception):
    """The external ownership provider could not confirm current NFT ownership.

    Raised for provider outages only. An outage is not evidence that ownership
    was lost, so no asset or listing state is changed when this is raised.
    """


@dataclass(frozen=True, slots=True)
class _ReservationSnapshot:
    """Server-side identity of a listing captured before the provider call."""

    listing_id: uuid.UUID
    asset_id: uuid.UUID
    seller_id: uuid.UUID
    external_id: str
    item_address: str
    network: str
    wallets: tuple[tuple[uuid.UUID, str], ...]


@dataclass(frozen=True, slots=True)
class _OwnershipCheck:
    """Outcome of the fresh owner check.

    `wallet_id` is set only when a verified seller wallet was confirmed as the
    current on-chain owner. When it is `None` the check is inconclusive, and
    `ownership_lost` records whether the provider affirmatively reported a
    different owner (as opposed to returning no usable answer).
    """

    wallet_id: uuid.UUID | None
    wallet_address: str | None
    ownership_lost: bool

    @property
    def is_confirmed(self) -> bool:
        return self.wallet_id is not None and not self.ownership_lost


async def _enqueue_order_notifications(
    session: AsyncSession,
    *,
    order: Order,
    event_type: str,
    recipients: dict[uuid.UUID, str],
) -> None:
    if not recipients:
        return
    users = (
        await session.scalars(
            select(User).where(User.id.in_(tuple(recipients.keys())))
        )
    ).all()
    for recipient in users:
        session.add(
            TelegramNotificationOutbox(
                dedupe_key=f"order:{order.id}:{event_type}:{recipient.id}",
                order_id=order.id,
                recipient_user_id=recipient.id,
                recipient_telegram_id=recipient.telegram_id,
                recipient_role=recipients[recipient.id],
                event_type=event_type,
            )
        )


async def _load_reservation_snapshot(
    session: AsyncSession,
    *,
    buyer_id: uuid.UUID,
    listing_id: uuid.UUID,
    idempotency_key: str,
    now: datetime,
) -> tuple[uuid.UUID | None, _ReservationSnapshot | None]:
    """Read the server-side reservation candidate without holding locks.

    Returns an existing order id for an idempotent retry, otherwise a snapshot of
    the primitives needed for verification. Nothing here trusts client input
    beyond the listing id and the idempotency key.
    """

    existing = await session.scalar(
        select(Order).where(
            Order.buyer_id == buyer_id,
            Order.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.listing_id != listing_id:
            raise OrderConflict("Idempotency key was already used for another listing")
        return existing.id, None

    listing = await session.scalar(select(Listing).where(Listing.id == listing_id))
    if listing is None:
        raise OrderConflict("Listing is not available")
    if listing.seller_id == buyer_id:
        raise OrderConflict("You cannot order your own listing")
    if listing.status is not ListingStatus.ACTIVE:
        raise OrderConflict("Listing is not available")
    if listing.expires_at is not None and listing.expires_at <= now:
        raise OrderConflict("Listing is not available")

    asset = await session.scalar(select(NFTAsset).where(NFTAsset.id == listing.asset_id))
    if (
        asset is None
        or asset.owner_id != listing.seller_id
        or asset.asset_type is not AssetType.TON_NFT
        or not asset.item_address
        or asset.verification_status != AssetVerificationStatus.VERIFIED
    ):
        raise OrderConflict("Listing is not available")

    wallet_rows = (
        await session.scalars(
            select(Wallet)
            .where(
                Wallet.user_id == listing.seller_id,
                Wallet.is_verified.is_(True),
                Wallet.network == asset.network,
            )
            .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
        )
    ).all()
    if not wallet_rows:
        raise OrderConflict("Listing is not available")

    return None, _ReservationSnapshot(
        listing_id=listing.id,
        asset_id=asset.id,
        seller_id=listing.seller_id,
        external_id=asset.external_id,
        item_address=asset.item_address,
        network=asset.network,
        wallets=tuple((wallet.id, wallet.address) for wallet in wallet_rows),
    )


async def _verify_current_ownership(
    snapshot: _ReservationSnapshot,
    verifier: TONNFTVerifier,
) -> _OwnershipCheck:
    """Run the TEP-62 owner check for every verified seller wallet.

    No database transaction or row lock is held while these provider calls run.
    A provider outage raises `OrderVerificationUnavailable`; it is never treated
    as proof that ownership was lost.
    """

    ownership_lost = False
    for wallet_id, wallet_address in snapshot.wallets:
        result: VerificationResult = await verifier.verify(
            snapshot.item_address, wallet_address
        )
        if result.status is VerificationStatus.PROVIDER_UNAVAILABLE:
            raise OrderVerificationUnavailable(
                "TON NFT ownership provider is temporarily unavailable"
            )
        if result.status is VerificationStatus.OWNER_MISMATCH:
            ownership_lost = True
            continue
        if not result.is_verified:
            continue
        try:
            verified_item = normalize_address(result.item_address)
            verified_owner = normalize_address(result.owner_address or "")
            expected_owner = normalize_address(result.expected_owner_address or "")
            normalized_item = normalize_address(snapshot.item_address)
            normalized_wallet = normalize_address(wallet_address)
        except AddressError:
            continue
        if (
            verified_item == normalized_item
            and verified_owner == normalized_wallet
            and expected_owner == normalized_wallet
        ):
            return _OwnershipCheck(
                wallet_id=wallet_id,
                wallet_address=wallet_address,
                ownership_lost=False,
            )

    # No wallet could prove ownership. This is inconclusive rather than a proven
    # transfer, but it must never be treated as a confirmed owner.
    return _OwnershipCheck(
        wallet_id=None,
        wallet_address=None,
        ownership_lost=ownership_lost,
    )


async def create_order(
    session: AsyncSession,
    *,
    buyer_id: uuid.UUID,
    listing_id: uuid.UUID,
    idempotency_key: str,
    verifier: TONNFTVerifier | None = None,
    now: datetime | None = None,
) -> uuid.UUID:
    """Reserve an ACTIVE listing after a fresh TEP-62 ownership re-check.

    Persisted `owner_id` and `verification_status` can be stale after an on-chain
    transfer, so a reservation additionally requires the seller's verified wallet
    to still own the NFT. The provider call runs outside any transaction; the
    final transition re-reads and revalidates everything under row locks.
    """

    current_time = now or datetime.now(UTC)

    existing_order_id, snapshot = await _load_reservation_snapshot(
        session,
        buyer_id=buyer_id,
        listing_id=listing_id,
        idempotency_key=idempotency_key,
        now=current_time,
    )
    if existing_order_id is not None:
        return existing_order_id
    if snapshot is None:  # pragma: no cover - guarded by the snapshot helper
        raise OrderConflict("Listing is not available")

    if verifier is None:
        raise OrderVerificationUnavailable("A TON NFT ownership verifier is required")

    # The snapshot read autobegins a transaction. Release it before the provider
    # call so no connection or row lock is held while the network is queried.
    await session.rollback()

    ownership = await _verify_current_ownership(snapshot, verifier)

    await session.rollback()

    return await _reserve_listing(
        session,
        buyer_id=buyer_id,
        idempotency_key=idempotency_key,
        snapshot=snapshot,
        ownership=ownership,
        current_time=current_time,
    )


async def _reserve_listing(
    session: AsyncSession,
    *,
    buyer_id: uuid.UUID,
    idempotency_key: str,
    snapshot: _ReservationSnapshot,
    ownership: _OwnershipCheck,
    current_time: datetime,
) -> uuid.UUID:
    """Lock, revalidate against the snapshot, then reserve atomically."""

    async with session.begin():
        await session.scalar(select(User.id).where(User.id == buyer_id).with_for_update())

        existing = await session.scalar(
            select(Order).where(
                Order.buyer_id == buyer_id,
                Order.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.listing_id != snapshot.listing_id:
                raise OrderConflict("Idempotency key was already used for another listing")
            return existing.id

        listing = await session.scalar(
            select(Listing).where(Listing.id == snapshot.listing_id).with_for_update()
        )
        if listing is None:
            raise OrderConflict("Listing is not available")

        asset = await session.scalar(
            select(NFTAsset)
            .where(NFTAsset.id == snapshot.asset_id)
            .with_for_update()
        )

        identity_changed = (
            listing.seller_id != snapshot.seller_id
            or listing.asset_id != snapshot.asset_id
            or asset is None
            or asset.owner_id != snapshot.seller_id
            or asset.external_id != snapshot.external_id
            or asset.item_address != snapshot.item_address
            or asset.network != snapshot.network
        )
        if identity_changed:
            raise OrderConflict(
                "Listing changed while ownership was being verified; try again"
            )

        if ownership.is_confirmed:
            locked_wallet = await session.scalar(
                select(Wallet)
                .where(Wallet.id == ownership.wallet_id)
                .with_for_update()
            )
            ownership_still_bound = (
                locked_wallet is not None
                and locked_wallet.user_id == snapshot.seller_id
                and locked_wallet.is_verified
                and locked_wallet.network == snapshot.network
                and locked_wallet.address == ownership.wallet_address
            )
        else:
            ownership_still_bound = False

        if ownership.is_confirmed and not ownership_still_bound:
            # The proof was valid a moment ago; the wallet binding changed
            # underneath us. Nothing is proven now, so reject without mutating.
            raise OrderConflict(
                "The verified seller wallet changed during ownership verification"
            )

        if not ownership_still_bound and not ownership.ownership_lost:
            # Inconclusive: the provider never confirmed the seller as owner and
            # never reported a different owner (for example the item was not
            # found). Fail closed without marking the asset as transferred.
            rejection = (
                "NFT ownership could not be freshly verified; the listing is unavailable"
            )
        elif not ownership_still_bound:
            # Current ownership is gone. Fail closed and record the asset as stale
            # under the locks we already hold; the listing cannot stay purchasable.
            # The transition is committed before the caller sees the conflict.
            asset.verification_status = AssetVerificationStatus.STALE
            if listing.status is ListingStatus.ACTIVE:
                listing.status = ListingStatus.EXPIRED
            await session.flush()
            rejection = (
                "NFT ownership could not be freshly verified; the listing is unavailable"
            )
        elif listing.status is not ListingStatus.ACTIVE:
            rejection = "Listing is not available"
        elif listing.expires_at is not None and listing.expires_at <= current_time:
            listing.status = ListingStatus.EXPIRED
            await session.flush()
            rejection = "Listing is not available"
        elif listing.seller_id == buyer_id:
            rejection = "You cannot order your own listing"
        elif (
            asset.asset_type is not AssetType.TON_NFT
            or asset.verification_status != AssetVerificationStatus.VERIFIED
        ):
            rejection = "Listing is not available"
        else:
            rejection = None

        if rejection is None:
            order = Order(
                listing_id=listing.id,
                buyer_id=buyer_id,
                seller_id=listing.seller_id,
                idempotency_key=idempotency_key,
                status=OrderStatus.PENDING_PAYMENT,
                price_amount=Decimal(listing.price_amount),
                price_currency=listing.price_currency,
                expires_at=current_time
                + timedelta(seconds=get_settings().order_pending_ttl_seconds),
            )
            listing.status = ListingStatus.RESERVED
            session.add(order)
            await session.flush()
            session.add(
                OrderEvent(
                    order_id=order.id,
                    from_status=None,
                    to_status=OrderStatus.PENDING_PAYMENT,
                    actor_id=buyer_id,
                    actor_type="buyer",
                )
            )
            await _enqueue_order_notifications(
                session,
                order=order,
                event_type="order_created",
                recipients={buyer_id: "buyer", listing.seller_id: "seller"},
            )
            order_id = order.id

    if rejection is not None:
        raise OrderConflict(rejection)

    return order_id


async def cancel_order(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    buyer_id: uuid.UUID,
    now: datetime | None = None,
) -> uuid.UUID:
    current_time = now or datetime.now(UTC)

    async with session.begin():
        listing_id = await session.scalar(
            select(Order.listing_id).where(
                Order.id == order_id, Order.buyer_id == buyer_id
            )
        )
        if listing_id is None:
            raise OrderConflict("Order not found")
        listing = await session.scalar(
            select(Listing).where(Listing.id == listing_id).with_for_update()
        )
        order = await session.scalar(
            select(Order)
            .where(Order.id == order_id, Order.buyer_id == buyer_id)
            .with_for_update()
        )
        if order is None:
            raise OrderConflict("Order not found")
        if order.status != OrderStatus.PENDING_PAYMENT:
            return order.id

        if order.expires_at <= current_time or (
            listing is not None
            and listing.expires_at is not None
            and listing.expires_at <= current_time
        ):
            target_status = OrderStatus.EXPIRED
            actor_id = None
            actor_type = "system"
        else:
            target_status = OrderStatus.CANCELLED
            actor_id = buyer_id
            actor_type = "buyer"
        order.status = target_status
        session.add(
            OrderEvent(
                order_id=order.id,
                from_status=OrderStatus.PENDING_PAYMENT,
                to_status=target_status,
                actor_id=actor_id,
                actor_type=actor_type,
            )
        )
        await _enqueue_order_notifications(
            session,
            order=order,
            event_type=(
                "order_expired" if target_status == OrderStatus.EXPIRED else "order_cancelled"
            ),
            recipients={order.buyer_id: "buyer", order.seller_id: "seller"},
        )
        _release_listing(listing, current_time)
        return order.id


def _release_listing(listing: Listing | None, now: datetime) -> None:
    if listing is None or listing.status != ListingStatus.RESERVED:
        return
    if listing.expires_at is not None and listing.expires_at <= now:
        listing.status = ListingStatus.EXPIRED
    else:
        listing.status = ListingStatus.ACTIVE


async def expire_pending_orders(
    session: AsyncSession, *, now: datetime | None = None, limit: int = 100
) -> int:
    current_time = now or datetime.now(UTC)
    expired_count = 0

    async with session.begin():
        listing_ids = (
            await session.scalars(
                select(Order.listing_id)
                .join(Listing, Listing.id == Order.listing_id)
                .where(Order.status == OrderStatus.PENDING_PAYMENT)
                .where(
                    (Order.expires_at <= current_time)
                    | (
                        Listing.expires_at.is_not(None)
                        & (Listing.expires_at <= current_time)
                    )
                )
                .distinct()
                .limit(limit)
            )
        ).all()
        for listing_id in listing_ids:
            listing = await session.scalar(
                select(Listing)
                .where(Listing.id == listing_id)
                .with_for_update(skip_locked=True)
            )
            if listing is None:
                continue
            order = await session.scalar(
                select(Order)
                .where(
                    Order.listing_id == listing_id,
                    Order.status == OrderStatus.PENDING_PAYMENT,
                )
                .join(Listing, Listing.id == Order.listing_id)
                .where(
                    (Order.expires_at <= current_time)
                    | (
                        Listing.expires_at.is_not(None)
                        & (Listing.expires_at <= current_time)
                    )
                )
                .with_for_update()
            )
            if order is None:
                continue
            order.status = OrderStatus.EXPIRED
            _release_listing(listing, current_time)
            session.add(
                OrderEvent(
                    order_id=order.id,
                    from_status=OrderStatus.PENDING_PAYMENT,
                    to_status=OrderStatus.EXPIRED,
                    actor_id=None,
                    actor_type="system",
                )
            )
            await _enqueue_order_notifications(
                session,
                order=order,
                event_type="order_expired",
                recipients={order.buyer_id: "buyer", order.seller_id: "seller"},
            )
            expired_count += 1

    return expired_count


async def get_order(
    session: AsyncSession, *, order_id: uuid.UUID, user_id: uuid.UUID
) -> Order | None:
    order: Order | None = await session.scalar(
        select(Order)
        .options(
            selectinload(Order.listing).selectinload(Listing.asset),
            selectinload(Order.events),
        )
        .where(
            Order.id == order_id,
            (Order.buyer_id == user_id) | (Order.seller_id == user_id),
        )
    )
    return order


async def list_user_orders(
    session: AsyncSession, *, user_id: uuid.UUID, role: str, limit: int, offset: int
) -> list[Order]:
    user_column = Order.buyer_id if role == "buyer" else Order.seller_id
    result = await session.scalars(
        select(Order)
        .options(
            selectinload(Order.listing).selectinload(Listing.asset),
            selectinload(Order.events),
        )
        .where(user_column == user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)
