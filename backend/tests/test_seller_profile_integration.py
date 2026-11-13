from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sellers import get_public_seller_profile
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
    User,
)

pytestmark = pytest.mark.integration
pytest_plugins = ("tests.test_postgres_integration",)


async def _seller_user(session: AsyncSession, telegram_id: int, *, blocked: bool = False) -> User:
    user = User(
        telegram_id=telegram_id,
        first_name=f"Public {telegram_id}",
        last_name="Seller",
        username=f"seller{telegram_id}",
        language_code="ru",
        is_blocked=blocked,
    )
    session.add(user)
    await session.flush()
    return user


async def _public_listing(
    session: AsyncSession,
    seller: User,
    *,
    status: ListingStatus = ListingStatus.ACTIVE,
    verification: AssetVerificationStatus = AssetVerificationStatus.VERIFIED,
    owner: User | None = None,
    expires_at: datetime | None = None,
):
    item_address = f"0:{uuid4().hex}{uuid4().hex}"
    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        network="mainnet",
        external_id=item_address,
        item_address=item_address,
        owner_id=(owner or seller).id,
        name="Storefront NFT",
        description="Public asset description",
        image_url="https://cdn.example.test/nft.png",
        verification_status=verification,
    )
    session.add(asset)
    await session.flush()
    listing = Listing(
        asset_id=asset.id,
        seller_id=seller.id,
        status=status,
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        title="Storefront item",
        description="Visible listing",
        expires_at=expires_at,
    )
    session.add(listing)
    await session.flush()
    return asset, listing


async def _verified_review(
    session: AsyncSession, seller: User, buyer: User, *, rating: int, comment: str | None
) -> SellerReview:
    asset, sold_listing = await _public_listing(
        session, seller, status=ListingStatus.SOLD, owner=buyer
    )
    now = datetime.now(UTC)
    order = Order(
        listing_id=sold_listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        idempotency_key=uuid4().hex,
        status=OrderStatus.COMPLETED,
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        expires_at=now + timedelta(minutes=15),
    )
    session.add(order)
    await session.flush()
    session.add(
        OrderDeliveryAttempt(
            order_id=order.id,
            attempt_number=1,
            status=OrderDeliveryAttemptStatus.VERIFIED,
            network="mainnet",
            item_address=asset.item_address or asset.external_id,
            seller_address_snapshot="0:" + "11" * 32,
            buyer_address_snapshot="0:" + "22" * 32,
            query_id=Decimal("1"),
            transaction_hash=f"tx-{uuid4().hex}",
            trace_id=f"trace-{uuid4().hex}",
            masterchain_seqno=1,
            prepared_at=now,
            deadline=now + timedelta(minutes=1),
            verified_at=now,
        )
    )
    review = SellerReview(
        order_id=order.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        rating=rating,
        comment=comment,
    )
    session.add(review)
    await session.flush()
    return review


async def test_public_profile_isolated_privacy_safe_and_filters_hidden_listings(db_session):
    seller = await _seller_user(db_session, 820000001)
    other_seller = await _seller_user(db_session, 820000002)
    buyer = await _seller_user(db_session, 820000003)

    visible_asset, visible_listing = await _public_listing(db_session, seller)
    await _public_listing(db_session, seller, status=ListingStatus.DRAFT)
    await _public_listing(db_session, seller, status=ListingStatus.RESERVED)
    await _public_listing(db_session, seller, status=ListingStatus.SUSPENDED)
    await _public_listing(
        db_session, seller, verification=AssetVerificationStatus.STALE
    )
    await _public_listing(
        db_session,
        seller,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    await _public_listing(db_session, seller, owner=other_seller)
    await _public_listing(db_session, other_seller)
    await _verified_review(db_session, seller, buyer, rating=5, comment="Great seller")
    await _verified_review(db_session, other_seller, buyer, rating=1, comment="Other seller")

    response = await get_public_seller_profile(
        seller.id,
        db_session,
        listings_limit=10,
        listings_offset=0,
        reviews_limit=10,
        reviews_offset=0,
    )

    assert response.seller.id == seller.id
    assert response.seller.display_name == "Public 820000001 Seller"
    assert response.seller.average_rating == 5.0
    assert response.seller.review_count == 1
    assert response.seller.active_listing_count == 1
    assert [item.id for item in response.listings] == [visible_listing.id]
    assert [review.comment for review in response.reviews] == ["Great seller"]
    assert response.listings[0].asset.id == visible_asset.id
    serialized = response.model_dump(mode="json")
    seller_payload = serialized["seller"]
    listing_payload = serialized["listings"][0]
    listing_seller_payload = listing_payload["seller"]
    review_payload = serialized["reviews"][0]

    assert set(seller_payload) == {
        "id", "display_name", "average_rating", "review_count", "active_listing_count"
    }
    assert set(listing_seller_payload) == {"id", "username", "first_name"}
    assert "item_address" in listing_payload["asset"]
    assert set(review_payload) == {"id", "rating", "comment", "created_at"}

    forbidden_keys = {
        "telegram_id",
        "language_code",
        "is_blocked",
        "wallets",
        "seller_address_snapshot",
        "buyer_address_snapshot",
        "buyer_id",
        "order_id",
        "email",
        "auth_token",
        "session_token",
        "provider_source",
        "trace_id",
        "transaction_hash",
    }

    def assert_no_private_fields(value):
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for nested in value.values():
                assert_no_private_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_no_private_fields(nested)

    assert_no_private_fields(serialized)


async def test_public_profile_empty_seller_and_stable_bounded_pagination(db_session):
    seller = await _seller_user(db_session, 820000004)
    empty = await get_public_seller_profile(
        seller.id, db_session, listings_limit=1, listings_offset=0,
        reviews_limit=1, reviews_offset=0,
    )
    assert empty.listings == []
    assert empty.reviews == []
    assert empty.seller.average_rating == 0.0
    assert empty.seller.review_count == 0

    ids = []
    for _ in range(3):
        _, row = await _public_listing(db_session, seller)
        ids.append(row.id)

    first = await get_public_seller_profile(
        seller.id, db_session, listings_limit=2, listings_offset=0,
        reviews_limit=1, reviews_offset=0,
    )
    second = await get_public_seller_profile(
        seller.id, db_session, listings_limit=2, listings_offset=2,
        reviews_limit=1, reviews_offset=0,
    )
    first_ids = [item.id for item in first.listings]
    second_ids = [item.id for item in second.listings]
    assert len(first_ids) == 2
    assert len(second_ids) == 1
    assert len(set(first_ids + second_ids)) == 3
    assert first.listings_has_more is True
    assert second.listings_has_more is False


async def test_public_profile_rejects_missing_or_blocked_seller(db_session):
    seller = await _seller_user(db_session, 820000005, blocked=True)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as missing:
        await get_public_seller_profile(
            uuid4(), db_session, listings_limit=12, listings_offset=0,
            reviews_limit=10, reviews_offset=0,
        )
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as blocked:
        await get_public_seller_profile(
            seller.id, db_session, listings_limit=12, listings_offset=0,
            reviews_limit=10, reviews_offset=0,
        )
    assert blocked.value.status_code == 404


async def test_public_rating_excludes_completed_orders_without_verified_transfer(db_session):
    seller = await _seller_user(db_session, 820000006)
    buyer = await _seller_user(db_session, 820000007)
    await _verified_review(db_session, seller, buyer, rating=4, comment="Verified")

    asset, listing = await _public_listing(
        db_session, seller, status=ListingStatus.SOLD, owner=buyer
    )
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
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        SellerReview(
            order_id=order.id,
            buyer_id=buyer.id,
            seller_id=seller.id,
            rating=1,
            comment="Ineligible",
        )
    )
    await db_session.flush()

    profile = await get_public_seller_profile(
        seller.id, db_session, listings_limit=10, listings_offset=0,
        reviews_limit=10, reviews_offset=0,
    )
    assert profile.seller.review_count == 1
    assert profile.seller.average_rating == 4.0
    assert [review.comment for review in profile.reviews] == ["Verified"]



async def test_multiple_verified_attempts_do_not_duplicate_reviews_or_bias_rating(db_session):
    seller = await _seller_user(db_session, 820000008)
    buyer = await _seller_user(db_session, 820000009)
    review = await _verified_review(
        db_session, seller, buyer, rating=4, comment="One review, two attempts"
    )

    order = await db_session.get(Order, review.order_id)
    assert order is not None
    existing_attempt = await db_session.scalar(
        select(OrderDeliveryAttempt).where(
            OrderDeliveryAttempt.order_id == order.id,
            OrderDeliveryAttempt.status == OrderDeliveryAttemptStatus.VERIFIED,
        )
    )
    assert existing_attempt is not None
    now = datetime.now(UTC)
    db_session.add(
        OrderDeliveryAttempt(
            order_id=order.id,
            attempt_number=2,
            status=OrderDeliveryAttemptStatus.VERIFIED,
            network=existing_attempt.network,
            item_address=existing_attempt.item_address,
            seller_address_snapshot="0:" + "33" * 32,
            buyer_address_snapshot="0:" + "44" * 32,
            query_id=Decimal("2"),
            transaction_hash=f"tx-second-{uuid4().hex}",
            trace_id=f"trace-second-{uuid4().hex}",
            masterchain_seqno=2,
            prepared_at=now,
            deadline=now + timedelta(minutes=1),
            verified_at=now,
        )
    )
    await db_session.flush()

    profile = await get_public_seller_profile(
        seller.id,
        db_session,
        listings_limit=10,
        listings_offset=0,
        reviews_limit=10,
        reviews_offset=0,
    )
    assert profile.seller.review_count == 1
    assert profile.seller.average_rating == 4.0
    assert [item.id for item in profile.reviews] == [review.id]
