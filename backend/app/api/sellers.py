from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.listings import ListingResponse, _listing_query, _purchasable_conditions
from app.db.models import (
    Listing,
    NFTAsset,
    Order,
    OrderDeliveryAttempt,
    OrderDeliveryAttemptStatus,
    OrderStatus,
    SellerReview,
    User,
)
from app.db.session import get_db_session
from app.reviews.schemas import ReviewItem

router = APIRouter(prefix="/sellers", tags=["sellers"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]

DEFAULT_LISTINGS_LIMIT = 12
MAX_LISTINGS_LIMIT = 48
DEFAULT_REVIEWS_LIMIT = 10
MAX_REVIEWS_LIMIT = 50


class PublicSellerSummary(BaseModel):
    id: UUID
    display_name: str
    average_rating: float
    review_count: int
    active_listing_count: int


class PublicSellerProfileResponse(BaseModel):
    seller: PublicSellerSummary
    listings: list[ListingResponse]
    listings_limit: int
    listings_offset: int
    listings_has_more: bool
    reviews: list[ReviewItem]
    reviews_limit: int
    reviews_offset: int
    reviews_has_more: bool


def _verified_review_conditions():
    """Exactly the eligibility evidence enforced by reviews.create_review."""
    return (
        Order.status == OrderStatus.COMPLETED,
        Order.seller_id == SellerReview.seller_id,
        Order.buyer_id == SellerReview.buyer_id,
        OrderDeliveryAttempt.order_id == Order.id,
        OrderDeliveryAttempt.status == OrderDeliveryAttemptStatus.VERIFIED,
        OrderDeliveryAttempt.transaction_hash.is_not(None),
        OrderDeliveryAttempt.verified_at.is_not(None),
    )


def _display_name(user: User) -> str:
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part)
    if full_name.strip():
        return full_name.strip()[:257]
    if user.username:
        return user.username[:64]
    return "Seller"


@router.get("/{seller_id}/profile", response_model=PublicSellerProfileResponse)
async def get_public_seller_profile(
    seller_id: UUID,
    session: DbSession,
    listings_limit: Annotated[int, Query(ge=1, le=MAX_LISTINGS_LIMIT)] = DEFAULT_LISTINGS_LIMIT,
    listings_offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    reviews_limit: Annotated[int, Query(ge=1, le=MAX_REVIEWS_LIMIT)] = DEFAULT_REVIEWS_LIMIT,
    reviews_offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> PublicSellerProfileResponse:
    seller = await session.scalar(
        select(User).where(User.id == seller_id, User.is_blocked.is_(False))
    )
    if seller is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seller not found")

    # One aggregate query over the exact completed + delivery-verified review
    # provenance required by the existing review creation service.
    rating_row = (
        await session.execute(
            select(
                func.count(func.distinct(SellerReview.id)),
                func.coalesce(func.avg(SellerReview.rating), 0),
            )
            .join(Order, Order.id == SellerReview.order_id)
            .join(OrderDeliveryAttempt, OrderDeliveryAttempt.order_id == Order.id)
            .where(
                SellerReview.seller_id == seller_id,
                *_verified_review_conditions(),
            )
        )
    ).one()
    review_count, average_rating = int(rating_row[0]), float(rating_row[1])

    purchasable = _purchasable_conditions()
    listings_base = (
        select(Listing.id)
        .join(NFTAsset, NFTAsset.id == Listing.asset_id)
        .where(Listing.seller_id == seller_id, *purchasable)
    )
    active_listing_count = int(
        await session.scalar(select(func.count()).select_from(listings_base.subquery())) or 0
    )
    listing_rows = await session.scalars(
        _listing_query()
        .join(NFTAsset, NFTAsset.id == Listing.asset_id)
        .where(Listing.seller_id == seller_id, *purchasable)
        .order_by(Listing.created_at.desc(), Listing.id.asc())
        .offset(listings_offset)
        .limit(listings_limit + 1)
    )
    listing_items = list(listing_rows.unique().all())
    listings_has_more = len(listing_items) > listings_limit
    public_listings = [
        ListingResponse.model_validate(row) for row in listing_items[:listings_limit]
    ]

    # Reviews use the same public item DTO as GET /reviews/sellers/{seller_id}.
    # Joining verified attempts prevents old/manually inserted or otherwise
    # ineligible rows from contributing to either count or public display.
    review_rows = await session.scalars(
        select(SellerReview)
        .join(Order, Order.id == SellerReview.order_id)
        .join(OrderDeliveryAttempt, OrderDeliveryAttempt.order_id == Order.id)
        .where(
            SellerReview.seller_id == seller_id,
            *_verified_review_conditions(),
        )
        .order_by(SellerReview.created_at.desc(), SellerReview.id.desc())
        .offset(reviews_offset)
        .limit(reviews_limit + 1)
    )
    reviews = list(review_rows.all())
    reviews_has_more = len(reviews) > reviews_limit
    public_reviews = [
        ReviewItem.model_validate(row) for row in reviews[:reviews_limit]
    ]

    return PublicSellerProfileResponse(
        seller=PublicSellerSummary(
            id=seller.id,
            display_name=_display_name(seller),
            average_rating=round(average_rating, 1),
            review_count=review_count,
            active_listing_count=active_listing_count,
        ),
        listings=public_listings,
        listings_limit=listings_limit,
        listings_offset=listings_offset,
        listings_has_more=listings_has_more,
        reviews=public_reviews,
        reviews_limit=reviews_limit,
        reviews_offset=reviews_offset,
        reviews_has_more=reviews_has_more,
    )
