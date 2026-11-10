"""Issue #45: catalog visibility against a real PostgreSQL.

Unit tests can only assert that a query was built; these tests assert what the
database actually returns for hidden states. They skip without TEST_DATABASE_URL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    PriceCurrency,
    User,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def catalog_database() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("Catalog visibility tests require PostgreSQL")
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        yield url
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        get_settings.cache_clear()


async def make_user(session: AsyncSession, *, offset: int) -> User:
    user = User(
        telegram_id=offset + uuid4().int % 1_000_000_000,
        first_name="Catalog user",
    )
    session.add(user)
    await session.flush()
    return user


async def make_listing(
    session: AsyncSession,
    seller: User,
    *,
    listing_status: ListingStatus = ListingStatus.ACTIVE,
    asset_status: AssetVerificationStatus = AssetVerificationStatus.VERIFIED,
    owner: User | None = None,
    created_at: datetime | None = None,
) -> tuple[NFTAsset, Listing]:
    item_address = f"0:{uuid4().hex}{uuid4().hex}"
    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        network="mainnet",
        external_id=item_address,
        item_address=item_address,
        owner_id=(owner or seller).id,
        name="Visibility NFT",
        verification_status=asset_status,
    )
    session.add(asset)
    await session.flush()
    listing = Listing(
        asset_id=asset.id,
        seller_id=seller.id,
        status=listing_status,
        price_amount=Decimal("1.25"),
        price_currency=PriceCurrency.TON,
        title="Visibility listing",
    )
    if created_at is not None:
        listing.created_at = created_at
    session.add(listing)
    await session.flush()
    return asset, listing


async def cleanup(session_factory, *, listing_ids, asset_ids, user_ids) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            Listing.__table__.delete().where(Listing.id.in_(listing_ids))
        )
        await session.execute(
            NFTAsset.__table__.delete().where(NFTAsset.id.in_(asset_ids))
        )
        await session.execute(User.__table__.delete().where(User.id.in_(user_ids)))


async def test_catalog_hides_stale_unverified_and_mismatched_listings(
    catalog_database: str,
) -> None:
    """Only ACTIVE listings over a VERIFIED asset owned by the seller are visible."""

    engine = create_async_engine(catalog_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    listing_ids: list = []
    asset_ids: list = []

    async with session_factory.begin() as session:
        seller = await make_user(session, offset=600_000_000)
        other = await make_user(session, offset=610_000_000)
        seller_id, other_id = seller.id, other.id

        visible_asset, visible_listing = await make_listing(session, seller)
        _, stale_listing = await make_listing(
            session, seller, asset_status=AssetVerificationStatus.STALE
        )
        _, pending_listing = await make_listing(
            session, seller, asset_status=AssetVerificationStatus.PENDING
        )
        _, failed_listing = await make_listing(
            session, seller, asset_status=AssetVerificationStatus.FAILED
        )
        _, reserved_listing = await make_listing(
            session, seller, listing_status=ListingStatus.RESERVED
        )
        _, draft_listing = await make_listing(
            session, seller, listing_status=ListingStatus.DRAFT
        )
        _, relocated_asset = await make_listing(session, seller, owner=other)

        listing_ids = [
            visible_listing.id,
            stale_listing.id,
            pending_listing.id,
            failed_listing.id,
            reserved_listing.id,
            draft_listing.id,
            relocated_asset.id,
        ]
        asset_ids = [visible_asset.id] + [
            listing.asset_id for listing in (
                stale_listing, pending_listing, failed_listing,
                reserved_listing, draft_listing, relocated_asset,
            )
        ]

    try:
        async with session_factory() as session:
            # Reuse the exact conditions the API applies.
            from app.api.listings import _purchasable_conditions

            rows = (
                await session.scalars(
                    select(Listing)
                    .join(NFTAsset, NFTAsset.id == Listing.asset_id)
                    .where(Listing.id.in_(listing_ids), *_purchasable_conditions())
                )
            ).all()

        assert [row.id for row in rows] == [listing_ids[0]]
    finally:
        await cleanup(
            session_factory,
            listing_ids=listing_ids,
            asset_ids=asset_ids,
            user_ids=[seller_id, other_id],
        )
        await engine.dispose()


async def test_catalog_pagination_is_stable_with_identical_timestamps(
    catalog_database: str,
) -> None:
    """Equal created_at values must not let rows repeat or vanish across pages."""

    engine = create_async_engine(catalog_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    listing_ids: list = []
    asset_ids: list = []

    async with session_factory.begin() as session:
        seller = await make_user(session, offset=620_000_000)
        seller_id = seller.id
        for _ in range(5):
            asset, listing = await make_listing(session, seller, created_at=timestamp)
            listing_ids.append(listing.id)
            asset_ids.append(asset.id)

    try:
        from app.api.listings import _purchasable_conditions

        seen: list = []
        for offset in range(0, 5, 2):
            async with session_factory() as session:
                rows = (
                    await session.scalars(
                        select(Listing)
                        .join(NFTAsset, NFTAsset.id == Listing.asset_id)
                        .where(
                            Listing.id.in_(listing_ids),
                            *_purchasable_conditions(),
                        )
                        .order_by(Listing.created_at.desc(), Listing.id.asc())
                        .limit(2)
                        .offset(offset)
                    )
                ).all()
            seen.extend(row.id for row in rows)

        assert len(seen) == len(set(seen)), "a row appeared on two pages"
        assert set(seen) == set(listing_ids), "pagination skipped a row"
    finally:
        await cleanup(
            session_factory,
            listing_ids=listing_ids,
            asset_ids=asset_ids,
            user_ids=[seller_id],
        )
        await engine.dispose()


async def test_detail_returns_hidden_listing_only_when_purchasable(
    catalog_database: str,
) -> None:
    """A stale listing must 404 on detail exactly as it is absent from the catalog."""

    engine = create_async_engine(catalog_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory.begin() as session:
        seller = await make_user(session, offset=630_000_000)
        seller_id = seller.id
        good_asset, good_listing = await make_listing(session, seller)
        bad_asset, bad_listing = await make_listing(
            session, seller, asset_status=AssetVerificationStatus.STALE
        )
        good_id, bad_id = good_listing.id, bad_listing.id
        asset_ids = [good_asset.id, bad_asset.id]

    try:
        from app.api.listings import _purchasable_conditions

        async with session_factory() as session:
            good = await session.scalar(
                select(Listing.id)
                .join(NFTAsset, NFTAsset.id == Listing.asset_id)
                .where(Listing.id == good_id, *_purchasable_conditions())
            )
            bad = await session.scalar(
                select(Listing.id)
                .join(NFTAsset, NFTAsset.id == Listing.asset_id)
                .where(Listing.id == bad_id, *_purchasable_conditions())
            )

        assert good == good_id
        assert bad is None
    finally:
        await cleanup(
            session_factory,
            listing_ids=[good_id, bad_id],
            asset_ids=asset_ids,
            user_ids=[seller_id],
        )
        await engine.dispose()


async def test_expired_active_listings_are_hidden_and_transitioned(
    catalog_database: str,
) -> None:
    """Expired active listings are immediately hidden and later closed by the worker."""

    from app.api.listings import _purchasable_conditions
    from app.listings.service import expire_active_listings

    engine = create_async_engine(catalog_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    listing_ids: list = []
    asset_ids: list = []

    async with session_factory.begin() as session:
        seller = await make_user(session, offset=640_000_000)
        seller_id = seller.id

        expired_asset, expired_listing = await make_listing(session, seller)
        expired_listing.expires_at = now - timedelta(minutes=1)

        future_asset, future_listing = await make_listing(session, seller)
        future_listing.expires_at = now + timedelta(days=1)

        reserved_asset, reserved_listing = await make_listing(
            session, seller, listing_status=ListingStatus.RESERVED
        )
        reserved_listing.expires_at = now - timedelta(minutes=1)

        listing_ids = [expired_listing.id, future_listing.id, reserved_listing.id]
        asset_ids = [expired_asset.id, future_asset.id, reserved_asset.id]

    try:
        async with session_factory() as session:
            visible_before_worker = (
                await session.scalars(
                    select(Listing.id)
                    .join(NFTAsset, NFTAsset.id == Listing.asset_id)
                    .where(Listing.id.in_(listing_ids), *_purchasable_conditions())
                    .order_by(Listing.id.asc())
                )
            ).all()
        assert expired_listing.id not in visible_before_worker
        assert future_listing.id in visible_before_worker
        assert reserved_listing.id not in visible_before_worker

        async with session_factory() as session:
            changed = await expire_active_listings(session, now=now, limit=10)
        assert changed == 1

        async with session_factory() as session:
            persisted = (
                await session.scalars(select(Listing).where(Listing.id.in_(listing_ids)))
            ).all()
        states = {listing.id: listing.status for listing in persisted}
        assert states[expired_listing.id] is ListingStatus.EXPIRED
        assert states[future_listing.id] is ListingStatus.ACTIVE
        assert states[reserved_listing.id] is ListingStatus.RESERVED
    finally:
        await cleanup(
            session_factory,
            listing_ids=listing_ids,
            asset_ids=asset_ids,
            user_ids=[seller_id],
        )
        await engine.dispose()
