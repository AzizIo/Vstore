from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Order,
    OrderDeliveryAttempt,
    OrderDeliveryAttemptStatus,
    OrderStatus,
    SellerReview,
)
from app.reviews.schemas import (
    EligibilityResponse,
    ReviewCreateResponse,
    ReviewItem,
    ReviewPageResponse,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class ReviewConflict(Exception):
    """The order is not eligible or already has an immutable review."""


def _is_verified_order(order: Order, attempt: OrderDeliveryAttempt | None) -> bool:
    return (
        order.status is OrderStatus.COMPLETED
        and attempt is not None
        and attempt.status is OrderDeliveryAttemptStatus.VERIFIED
        and attempt.transaction_hash is not None
        and attempt.verified_at is not None
    )


async def _verified_attempt(session: AsyncSession, order_id: UUID) -> OrderDeliveryAttempt | None:
    return await session.scalar(
        select(OrderDeliveryAttempt).where(
            OrderDeliveryAttempt.order_id == order_id,
            OrderDeliveryAttempt.status == OrderDeliveryAttemptStatus.VERIFIED,
            OrderDeliveryAttempt.transaction_hash.is_not(None),
            OrderDeliveryAttempt.verified_at.is_not(None),
        ).limit(1)
    )


async def get_review_eligibility(
    session: AsyncSession, *, order_id: UUID, buyer_id: UUID
) -> EligibilityResponse:
    order = await session.get(Order, order_id)
    if order is None or order.buyer_id != buyer_id or order.seller_id == buyer_id:
        return EligibilityResponse(order_id=order_id, eligible=False, already_reviewed=False)
    already_reviewed = await session.scalar(
        select(SellerReview.id).where(SellerReview.order_id == order_id).limit(1)
    )
    attempt = await _verified_attempt(session, order_id)
    return EligibilityResponse(
        order_id=order_id,
        eligible=not already_reviewed and _is_verified_order(order, attempt),
        already_reviewed=already_reviewed is not None,
    )


async def create_review(
    session: AsyncSession,
    *,
    order_id: UUID,
    buyer_id: UUID,
    rating: int,
    comment: str | None,
) -> ReviewCreateResponse:
    try:
        transaction = session.begin_nested() if session.in_transaction() else session.begin()
        async with transaction:
            order = await session.scalar(
                select(Order).where(Order.id == order_id).with_for_update()
            )
            if order is None or order.buyer_id != buyer_id or order.seller_id == buyer_id:
                raise ReviewConflict("Review is not available for this order")
            attempt = await _verified_attempt(session, order_id)
            if not _is_verified_order(order, attempt):
                raise ReviewConflict("Review is not available for this order")
            existing = await session.scalar(
                select(SellerReview.id).where(SellerReview.order_id == order_id).limit(1)
            )
            if existing is not None:
                raise ReviewConflict("This order has already been reviewed")
            normalized_comment = " ".join(comment.split()) if comment else None
            review = SellerReview(
                order_id=order.id,
                buyer_id=order.buyer_id,
                seller_id=order.seller_id,
                rating=rating,
                comment=normalized_comment or None,
            )
            session.add(review)
            await session.flush()
            await session.refresh(review)
            response = ReviewCreateResponse.model_validate(review)
        return response
    except IntegrityError as exc:
        raise ReviewConflict("This order has already been reviewed") from exc


async def list_seller_reviews(
    session: AsyncSession, *, seller_id: UUID, limit: int, offset: int
) -> ReviewPageResponse:
    bounded_limit = min(max(limit, 1), MAX_LIMIT)
    bounded_offset = max(offset, 0)
    totals = await session.execute(
        select(
            func.count(SellerReview.id),
            func.coalesce(func.avg(SellerReview.rating), 0),
        ).where(SellerReview.seller_id == seller_id)
    )
    review_count, average = totals.one()
    distribution_rows = await session.execute(
        select(SellerReview.rating, func.count(SellerReview.id))
        .where(SellerReview.seller_id == seller_id)
        .group_by(SellerReview.rating)
    )
    distribution = {str(rating): int(count) for rating, count in distribution_rows}
    items_result = await session.scalars(
        select(SellerReview)
        .where(SellerReview.seller_id == seller_id)
        .order_by(desc(SellerReview.created_at), desc(SellerReview.id))
        .offset(bounded_offset)
        .limit(bounded_limit + 1)
    )
    rows = list(items_result)
    has_more = len(rows) > bounded_limit
    items = [ReviewItem.model_validate(row) for row in rows[:bounded_limit]]
    return ReviewPageResponse(
        seller_id=seller_id,
        average_rating=round(float(average), 1),
        review_count=int(review_count),
        rating_distribution={str(value): distribution.get(str(value), 0) for value in range(1, 6)},
        items=items,
        limit=bounded_limit,
        offset=bounded_offset,
        has_more=has_more,
    )
