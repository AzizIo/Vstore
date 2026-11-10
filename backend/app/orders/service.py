from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import (
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    Order,
    OrderEvent,
    OrderStatus,
    User,
)


class OrderConflict(Exception):
    """The listing or idempotency key cannot be used for this order."""


async def create_order(
    session: AsyncSession,
    *,
    buyer_id: uuid.UUID,
    listing_id: uuid.UUID,
    idempotency_key: str,
    now: datetime | None = None,
) -> uuid.UUID:
    current_time = now or datetime.now(UTC)
    order_id: uuid.UUID
    unavailable = False

    async with session.begin():
        await session.scalar(select(User.id).where(User.id == buyer_id).with_for_update())
        existing = await session.scalar(
            select(Order).where(
                Order.buyer_id == buyer_id,
                Order.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.listing_id != listing_id:
                raise OrderConflict("Idempotency key was already used for another listing")
            return existing.id

        listing = await session.scalar(
            select(Listing).where(Listing.id == listing_id).with_for_update()
        )
        if listing is None:
            unavailable = True
        elif listing.seller_id == buyer_id:
            raise OrderConflict("You cannot order your own listing")
        elif listing.expires_at is not None and listing.expires_at <= current_time:
            if listing.status == ListingStatus.ACTIVE:
                listing.status = ListingStatus.EXPIRED
            unavailable = True
        elif listing.status != ListingStatus.ACTIVE:
            unavailable = True
        else:
            asset = await session.scalar(
                select(NFTAsset)
                .where(NFTAsset.id == listing.asset_id)
                .with_for_update()
            )
            if (
                asset is None
                or asset.owner_id != listing.seller_id
                or asset.verification_status != AssetVerificationStatus.VERIFIED
            ):
                unavailable = True
            else:
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
                order_id = order.id

    if unavailable:
        raise OrderConflict("Listing is not available")

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
