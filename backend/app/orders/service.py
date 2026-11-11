from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.delivery import normalize_transaction_hash
from app.assets.ton_nft.errors import InvalidProviderData
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
    OrderDeliveryAttempt,
    OrderDeliveryAttemptStatus,
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
class _DeliveryPreparationSnapshot:
    order_id: uuid.UUID
    listing_id: uuid.UUID
    asset_id: uuid.UUID
    seller_id: uuid.UUID
    buyer_id: uuid.UUID
    seller_wallet_id: uuid.UUID
    seller_address: str
    buyer_wallet_id: uuid.UUID
    buyer_address: str
    item_address: str
    network: str


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

    The asset's persisted network must match the network this verifier queries.
    If configuration changed while older assets remained in the database, a
    mismatch would silently ask the wrong indexer, so it fails closed instead.
    """

    verifier_network = getattr(verifier, "network", None)
    if verifier_network is not None and verifier_network != snapshot.network:
        raise OrderVerificationUnavailable(
            "The TON ownership provider is not configured for this asset's network"
        )

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

        # Fixed lock order shared with `publish_listing`:
        # listing -> wallet -> asset. Reservation used to take the asset before
        # the wallet, which could deadlock against a concurrent publication for
        # the same NFT (publication holds the wallet while waiting for the asset).
        listing = await session.scalar(
            select(Listing).where(Listing.id == snapshot.listing_id).with_for_update()
        )
        if listing is None:
            raise OrderConflict("Listing is not available")

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
            locked_wallet = None
            ownership_still_bound = False

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
            # Current ownership is gone. Fail closed and invalidate everything that
            # depends on it under the locks already held. The transition commits
            # before the caller sees the conflict, so it cannot be rolled back
            # with the failed request.
            await _invalidate_lost_ownership(
                session, listing=listing, asset=asset, current_time=current_time
            )
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
                status=OrderStatus.RESERVED,
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
                    to_status=OrderStatus.RESERVED,
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
        asset = (
            await session.scalar(
                select(NFTAsset)
                .where(NFTAsset.id == listing.asset_id)
                .with_for_update()
            )
            if listing is not None
            else None
        )
        order = await session.scalar(
            select(Order)
            .where(Order.id == order_id, Order.buyer_id == buyer_id)
            .with_for_update()
        )
        if order is None:
            raise OrderConflict("Order not found")
        if order.status in (
            OrderStatus.AWAITING_TRANSFER,
            OrderStatus.OBSERVING_TRANSFER,
        ):
            raise OrderConflict("Order cannot be cancelled after delivery preparation")
        if order.status != OrderStatus.RESERVED:
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
                from_status=OrderStatus.RESERVED,
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
        _release_listing(listing, current_time, asset)
        return order.id


async def _invalidate_lost_ownership(
    session: AsyncSession,
    *,
    listing: Listing,
    asset: NFTAsset,
    current_time: datetime,
) -> None:
    """Mark the asset stale and make every dependent order unobtainable.

    Ownership can be lost while a listing is ACTIVE *or* while another buyer has
    already RESERVED it. In the reserved case the pending order and its listing
    must be closed together, otherwise cancellation or the expiry worker would
    release the listing back to ACTIVE and re-expose an NFT the seller no longer
    owns. Only ACTIVE/RESERVED listings are closed: a DRAFT or already-closed
    listing is left alone so history is not rewritten.
    """

    asset.verification_status = AssetVerificationStatus.STALE

    pending_orders = (
        await session.scalars(
            select(Order)
            .where(
                Order.listing_id == listing.id,
                Order.status == OrderStatus.RESERVED,
            )
            .with_for_update()
        )
    ).all()
    for pending_order in pending_orders:
        pending_order.status = OrderStatus.CANCELLED
        session.add(
            OrderEvent(
                order_id=pending_order.id,
                from_status=OrderStatus.RESERVED,
                to_status=OrderStatus.CANCELLED,
                actor_id=None,
                actor_type="system",
            )
        )
        await _enqueue_order_notifications(
            session,
            order=pending_order,
            event_type="order_cancelled",
            recipients={
                pending_order.buyer_id: "buyer",
                pending_order.seller_id: "seller",
            },
        )

    if listing.status in (ListingStatus.ACTIVE, ListingStatus.RESERVED):
        # The listing can never be fulfilled, so it must not return to the
        # catalog through cancellation or expiry release.
        listing.status = ListingStatus.EXPIRED

    await session.flush()


def _release_listing(
    listing: Listing | None,
    now: datetime,
    asset: NFTAsset | None,
) -> None:
    """Return a reserved listing to the catalog, unless it is no longer sellable.

    A stale or unverified asset must never be re-exposed by cancelling or
    expiring an order: the catalog filters on listing status alone, so promoting
    such a listing back to ACTIVE would offer an NFT the seller no longer owns.
    """

    if listing is None or listing.status != ListingStatus.RESERVED:
        return
    asset_sellable = (
        asset is not None
        and asset.verification_status is AssetVerificationStatus.VERIFIED
        and asset.owner_id == listing.seller_id
    )
    if not asset_sellable or (
        listing.expires_at is not None and listing.expires_at <= now
    ):
        listing.status = ListingStatus.EXPIRED
        return
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
                .where(Order.status == OrderStatus.RESERVED)
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
            asset = await session.scalar(
                select(NFTAsset)
                .where(NFTAsset.id == listing.asset_id)
                .with_for_update()
            )
            order = await session.scalar(
                select(Order)
                .where(
                    Order.listing_id == listing_id,
                    Order.status == OrderStatus.RESERVED,
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
            _release_listing(listing, current_time, asset)
            session.add(
                OrderEvent(
                    order_id=order.id,
                    from_status=OrderStatus.RESERVED,
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


async def _load_delivery_preparation_snapshot(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    seller_id: uuid.UUID,
    seller_wallet_id: uuid.UUID,
    idempotency_key: str,
    now: datetime,
) -> tuple[uuid.UUID | None, _DeliveryPreparationSnapshot | None]:
    order = await session.scalar(select(Order).where(Order.id == order_id))
    if order is None or order.seller_id != seller_id:
        raise OrderConflict("Order not found")

    existing = await session.scalar(
        select(OrderDeliveryAttempt).where(
            OrderDeliveryAttempt.order_id == order_id,
            OrderDeliveryAttempt.prepare_idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.seller_wallet_id != seller_wallet_id:
            raise OrderConflict("Idempotency key was already used with another seller wallet")
        return existing.id, None

    previous_attempt = await session.scalar(
        select(OrderDeliveryAttempt)
        .where(OrderDeliveryAttempt.order_id == order_id)
        .order_by(OrderDeliveryAttempt.attempt_number.desc())
    )
    if previous_attempt is not None:
        raise OrderConflict("Delivery has already been prepared for this order")
    if order.status is not OrderStatus.RESERVED or order.expires_at <= now:
        raise OrderConflict("Order is not available for delivery preparation")

    listing = await session.scalar(select(Listing).where(Listing.id == order.listing_id))
    if (
        listing is None
        or listing.seller_id != order.seller_id
        or listing.status is not ListingStatus.RESERVED
        or (listing.expires_at is not None and listing.expires_at <= now)
    ):
        raise OrderConflict("Reserved listing is not available")

    asset = await session.scalar(select(NFTAsset).where(NFTAsset.id == listing.asset_id))
    configured_network = get_settings().ton_connect_network
    if (
        asset is None
        or asset.owner_id != order.seller_id
        or asset.asset_type is not AssetType.TON_NFT
        or asset.verification_status is not AssetVerificationStatus.VERIFIED
        or not asset.item_address
        or asset.network != configured_network
    ):
        raise OrderConflict("NFT is not eligible for delivery preparation")

    seller_wallet = await session.scalar(
        select(Wallet).where(
            Wallet.id == seller_wallet_id,
            Wallet.user_id == order.seller_id,
            Wallet.is_verified.is_(True),
            Wallet.network == asset.network,
        )
    )
    if seller_wallet is None:
        raise OrderConflict("Choose a verified seller wallet on the NFT network")

    buyer_wallets = (
        await session.scalars(
            select(Wallet).where(
                Wallet.user_id == order.buyer_id,
                Wallet.is_verified.is_(True),
                Wallet.is_primary.is_(True),
                Wallet.network == asset.network,
            )
        )
    ).all()
    if len(buyer_wallets) != 1:
        raise OrderConflict("Buyer must have one verified primary wallet on the NFT network")
    buyer_wallet = buyer_wallets[0]

    try:
        item_address = normalize_address(asset.item_address)
        seller_address = normalize_address(seller_wallet.address)
        buyer_address = normalize_address(buyer_wallet.address)
    except AddressError as exc:
        raise OrderConflict("A delivery wallet or NFT address is invalid") from exc
    if seller_address == buyer_address:
        raise OrderConflict("Seller and buyer delivery wallets must be different")

    return None, _DeliveryPreparationSnapshot(
        order_id=order.id,
        listing_id=listing.id,
        asset_id=asset.id,
        seller_id=order.seller_id,
        buyer_id=order.buyer_id,
        seller_wallet_id=seller_wallet.id,
        seller_address=seller_address,
        buyer_wallet_id=buyer_wallet.id,
        buyer_address=buyer_address,
        item_address=item_address,
        network=asset.network,
    )


async def prepare_delivery(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    seller_id: uuid.UUID,
    seller_wallet_id: uuid.UUID,
    idempotency_key: str,
    verifier: TONNFTVerifier,
) -> uuid.UUID:
    """Create a non-custodial seller delivery intent after fresh owner verification."""

    if not 1 <= len(idempotency_key) <= 128:
        raise OrderConflict("Invalid delivery preparation idempotency key")

    # First read is deliberately unlocked; provider I/O must not run under DB locks.
    current_time = datetime.now(UTC)
    existing_id, snapshot = await _load_delivery_preparation_snapshot(
        session,
        order_id=order_id,
        seller_id=seller_id,
        seller_wallet_id=seller_wallet_id,
        idempotency_key=idempotency_key,
        now=current_time,
    )
    if existing_id is not None:
        return existing_id
    if snapshot is None:  # pragma: no cover - guarded by the loader
        raise OrderConflict("Delivery is not available")

    if verifier.network is not None and verifier.network != snapshot.network:
        raise OrderVerificationUnavailable(
            "The TON ownership provider is not configured for this asset's network"
        )

    # Do not keep the read transaction or any DB connection while querying TON.
    await session.rollback()
    verification = await verifier.verify(snapshot.item_address, snapshot.seller_address)
    if verification.status is VerificationStatus.PROVIDER_UNAVAILABLE:
        raise OrderVerificationUnavailable(
            "TON NFT ownership provider is temporarily unavailable"
        )
    try:
        verified_item = normalize_address(verification.item_address)
        verified_expected_owner = normalize_address(verification.expected_owner_address or "")
        verified_owner = normalize_address(verification.owner_address or "")
    except AddressError as exc:
        raise OrderConflict("Current NFT ownership could not be verified") from exc
    if (
        verified_item != snapshot.item_address
        or verified_expected_owner != snapshot.seller_address
    ):
        raise OrderConflict("TON provider returned ownership data for a different NFT or wallet")

    ownership_lost = (
        verification.status is VerificationStatus.OWNER_MISMATCH
        and verified_owner != snapshot.seller_address
    )
    if not ownership_lost and (
        verification.status is not VerificationStatus.VERIFIED
        or verified_owner != snapshot.seller_address
    ):
        raise OrderConflict("Seller ownership of this NFT could not be verified")

    committed_at = datetime.now(UTC)
    settings = get_settings()
    query_id = secrets.randbits(64)
    rejection: str | None = None
    attempt_id: uuid.UUID | None = None

    await session.rollback()
    async with session.begin():
        listing = await session.scalar(
            select(Listing).where(Listing.id == snapshot.listing_id).with_for_update()
        )
        wallet_ids = sorted(
            (snapshot.seller_wallet_id, snapshot.buyer_wallet_id), key=str
        )
        locked_wallets = (
            await session.scalars(
                select(Wallet)
                .where(Wallet.id.in_(wallet_ids))
                .order_by(Wallet.id)
                .with_for_update()
            )
        ).all()
        wallets_by_id = {wallet.id: wallet for wallet in locked_wallets}
        asset = await session.scalar(
            select(NFTAsset).where(NFTAsset.id == snapshot.asset_id).with_for_update()
        )
        order = await session.scalar(
            select(Order).where(Order.id == snapshot.order_id).with_for_update()
        )
        if order is None or order.seller_id != seller_id:
            rejection = "Order not found"
        else:
            same_key_attempt = await session.scalar(
                select(OrderDeliveryAttempt)
                .where(
                    OrderDeliveryAttempt.order_id == order.id,
                    OrderDeliveryAttempt.prepare_idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if same_key_attempt is not None:
                attempt_id = same_key_attempt.id
            else:
                previous_attempt = await session.scalar(
                    select(OrderDeliveryAttempt)
                    .where(OrderDeliveryAttempt.order_id == order.id)
                    .order_by(OrderDeliveryAttempt.attempt_number.desc())
                    .with_for_update()
                )
                seller_wallet = wallets_by_id.get(snapshot.seller_wallet_id)
                buyer_wallet = wallets_by_id.get(snapshot.buyer_wallet_id)
                identity_matches = (
                    listing is not None
                    and asset is not None
                    and listing.id == order.listing_id
                    and listing.asset_id == asset.id
                    and listing.seller_id == order.seller_id
                    and asset.owner_id == order.seller_id
                    and asset.asset_type is AssetType.TON_NFT
                    and asset.verification_status is AssetVerificationStatus.VERIFIED
                    and asset.network == snapshot.network
                    and asset.item_address is not None
                    and normalize_address(asset.item_address) == snapshot.item_address
                )
                wallets_match = (
                    seller_wallet is not None
                    and seller_wallet.user_id == order.seller_id
                    and seller_wallet.is_verified
                    and seller_wallet.network == snapshot.network
                    and normalize_address(seller_wallet.address) == snapshot.seller_address
                    and buyer_wallet is not None
                    and buyer_wallet.user_id == order.buyer_id
                    and buyer_wallet.is_verified
                    and buyer_wallet.is_primary
                    and buyer_wallet.network == snapshot.network
                    and normalize_address(buyer_wallet.address) == snapshot.buyer_address
                )
                if previous_attempt is not None:
                    rejection = "Delivery has already been prepared for this order"
                elif ownership_lost and identity_matches:
                    await _invalidate_lost_ownership(
                        session,
                        listing=listing,
                        asset=asset,
                        current_time=committed_at,
                    )
                    rejection = "Seller no longer owns this NFT; the listing was invalidated"
                elif not identity_matches or not wallets_match:
                    rejection = "Order, listing, asset, or verified wallet changed during preparation"
                elif (
                    order.status is not OrderStatus.RESERVED
                    or order.expires_at <= committed_at
                    or listing.status is not ListingStatus.RESERVED
                    or (
                        listing.expires_at is not None
                        and listing.expires_at <= committed_at
                    )
                ):
                    rejection = "Order is no longer available for delivery preparation"
                else:
                    attempt = OrderDeliveryAttempt(
                        order_id=order.id,
                        attempt_number=1,
                        status=OrderDeliveryAttemptStatus.PREPARED,
                        network=snapshot.network,
                        item_address=snapshot.item_address,
                        seller_wallet_id=seller_wallet.id,
                        seller_address_snapshot=snapshot.seller_address,
                        buyer_wallet_id=buyer_wallet.id,
                        buyer_address_snapshot=snapshot.buyer_address,
                        query_id=Decimal(query_id),
                        prepare_idempotency_key=idempotency_key,
                        prepared_at=committed_at,
                        deadline=committed_at + timedelta(
                            seconds=settings.delivery_preparation_ttl_seconds
                        ),
                        next_check_at=committed_at,
                    )
                    order.status = OrderStatus.AWAITING_TRANSFER
                    session.add(attempt)
                    session.add(
                        OrderEvent(
                            order_id=order.id,
                            from_status=OrderStatus.RESERVED,
                            to_status=OrderStatus.AWAITING_TRANSFER,
                            actor_id=seller_id,
                            actor_type="seller",
                        )
                    )
                    await session.flush()
                    attempt_id = attempt.id

    if rejection is not None:
        raise OrderConflict(rejection)
    if attempt_id is None:  # pragma: no cover - guarded by transaction branches
        raise OrderConflict("Delivery preparation could not be persisted")
    return attempt_id


async def submit_delivery_candidate(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    seller_id: uuid.UUID,
    transaction_hash: str,
    now: datetime | None = None,
) -> uuid.UUID:
    """Persist a seller-supplied transaction hash as an untrusted lookup hint."""

    try:
        normalized_hash = normalize_transaction_hash(transaction_hash, "transaction_hash")
    except InvalidProviderData as exc:
        raise OrderConflict("Invalid candidate transaction hash") from exc
    order_header = await session.execute(
        select(Order.listing_id, Listing.asset_id)
        .join(Listing, Listing.id == Order.listing_id)
        .where(Order.id == order_id, Order.seller_id == seller_id)
    )
    header = order_header.first()
    if header is None:
        raise OrderConflict("Order not found")
    listing_id, asset_id = header
    await session.rollback()

    current_time = now or datetime.now(UTC)
    attempt_id: uuid.UUID | None = None
    rejection: str | None = None
    async with session.begin():
        listing = await session.scalar(
            select(Listing).where(Listing.id == listing_id).with_for_update()
        )
        asset = await session.scalar(
            select(NFTAsset).where(NFTAsset.id == asset_id).with_for_update()
        )
        order = await session.scalar(
            select(Order)
            .where(Order.id == order_id, Order.seller_id == seller_id)
            .with_for_update()
        )
        if order is None:
            rejection = "Order not found"
        else:
            attempt = await session.scalar(
                select(OrderDeliveryAttempt)
                .where(OrderDeliveryAttempt.order_id == order.id)
                .order_by(OrderDeliveryAttempt.attempt_number.desc())
                .with_for_update()
            )
            if attempt is None:
                rejection = "Delivery has not been prepared"
            elif attempt.candidate_transaction_hash is not None:
                if attempt.candidate_transaction_hash == normalized_hash:
                    attempt_id = attempt.id
                else:
                    rejection = "A different transaction hash was already submitted"
            elif (
                order.status not in (
                    OrderStatus.AWAITING_TRANSFER,
                    OrderStatus.OBSERVING_TRANSFER,
                )
                or attempt.status not in (
                    OrderDeliveryAttemptStatus.PREPARED,
                    OrderDeliveryAttemptStatus.OBSERVING,
                )
                or listing is None
                or asset is None
                or listing.status is not ListingStatus.RESERVED
                or listing.asset_id != asset.id
            ):
                rejection = "Order is not accepting a delivery submission"
            else:
                attempt.candidate_transaction_hash = normalized_hash
                attempt.submitted_at = current_time
                attempt.next_check_at = current_time
                attempt.status = OrderDeliveryAttemptStatus.OBSERVING
                if order.status is OrderStatus.AWAITING_TRANSFER:
                    order.status = OrderStatus.OBSERVING_TRANSFER
                    session.add(
                        OrderEvent(
                            order_id=order.id,
                            from_status=OrderStatus.AWAITING_TRANSFER,
                            to_status=OrderStatus.OBSERVING_TRANSFER,
                            actor_id=seller_id,
                            actor_type="seller",
                        )
                    )
                attempt_id = attempt.id

    if rejection is not None:
        raise OrderConflict(rejection)
    if attempt_id is None:  # pragma: no cover - guarded by transaction branches
        raise OrderConflict("Delivery submission could not be persisted")
    return attempt_id


async def get_order_delivery_state(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[Order, OrderDeliveryAttempt | None] | None:
    """Return the latest delivery attempt only to a buyer or seller of the order."""

    order = await get_order(session, order_id=order_id, user_id=user_id)
    if order is None:
        return None
    attempt = await session.scalar(
        select(OrderDeliveryAttempt)
        .where(OrderDeliveryAttempt.order_id == order_id)
        .order_by(OrderDeliveryAttempt.attempt_number.desc())
        .limit(1)
    )
    return order, attempt


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
