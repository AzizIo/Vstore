from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.assets import _upsert_verified_asset
from app.assets.ton_nft.models import NFTItemSnapshot, NFTMetadata
from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    PriceCurrency,
    User,
    Wallet,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("Integration tests require a dedicated PostgreSQL TEST_DATABASE_URL")
    return url


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str):
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_database_url
    get_settings.cache_clear()
    try:
        alembic_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(alembic_config, "head")
        yield
        command.downgrade(alembic_config, "base")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        get_settings.cache_clear()


@pytest.fixture
async def db_session(test_database_url: str, migrated_database) -> AsyncSession:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


async def make_user(session: AsyncSession, telegram_id: int = 700000001) -> User:
    user = User(telegram_id=telegram_id, first_name="Integration", username=f"user{telegram_id}")
    session.add(user)
    await session.flush()
    return user


async def make_asset(
    session: AsyncSession, owner: User, external_id: str = "nft-asset-1"
) -> NFTAsset:
    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        external_id=external_id,
        item_address=f"EQ{external_id}",
        owner_id=owner.id,
        name="Integration NFT",
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    session.add(asset)
    await session.flush()
    return asset


def make_listing(owner: User, asset: NFTAsset, status: ListingStatus) -> Listing:
    return Listing(
        asset_id=asset.id,
        seller_id=owner.id,
        status=status,
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        title="Integration listing",
    )


async def test_alembic_upgrade_applies_expected_revision(db_session: AsyncSession) -> None:
    revision = await db_session.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "0002_asset_network_scope"


async def test_users_reject_duplicate_telegram_ids(db_session: AsyncSession) -> None:
    await make_user(db_session, telegram_id=700000002)
    db_session.add(User(telegram_id=700000002, first_name="Duplicate"))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_wallet_address_is_unique_per_network(db_session: AsyncSession) -> None:
    owner = await make_user(db_session, telegram_id=700000003)
    other_owner = await make_user(db_session, telegram_id=700000013)
    db_session.add_all(
        [
            Wallet(user_id=owner.id, address="same-wallet-address", network="mainnet"),
            Wallet(user_id=other_owner.id, address="same-wallet-address", network="mainnet"),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_asset_external_id_is_unique_per_asset_type(db_session: AsyncSession) -> None:
    owner = await make_user(db_session, telegram_id=700000004)
    await make_asset(db_session, owner, external_id="unique-nft")
    db_session.add(
        NFTAsset(
            asset_type=AssetType.TON_NFT,
            external_id="unique-nft",
            owner_id=owner.id,
            verification_status=AssetVerificationStatus.PENDING,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_open_listing_is_unique_but_drafts_are_allowed(db_session: AsyncSession) -> None:
    owner = await make_user(db_session, telegram_id=700000005)
    asset = await make_asset(db_session, owner, external_id="single-open-listing")
    db_session.add_all(
        [
            make_listing(owner, asset, ListingStatus.ACTIVE),
            make_listing(owner, asset, ListingStatus.DRAFT),
        ]
    )
    await db_session.flush()

    db_session.add(make_listing(owner, asset, ListingStatus.RESERVED))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_closed_listing_does_not_block_new_active_listing(db_session: AsyncSession) -> None:
    owner = await make_user(db_session, telegram_id=700000006)
    asset = await make_asset(db_session, owner, external_id="relistable-nft")
    db_session.add(make_listing(owner, asset, ListingStatus.SOLD))
    await db_session.flush()

    active = make_listing(owner, asset, ListingStatus.ACTIVE)
    db_session.add(active)
    await db_session.flush()

    result = await db_session.scalar(
        select(Listing).where(Listing.asset_id == asset.id, Listing.status == ListingStatus.ACTIVE)
    )
    assert result is not None
    assert result.id == active.id


async def test_listing_foreign_keys_reject_missing_asset(db_session: AsyncSession) -> None:
    owner = await make_user(db_session, telegram_id=700000007)
    db_session.add(
        Listing(
            asset_id=uuid4(),
            seller_id=owner.id,
            status=ListingStatus.DRAFT,
            price_amount=Decimal("1"),
            price_currency=PriceCurrency.TON,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_listing_query_returns_only_requested_sellers_assets(
    db_session: AsyncSession,
) -> None:
    first_owner = await make_user(db_session, telegram_id=700000008)
    second_owner = await make_user(db_session, telegram_id=700000009)
    first_asset = await make_asset(db_session, first_owner, external_id="seller-one-nft")
    second_asset = await make_asset(db_session, second_owner, external_id="seller-two-nft")
    first_listing = make_listing(first_owner, first_asset, ListingStatus.ACTIVE)
    second_listing = make_listing(second_owner, second_asset, ListingStatus.ACTIVE)
    db_session.add_all([first_listing, second_listing])
    await db_session.flush()

    results = (
        await db_session.scalars(select(Listing).where(Listing.seller_id == first_owner.id))
    ).all()
    assert [listing.id for listing in results] == [first_listing.id]


async def test_same_external_id_is_allowed_for_different_asset_types(
    db_session: AsyncSession,
) -> None:
    owner = await make_user(db_session, telegram_id=700000010)
    await make_asset(db_session, owner, external_id="shared-external-id")
    gift = NFTAsset(
        asset_type=AssetType.TELEGRAM_GIFT,
        external_id="shared-external-id",
        owner_id=owner.id,
        verification_status=AssetVerificationStatus.PENDING,
    )
    db_session.add(gift)
    await db_session.flush()

    assert gift.id is not None


async def test_same_ton_item_address_is_scoped_to_network(
    db_session: AsyncSession,
) -> None:
    owner = await make_user(db_session, telegram_id=700000014)
    mainnet_asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        network="mainnet",
        external_id="same-ton-item-address",
        owner_id=owner.id,
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    testnet_asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        network="testnet",
        external_id="same-ton-item-address",
        owner_id=owner.id,
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    db_session.add_all([mainnet_asset, testnet_asset])
    await db_session.flush()

    assert mainnet_asset.id != testnet_asset.id


async def test_listing_rejects_non_positive_price(db_session: AsyncSession) -> None:
    owner = await make_user(db_session, telegram_id=700000011)
    asset = await make_asset(db_session, owner, external_id="invalid-price-nft")
    listing = make_listing(owner, asset, ListingStatus.DRAFT)
    listing.price_amount = Decimal("0")
    db_session.add(listing)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_seller_cannot_be_deleted_while_listing_exists(db_session: AsyncSession) -> None:
    owner = await make_user(db_session, telegram_id=700000012)
    asset = await make_asset(db_session, owner, external_id="protected-seller-nft")
    db_session.add(make_listing(owner, asset, ListingStatus.DRAFT))
    await db_session.flush()

    await db_session.delete(owner)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_verified_asset_upsert_is_idempotent_under_concurrent_syncs(
    test_database_url: str,
    migrated_database,
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    telegram_id = 799_999_991
    external_id = f"0:{uuid4().hex}{uuid4().hex}"
    owner = User(telegram_id=telegram_id, first_name="Inventory integration")
    try:
        async with session_factory.begin() as session:
            session.add(owner)
        snapshot = NFTItemSnapshot(
            address=external_id,
            initialized=True,
            index=0,
            collection_address=None,
            owner_address=f"0:{'22' * 32}",
            metadata=NFTMetadata(name="Concurrent inventory item"),
        )

        async def sync_once():
            async with session_factory.begin() as session:
                asset = await _upsert_verified_asset(
                    session,
                    owner.id,
                    "mainnet",
                    snapshot,
                )
                assert asset is not None
                return asset.id

        asset_ids = await asyncio.gather(sync_once(), sync_once())
        assert asset_ids[0] == asset_ids[1]

        async with session_factory() as session:
            assets = (
                await session.scalars(
                    select(NFTAsset).where(
                        NFTAsset.asset_type == AssetType.TON_NFT,
                        NFTAsset.external_id == external_id,
                    )
                )
            ).all()
            assert len(assets) == 1
            assert assets[0].owner_id == owner.id
            assert assets[0].verification_status is AssetVerificationStatus.VERIFIED
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                NFTAsset.__table__.delete().where(NFTAsset.external_id == external_id)
            )
            await session.execute(
                User.__table__.delete().where(User.telegram_id == telegram_id)
            )
        await engine.dispose()


async def test_verified_inventory_upsert_is_idempotent_under_concurrent_syncs(
    test_database_url: str,
    migrated_database,
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    telegram_id = 799_999_991
    external_id = f"0:{uuid4().hex}{uuid4().hex}"
    owner = User(telegram_id=telegram_id, first_name="Inventory integration")
    try:
        async with session_factory.begin() as session:
            session.add(owner)
        snapshot = NFTItemSnapshot(
            address=external_id,
            initialized=True,
            index=0,
            collection_address=None,
            owner_address=f"0:{'22' * 32}",
            metadata=NFTMetadata(name="Concurrent inventory item"),
        )

        async def sync_once():
            async with session_factory.begin() as session:
                asset = await _upsert_verified_asset(
                    session,
                    owner.id,
                    "mainnet",
                    snapshot,
                )
                assert asset is not None
                return asset.id

        asset_ids = await asyncio.gather(sync_once(), sync_once())
        assert asset_ids[0] == asset_ids[1]

        async with session_factory() as session:
            assets = (
                await session.scalars(
                    select(NFTAsset).where(
                        NFTAsset.asset_type == AssetType.TON_NFT,
                        NFTAsset.external_id == external_id,
                    )
                )
            ).all()
            assert len(assets) == 1
            assert assets[0].owner_id == owner.id
            assert assets[0].verification_status is AssetVerificationStatus.VERIFIED
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                NFTAsset.__table__.delete().where(NFTAsset.external_id == external_id)
            )
            await session.execute(
                User.__table__.delete().where(User.telegram_id == telegram_id)
            )
        await engine.dispose()
