from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    Order,
    OrderDeliveryAttempt,
    OrderDeliveryAttemptStatus,
    OrderStatus,
    PriceCurrency,
    SellerReview,
)
from app.reviews.service import ReviewConflict, create_review, list_seller_reviews

pytestmark = pytest.mark.integration
pytest_plugins = ("tests.test_postgres_integration",)


async def _user(session: AsyncSession, telegram_id: int):
    from app.db.models import User

    user = User(telegram_id=telegram_id, first_name="Review user")
    session.add(user)
    await session.flush()
    return user


async def _completed_order(session: AsyncSession, seller, buyer, *, verified=True):
    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        external_id=f"0:{uuid4().hex}{uuid4().hex}",
        item_address=f"0:{uuid4().hex}{uuid4().hex}",
        owner_id=buyer.id,
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    session.add(asset)
    await session.flush()
    listing = Listing(
        asset_id=asset.id,
        seller_id=seller.id,
        status=ListingStatus.SOLD,
        price_amount=Decimal("1"),
        price_currency=PriceCurrency.TON,
    )
    session.add(listing)
    await session.flush()
    now = datetime.now(UTC)
    order = Order(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        idempotency_key=uuid4().hex,
        status=OrderStatus.COMPLETED,
        price_amount=Decimal("1"),
        price_currency=PriceCurrency.TON,
        expires_at=now + timedelta(minutes=1),
    )
    session.add(order)
    await session.flush()
    if verified:
        session.add(
            OrderDeliveryAttempt(
                order_id=order.id,
                attempt_number=1,
                status=OrderDeliveryAttemptStatus.VERIFIED,
                network="mainnet",
                item_address=asset.item_address,
                seller_address_snapshot="0:" + "11" * 32,
                buyer_address_snapshot="0:" + "22" * 32,
                query_id=Decimal("1"),
                transaction_hash="tx-verified",
                trace_id="trace-verified",
                masterchain_seqno=1,
                prepared_at=now,
                deadline=now + timedelta(minutes=1),
                verified_at=now,
            )
        )
        await session.flush()
    return order


@pytest.mark.asyncio
async def test_completed_order_requires_verified_delivery_and_duplicate_is_rejected(db_session):
    seller = await _user(db_session, 810000001)
    buyer = await _user(db_session, 810000002)
    unverified = await _completed_order(db_session, seller, buyer, verified=False)

    with pytest.raises(ReviewConflict):
        await create_review(
            db_session, order_id=unverified.id, buyer_id=buyer.id, rating=5, comment="x"
        )

    order = await _completed_order(db_session, seller, buyer)
    created = await create_review(
        db_session, order_id=order.id, buyer_id=buyer.id, rating=5, comment="  Great   transfer "
    )
    assert created.comment == "Great transfer"
    with pytest.raises(ReviewConflict):
        await create_review(
            db_session, order_id=order.id, buyer_id=buyer.id, rating=4, comment=None
        )


@pytest.mark.asyncio
async def test_public_aggregate_is_scoped_and_paginated(db_session):
    seller = await _user(db_session, 810000003)
    other_seller = await _user(db_session, 810000004)
    buyer = await _user(db_session, 810000005)
    first = await _completed_order(db_session, seller, buyer)
    second = await _completed_order(db_session, seller, buyer)
    other = await _completed_order(db_session, other_seller, buyer)
    await create_review(db_session, order_id=first.id, buyer_id=buyer.id, rating=5, comment=None)
    await create_review(db_session, order_id=second.id, buyer_id=buyer.id, rating=3, comment=None)
    await create_review(db_session, order_id=other.id, buyer_id=buyer.id, rating=1, comment=None)

    page = await list_seller_reviews(db_session, seller_id=seller.id, limit=1, offset=0)
    assert page.review_count == 2
    assert page.average_rating == 4.0
    assert page.rating_distribution == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 1}
    assert len(page.items) == 1
    assert page.has_more is True


@pytest.mark.asyncio
async def test_review_database_rejects_self_review(db_session):
    user = await _user(db_session, 810000006)
    review = SellerReview(order_id=uuid4(), buyer_id=user.id, seller_id=user.id, rating=5)
    db_session.add(review)
    with pytest.raises(IntegrityError):
        await db_session.flush()
