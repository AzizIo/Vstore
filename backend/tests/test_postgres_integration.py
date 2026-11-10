from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.assets import _upsert_verified_asset
from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.models import (
    NFTItemSnapshot,
    NFTMetadata,
    VerificationResult,
    VerificationStatus,
)
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
    User,
    Wallet,
)
from app.listings.service import (
    ListingConflict,
    ListingVerificationUnavailable,
    publish_listing,
)
from app.orders.service import (
    OrderConflict,
    cancel_order,
    create_order,
    expire_pending_orders,
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
    session: AsyncSession,
    owner: User,
    external_id: str | None = None,
    *,
    item_address: str | None = None,
) -> NFTAsset:
    external_id = external_id or f"0:{uuid4().hex}{uuid4().hex}"
    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        external_id=external_id,
        item_address=item_address or f"0:{uuid4().hex}{uuid4().hex}",
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
        title="Integration listing",
    )


async def test_alembic_upgrade_applies_expected_revision(db_session: AsyncSession) -> None:
    revision = await db_session.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "0005_free_listings"


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


async def test_free_listing_migration_removes_legacy_price_columns(
    db_session: AsyncSession,
) -> None:
    rows = await db_session.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name IN ('listings', 'orders')
              AND column_name IN ('price_amount', 'price_currency')
            """
        )
    )
    assert rows.all() == []


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


async def test_concurrent_reservation_idempotency_cancellation_and_expiry(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    seller_id = uuid4()
    first_buyer_id = uuid4()
    second_buyer_id = uuid4()
    listing_id = uuid4()

    try:
        async with session_factory() as session:
            seller = await make_user(session, telegram_id=700000000 + seller_id.int % 1000000000)
            first_buyer = await make_user(
                session, telegram_id=700000000 + first_buyer_id.int % 1000000000
            )
            second_buyer = await make_user(
                session, telegram_id=700000000 + second_buyer_id.int % 1000000000
            )
            asset = await make_asset(session, seller, external_id=f"order-{listing_id}")
            wallet = Wallet(
                user_id=seller.id,
                address=f"0:{uuid4().hex}{uuid4().hex}",
                network="mainnet",
                is_verified=True,
                is_primary=True,
            )
            session.add(wallet)
            listing = make_listing(seller, asset, ListingStatus.ACTIVE)
            session.add(listing)
            await session.commit()
            seller_id, first_buyer_id, second_buyer_id, listing_id = (
                seller.id,
                first_buyer.id,
                second_buyer.id,
                listing.id,
            )

        async def attempt_order(buyer_id):
            async with session_factory() as session:
                try:
                    return await create_order(
                        session,
                        buyer_id=buyer_id,
                        listing_id=listing_id,
                        idempotency_key=f"concurrent-{buyer_id}",
                        verifier=_StaticOwnershipVerifier(session=session),
                    )
                except OrderConflict:
                    return None

        outcomes = await asyncio.gather(
            attempt_order(first_buyer_id), attempt_order(second_buyer_id)
        )
        successful_order_ids = [order_id for order_id in outcomes if order_id is not None]
        assert len(successful_order_ids) == 1
        order_id = successful_order_ids[0]
        winning_buyer_id = first_buyer_id if outcomes[0] is not None else second_buyer_id

        async with session_factory() as session:
            retry_id = await create_order(
                session,
                buyer_id=winning_buyer_id,
                listing_id=listing_id,
                idempotency_key=f"concurrent-{winning_buyer_id}",
                verifier=_StaticOwnershipVerifier(session=session),
            )
            assert retry_id == order_id
            order = await session.get(Order, order_id)
            assert order is not None
            assert order.status is OrderStatus.PENDING_PAYMENT

        async with session_factory() as session:
            await cancel_order(
                session,
                order_id=order_id,
                buyer_id=winning_buyer_id,
                now=datetime.now(UTC) + timedelta(seconds=1),
            )
            await cancel_order(
                session,
                order_id=order_id,
                buyer_id=winning_buyer_id,
                now=datetime.now(UTC) + timedelta(seconds=2),
            )

        async with session_factory() as session:
            listing = await session.get(Listing, listing_id)
            order = await session.get(Order, order_id)
            events = (
                await session.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id))
            ).all()
            assert listing is not None and listing.status == ListingStatus.ACTIVE
            assert order is not None and order.status == OrderStatus.CANCELLED
            assert len(events) == 2

        async with session_factory() as session:
            expiring_order_id = await create_order(
                session,
                buyer_id=second_buyer_id if winning_buyer_id == first_buyer_id else first_buyer_id,
                listing_id=listing_id,
                idempotency_key="expiring-order",
                verifier=_StaticOwnershipVerifier(session=session),
                now=datetime.now(UTC),
            )
            expired_count = await expire_pending_orders(
                session, now=datetime.now(UTC) + timedelta(hours=1)
            )
            assert expired_count == 1
            listing = await session.get(Listing, listing_id)
            expired_order = await session.get(Order, expiring_order_id)
            assert listing is not None and listing.status == ListingStatus.ACTIVE
            assert expired_order is not None and expired_order.status == OrderStatus.EXPIRED

        async with session_factory() as session:
            await session.execute(
                text(
                    "DELETE FROM order_events WHERE order_id IN "
                    "(SELECT id FROM orders WHERE listing_id = :listing_id)"
                ),
                {"listing_id": listing_id},
            )
            await session.execute(
                text(
                    "DELETE FROM telegram_notification_outbox WHERE order_id IN "
                    "(SELECT id FROM orders WHERE listing_id = :listing_id)"
                ),
                {"listing_id": listing_id},
            )
            await session.execute(
                text("DELETE FROM orders WHERE listing_id = :listing_id"),
                {"listing_id": listing_id},
            )
            await session.execute(
                text("DELETE FROM listings WHERE id = :listing_id"), {"listing_id": listing_id}
            )
            await session.execute(
                text("DELETE FROM nft_assets WHERE external_id = :external_id"),
                {"external_id": f"order-{listing_id}"},
            )
            await session.execute(
                text(
                    "DELETE FROM users WHERE id IN "
                    "(:seller_id, :first_buyer_id, :second_buyer_id)"
                ),
                {
                    "seller_id": seller_id,
                    "first_buyer_id": first_buyer_id,
                    "second_buyer_id": second_buyer_id,
                },
            )
            await session.commit()
    finally:
        await engine.dispose()



def _publishable_item_address() -> str:
    return f"0:{uuid4().hex}{uuid4().hex}"


def _publishable_wallet_address() -> str:
    return f"0:{uuid4().hex}{uuid4().hex}"


def _canonical(address: str) -> str:
    """Return a raw TON address; provider snapshots are always canonical."""

    try:
        return normalize_address(address)
    except AddressError:
        return f"0:{uuid4().hex}{uuid4().hex}"


class _StaticOwnershipVerifier:
    def __init__(
        self,
        *,
        session: AsyncSession,
        status: VerificationStatus = VerificationStatus.VERIFIED,
        callback=None,
    ) -> None:
        self.session = session
        self.status = status
        self.callback = callback
        self.transaction_states: list[bool] = []
        self.calls: list[tuple[str, str]] = []

    async def verify(self, item_address: str, expected_owner_address: str):
        self.transaction_states.append(self.session.in_transaction())
        self.calls.append((item_address, expected_owner_address))
        if self.callback is not None:
            await self.callback()
        return VerificationResult(
            status=self.status,
            item_address=_canonical(item_address),
            owner_address=_canonical(expected_owner_address),
            expected_owner_address=_canonical(expected_owner_address),
        )


async def _create_publishable_listing(
    session: AsyncSession,
    *,
    status: ListingStatus = ListingStatus.DRAFT,
    telegram_id: int | None = None,
    item_address: str | None = None,
) -> tuple[User, NFTAsset, Wallet, Listing]:
    owner = await make_user(
        session,
        telegram_id=telegram_id or (700_000_000 + uuid4().int % 1_000_000_000),
    )
    asset_address = item_address or _publishable_item_address()
    wallet_address = _publishable_wallet_address()
    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        network="mainnet",
        external_id=asset_address,
        item_address=asset_address,
        owner_id=owner.id,
        name="Publishable NFT",
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    wallet = Wallet(
        user_id=owner.id,
        address=wallet_address,
        network="mainnet",
        is_verified=True,
        is_primary=True,
    )
    session.add_all([asset, wallet])
    await session.flush()
    listing = Listing(
        asset_id=asset.id,
        seller_id=owner.id,
        status=status,
        title="Seller draft",
    )
    session.add(listing)
    await session.flush()
    return owner, asset, wallet, listing


async def _cleanup_publishable_data(
    session_factory,
    *,
    listing_ids: list,
    asset_ids: list,
    wallet_ids: list,
    user_ids: list,
) -> None:
    async with session_factory.begin() as session:
        if listing_ids:
            await session.execute(
                Listing.__table__.delete().where(Listing.id.in_(listing_ids))
            )
        if asset_ids:
            await session.execute(
                NFTAsset.__table__.delete().where(NFTAsset.id.in_(asset_ids))
            )
        if wallet_ids:
            await session.execute(
                Wallet.__table__.delete().where(Wallet.id.in_(wallet_ids))
            )
        if user_ids:
            await session.execute(User.__table__.delete().where(User.id.in_(user_ids)))


async def test_publish_listing_rechecks_ownership_outside_database_transaction(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        owner, asset, wallet, draft = await _create_publishable_listing(session)

    try:
        async with session_factory() as session:
            verifier = _StaticOwnershipVerifier(session=session)
            published = await publish_listing(
                session,
                listing_id=draft.id,
                seller_id=owner.id,
                verifier=verifier,
            )

        assert published.status is ListingStatus.ACTIVE
        assert verifier.calls == [(asset.item_address, wallet.address)]
        assert verifier.transaction_states == [False]

        async with session_factory() as session:
            persisted = await session.get(Listing, draft.id)
            assert persisted is not None
            assert persisted.status is ListingStatus.ACTIVE
    finally:
        await _cleanup_publishable_data(
            session_factory,
            listing_ids=[draft.id],
            asset_ids=[asset.id],
            wallet_ids=[wallet.id],
            user_ids=[owner.id],
        )
        await engine.dispose()


async def test_publish_listing_rejects_owner_change_during_provider_check(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        owner, asset, wallet, draft = await _create_publishable_listing(session)
        other_owner = await make_user(
            session,
            telegram_id=700_000_000 + uuid4().int % 1_000_000_000,
        )

    async def transfer_asset() -> None:
        async with session_factory.begin() as session:
            current_asset = await session.get(NFTAsset, asset.id)
            assert current_asset is not None
            current_asset.owner_id = other_owner.id

    try:
        async with session_factory() as session:
            verifier = _StaticOwnershipVerifier(session=session, callback=transfer_asset)
            with pytest.raises(ListingConflict, match="ownership or verification state changed"):
                await publish_listing(
                    session,
                    listing_id=draft.id,
                    seller_id=owner.id,
                    verifier=verifier,
                )
            assert verifier.transaction_states == [False]

        async with session_factory() as session:
            persisted_listing = await session.get(Listing, draft.id)
            persisted_asset = await session.get(NFTAsset, asset.id)
            assert persisted_listing is not None
            assert persisted_listing.status is ListingStatus.DRAFT
            assert persisted_asset is not None
            assert persisted_asset.owner_id == other_owner.id
    finally:
        await _cleanup_publishable_data(
            session_factory,
            listing_ids=[draft.id],
            asset_ids=[asset.id],
            wallet_ids=[wallet.id],
            user_ids=[owner.id, other_owner.id],
        )
        await engine.dispose()


async def test_publish_listing_fails_closed_when_ton_provider_is_unavailable(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        owner, asset, wallet, draft = await _create_publishable_listing(session)

    try:
        async with session_factory() as session:
            verifier = _StaticOwnershipVerifier(
                session=session,
                status=VerificationStatus.PROVIDER_UNAVAILABLE,
            )
            with pytest.raises(ListingVerificationUnavailable):
                await publish_listing(
                    session,
                    listing_id=draft.id,
                    seller_id=owner.id,
                    verifier=verifier,
                )
            assert verifier.transaction_states == [False]

        async with session_factory() as session:
            persisted = await session.get(Listing, draft.id)
            assert persisted is not None
            assert persisted.status is ListingStatus.DRAFT
    finally:
        await _cleanup_publishable_data(
            session_factory,
            listing_ids=[draft.id],
            asset_ids=[asset.id],
            wallet_ids=[wallet.id],
            user_ids=[owner.id],
        )
        await engine.dispose()


async def test_concurrent_publication_of_two_drafts_for_one_nft_has_one_winner(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        owner, asset, wallet, first_draft = await _create_publishable_listing(session)
        second_draft = make_listing(owner, asset, ListingStatus.DRAFT)
        session.add(second_draft)
        await session.flush()

    ready = asyncio.Event()
    call_count = 0
    call_lock = asyncio.Lock()

    class _BarrierVerifier:
        async def verify(self, item_address: str, expected_owner_address: str):
            nonlocal call_count
            assert item_address == asset.item_address
            assert expected_owner_address == wallet.address
            async with call_lock:
                call_count += 1
                if call_count == 2:
                    ready.set()
            await ready.wait()
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                item_address=item_address,
                owner_address=expected_owner_address,
                expected_owner_address=expected_owner_address,
            )

    async def attempt(listing_id):
        async with session_factory() as session:
            try:
                return await publish_listing(
                    session,
                    listing_id=listing_id,
                    seller_id=owner.id,
                    verifier=_BarrierVerifier(),
                )
            except ListingConflict as exc:
                return exc

    try:
        results = await asyncio.gather(attempt(first_draft.id), attempt(second_draft.id))
        successes = [result for result in results if isinstance(result, Listing)]
        conflicts = [result for result in results if isinstance(result, ListingConflict)]
        assert len(successes) == 1
        assert len(conflicts) == 1

        async with session_factory() as session:
            active_ids = (
                await session.scalars(
                    select(Listing.id).where(
                        Listing.asset_id == asset.id,
                        Listing.status == ListingStatus.ACTIVE,
                    )
                )
            ).all()
            assert len(active_ids) == 1
    finally:
        await _cleanup_publishable_data(
            session_factory,
            listing_ids=[first_draft.id, second_draft.id],
            asset_ids=[asset.id],
            wallet_ids=[wallet.id],
            user_ids=[owner.id],
        )
        await engine.dispose()


async def test_publish_listing_rejects_stale_foreign_and_unsupported_assets(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        owner, verified_asset, wallet, verified_draft = await _create_publishable_listing(session)
        other_owner = await make_user(
            session,
            telegram_id=700_000_000 + uuid4().int % 1_000_000_000,
        )
        stale_asset = NFTAsset(
            asset_type=AssetType.TON_NFT,
            network="mainnet",
            external_id=_publishable_item_address(),
            item_address=_publishable_item_address(),
            owner_id=owner.id,
            verification_status=AssetVerificationStatus.STALE,
        )
        foreign_asset = NFTAsset(
            asset_type=AssetType.TON_NFT,
            network="mainnet",
            external_id=_publishable_item_address(),
            item_address=_publishable_item_address(),
            owner_id=other_owner.id,
            verification_status=AssetVerificationStatus.VERIFIED,
        )
        unsupported_asset = NFTAsset(
            asset_type=AssetType.TELEGRAM_GIFT,
            network="mainnet",
            external_id=f"gift-{uuid4()}",
            owner_id=owner.id,
            verification_status=AssetVerificationStatus.VERIFIED,
        )
        session.add_all([stale_asset, foreign_asset, unsupported_asset])
        await session.flush()
        stale_draft = make_listing(owner, stale_asset, ListingStatus.DRAFT)
        foreign_draft = make_listing(owner, foreign_asset, ListingStatus.DRAFT)
        unsupported_draft = make_listing(owner, unsupported_asset, ListingStatus.DRAFT)
        session.add_all([stale_draft, foreign_draft, unsupported_draft])
        await session.flush()

    class _VerifierMustNotRun:
        async def verify(self, item_address: str, expected_owner_address: str):
            raise AssertionError("ineligible asset must be rejected before provider access")

    try:
        for listing_id in (stale_draft.id, foreign_draft.id, unsupported_draft.id):
            async with session_factory() as session:
                with pytest.raises(ListingConflict):
                    await publish_listing(
                        session,
                        listing_id=listing_id,
                        seller_id=owner.id,
                        verifier=_VerifierMustNotRun(),
                    )
        async with session_factory() as session:
            for listing_id in (stale_draft.id, foreign_draft.id, unsupported_draft.id):
                listing = await session.get(Listing, listing_id)
                assert listing is not None
                assert listing.status is ListingStatus.DRAFT
    finally:
        await _cleanup_publishable_data(
            session_factory,
            listing_ids=[
                verified_draft.id,
                stale_draft.id,
                foreign_draft.id,
                unsupported_draft.id,
            ],
            asset_ids=[
                verified_asset.id,
                stale_asset.id,
                foreign_asset.id,
                unsupported_asset.id,
            ],
            wallet_ids=[wallet.id],
            user_ids=[owner.id, other_owner.id],
        )
        await engine.dispose()


async def test_publish_listing_rejects_provider_owner_mismatch(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        owner, asset, wallet, draft = await _create_publishable_listing(session)

    try:
        async with session_factory() as session:
            verifier = _StaticOwnershipVerifier(
                session=session,
                status=VerificationStatus.OWNER_MISMATCH,
            )
            with pytest.raises(ListingConflict, match="Current NFT ownership"):
                await publish_listing(
                    session,
                    listing_id=draft.id,
                    seller_id=owner.id,
                    verifier=verifier,
                )
            assert verifier.transaction_states == [False]

        async with session_factory() as session:
            persisted = await session.get(Listing, draft.id)
            assert persisted is not None
            assert persisted.status is ListingStatus.DRAFT
    finally:
        await _cleanup_publishable_data(
            session_factory,
            listing_ids=[draft.id],
            asset_ids=[asset.id],
            wallet_ids=[wallet.id],
            user_ids=[owner.id],
        )
        await engine.dispose()
