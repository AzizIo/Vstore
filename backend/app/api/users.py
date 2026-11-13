from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import Listing, ListingStatus, NFTAsset, Order, OrderStatus, User, Wallet
from app.db.session import get_db_session

router = APIRouter(prefix="/users", tags=["users"])


class UserProfileResponse(BaseModel):
    id: str
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None
    language_code: str | None


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    address: str
    network: str
    is_verified: bool
    is_primary: bool


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    user: Annotated[User, Depends(get_current_user)],
) -> UserProfileResponse:
    return UserProfileResponse(
        id=str(user.id),
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,
    )


@router.get("/me/wallets", response_model=list[WalletResponse])
async def get_my_wallets(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[Wallet]:
    result = await session.scalars(
        select(Wallet)
        .where(Wallet.user_id == user.id)
        .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
    )
    return list(result.all())


@router.delete("/me/wallets/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_wallet(
    wallet_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    # Serialize wallet removal with other wallet lifecycle operations. The
    # marketplace currently associates NFT assets with users, not individual
    # wallet rows, so unlinking is intentionally blocked while this user has
    # any live listing or pending order instead of guessing which wallet backs it.
    await session.scalar(select(User.id).where(User.id == user.id).with_for_update())
    wallet = await session.scalar(
        select(Wallet)
        .where(Wallet.id == wallet_id, Wallet.user_id == user.id)
        .with_for_update()
    )
    if wallet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")

    active_listing_id = await session.scalar(
        select(Listing.id)
        .where(
            Listing.seller_id == user.id,
            Listing.status.in_(
                [ListingStatus.ACTIVE, ListingStatus.RESERVED, ListingStatus.PENDING_REVIEW]
            ),
        )
        .limit(1)
    )
    live_order_id = await session.scalar(
        select(Order.id)
        .where(
            or_(Order.buyer_id == user.id, Order.seller_id == user.id),
            Order.status.in_(OrderStatus.LIVE_STATUSES),
        )
        .limit(1)
    )
    if active_listing_id is not None or live_order_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Close active listings and pending orders before unlinking a wallet.",
        )

    await session.delete(wallet)
    await session.commit()


class ListingOverviewCounts(BaseModel):
    draft: int = 0
    pending_review: int = 0
    active: int = 0
    reserved: int = 0
    sold: int = 0
    cancelled: int = 0
    expired: int = 0
    suspended: int = 0
    total: int = 0


class OrderOverviewCounts(BaseModel):
    reserved: int = 0
    awaiting_transfer: int = 0
    observing_transfer: int = 0
    completed: int = 0
    cancelled: int = 0
    expired: int = 0
    total: int = 0


class SellerActivityItem(BaseModel):
    id: UUID
    kind: Literal["listing", "order"]
    role: Literal["buyer", "seller"] | None = None
    listing_id: UUID
    title: str
    status: str
    created_at: datetime
    price_amount: Decimal
    price_currency: str


class SellerOverviewResponse(BaseModel):
    listings: ListingOverviewCounts
    orders_as_seller: OrderOverviewCounts
    orders_as_buyer: OrderOverviewCounts
    reserved_order_snapshot_values: dict[str, Decimal]
    completed_order_snapshot_values: dict[str, Decimal]
    recent_activity: list[SellerActivityItem]


def _count_statuses(
    rows: list[tuple[object, int]], status_values: tuple[str, ...]
) -> dict[str, int]:
    counts = {value: 0 for value in status_values}
    for value, count in rows:
        key = value.value if hasattr(value, "value") else str(value)
        if key in counts:
            counts[key] = int(count)
    counts["total"] = sum(counts.values())
    return counts


@router.get("/me/overview", response_model=SellerOverviewResponse)
async def get_my_overview(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SellerOverviewResponse:
    listing_statuses = ("draft", "pending_review", "active", "reserved", "sold", "cancelled", "expired", "suspended")
    order_statuses = (
        "reserved",
        "awaiting_transfer",
        "observing_transfer",
        "completed",
        "cancelled",
        "expired",
    )

    listing_rows = await session.execute(
        select(Listing.status, func.count(Listing.id))
        .where(Listing.seller_id == user.id)
        .group_by(Listing.status)
    )
    seller_order_rows = await session.execute(
        select(Order.status, func.count(Order.id))
        .where(Order.seller_id == user.id)
        .group_by(Order.status)
    )
    buyer_order_rows = await session.execute(
        select(Order.status, func.count(Order.id))
        .where(Order.buyer_id == user.id)
        .group_by(Order.status)
    )

    reserved_value_rows = await session.execute(
        select(Order.price_currency, func.sum(Order.price_amount))
        .where(
            Order.seller_id == user.id,
            Order.status.in_(OrderStatus.LIVE_STATUSES),
        )
        .group_by(Order.price_currency)
    )
    completed_value_rows = await session.execute(
        select(Order.price_currency, func.sum(Order.price_amount))
        .where(
            Order.seller_id == user.id,
            Order.status == OrderStatus.COMPLETED,
        )
        .group_by(Order.price_currency)
    )

    recent_listing_rows = await session.execute(
        select(Listing, NFTAsset.name)
        .join(NFTAsset, NFTAsset.id == Listing.asset_id)
        .where(Listing.seller_id == user.id)
        .order_by(Listing.updated_at.desc(), Listing.id.desc())
        .limit(10)
    )
    recent_order_rows = await session.execute(
        select(Order, Listing.title, NFTAsset.name)
        .join(Listing, Listing.id == Order.listing_id)
        .join(NFTAsset, NFTAsset.id == Listing.asset_id)
        .where(or_(Order.buyer_id == user.id, Order.seller_id == user.id))
        .order_by(Order.updated_at.desc(), Order.id.desc())
        .limit(10)
    )

    activity: list[SellerActivityItem] = []
    for listing, asset_name in recent_listing_rows.all():
        activity.append(
            SellerActivityItem(
                id=listing.id,
                kind="listing",
                listing_id=listing.id,
                title=listing.title or asset_name or "Untitled asset",
                status=listing.status.value,
                created_at=listing.updated_at,
                price_amount=listing.price_amount,
                price_currency=listing.price_currency.value,
            )
        )
    for order, listing_title, asset_name in recent_order_rows.all():
        activity.append(
            SellerActivityItem(
                id=order.id,
                kind="order",
                role="buyer" if order.buyer_id == user.id else "seller",
                listing_id=order.listing_id,
                title=listing_title or asset_name or "Untitled asset",
                status=order.status.value,
                created_at=order.updated_at,
                price_amount=order.price_amount,
                price_currency=order.price_currency.value,
            )
        )
    activity.sort(key=lambda item: (item.created_at, str(item.id)), reverse=True)

    return SellerOverviewResponse(
        listings=ListingOverviewCounts(**_count_statuses(listing_rows.all(), listing_statuses)),
        orders_as_seller=OrderOverviewCounts(
            **_count_statuses(seller_order_rows.all(), order_statuses)
        ),
        orders_as_buyer=OrderOverviewCounts(
            **_count_statuses(buyer_order_rows.all(), order_statuses)
        ),
        reserved_order_snapshot_values={
            currency.value: amount for currency, amount in reserved_value_rows.all()
        },
        completed_order_snapshot_values={
            currency.value: amount for currency, amount in completed_value_rows.all()
        },
        recent_activity=activity[:10],
    )
