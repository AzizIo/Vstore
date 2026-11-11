from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
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
from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.delivery import DeliveryEvidenceResult, DeliveryEvidenceStatus
from app.assets.ton_nft.models import (
    NFTItemSnapshot,
    NFTMetadata,
    VerificationResult,
    VerificationStatus,
)
from app.assets.ton_nft.observer import (
    apply_delivery_observation,
    claim_due_delivery_attempts,
    run_delivery_observer_pass,
)
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
    PriceCurrency,
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
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        title="Integration listing",
    )


ALEMBIC_CONFIG_PATH = str(Path(__file__).resolve().parents[1] / "alembic.ini")


async def test_alembic_upgrade_applies_expected_revision(db_session: AsyncSession) -> None:
    revision = await db_session.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "0006_delivery_observer_leases"


async def test_downgrade_refuses_delivery_event_history_without_attempt_rows(
    test_database_url: str,
    migrated_database,
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    seller_id = buyer_id = asset_id = listing_id = order_id = None
    try:
        async with session_factory() as session:
            seller = await make_user(session, telegram_id=719100001)
            buyer = await make_user(session, telegram_id=719100002)
            asset = await make_asset(session, seller)
            listing = make_listing(seller, asset, ListingStatus.RESERVED)
            session.add(listing)
            await session.flush()
            now = datetime.now(UTC)
            order = Order(
                listing_id=listing.id,
                buyer_id=buyer.id,
                seller_id=seller.id,
                idempotency_key=f"downgrade-event-{uuid4()}",
                status=OrderStatus.RESERVED,
                price_amount=Decimal("1.250000000"),
                price_currency=PriceCurrency.TON,
                expires_at=now + timedelta(minutes=15),
            )
            session.add(order)
            await session.flush()
            session.add(
                OrderEvent(
                    order_id=order.id,
                    from_status=OrderStatus.RESERVED,
                    to_status=OrderStatus.AWAITING_TRANSFER,
                    actor_id=seller.id,
                    actor_type="seller",
                )
            )
            await session.commit()
            seller_id, buyer_id = seller.id, buyer.id
            asset_id, listing_id, order_id = asset.id, listing.id, order.id

        await engine.dispose()
        config = Config(ALEMBIC_CONFIG_PATH)
        with pytest.raises(RuntimeError, match="delivery events"):
            await asyncio.to_thread(
                command.downgrade,
                config,
                "0004_tg_notif_outbox",
            )

        engine = create_async_engine(test_database_url, pool_pre_ping=True)
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "0006_delivery_observer_leases"

        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM order_events WHERE order_id = :order_id"),
                {"order_id": order_id},
            )
            await connection.execute(
                text("DELETE FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            )
            await connection.execute(
                text("DELETE FROM listings WHERE id = :listing_id"),
                {"listing_id": listing_id},
            )
            await connection.execute(
                text("DELETE FROM nft_assets WHERE id = :asset_id"),
                {"asset_id": asset_id},
            )
            await connection.execute(
                text("DELETE FROM users WHERE id IN (:seller_id, :buyer_id)"),
                {"seller_id": seller_id, "buyer_id": buyer_id},
            )
    finally:
        await engine.dispose()


async def test_delivery_attempt_keeps_wallet_address_snapshots_after_unlink(
    db_session: AsyncSession,
) -> None:
    seller = await make_user(db_session, telegram_id=710000001)
    buyer = await make_user(db_session, telegram_id=710000002)
    asset = await make_asset(db_session, seller)
    seller_wallet = Wallet(
        user_id=seller.id,
        address=f"0:{uuid4().hex}{uuid4().hex}",
        network="mainnet",
        is_verified=True,
        is_primary=True,
    )
    buyer_wallet = Wallet(
        user_id=buyer.id,
        address=f"0:{uuid4().hex}{uuid4().hex}",
        network="mainnet",
        is_verified=True,
        is_primary=True,
    )
    db_session.add_all([seller_wallet, buyer_wallet])
    await db_session.flush()
    listing = make_listing(seller, asset, ListingStatus.RESERVED)
    db_session.add(listing)
    await db_session.flush()

    now = datetime.now(UTC)
    order = Order(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        idempotency_key=f"delivery-snapshot-{uuid4()}",
        status=OrderStatus.RESERVED,
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        expires_at=now + timedelta(minutes=15),
    )
    db_session.add(order)
    await db_session.flush()

    seller_address = seller_wallet.address
    buyer_address = buyer_wallet.address
    attempt = OrderDeliveryAttempt(
        order_id=order.id,
        attempt_number=1,
        status=OrderDeliveryAttemptStatus.PREPARED,
        network="mainnet",
        item_address=asset.item_address or asset.external_id,
        seller_wallet_id=seller_wallet.id,
        seller_address_snapshot=seller_address,
        buyer_wallet_id=buyer_wallet.id,
        buyer_address_snapshot=buyer_address,
        query_id=Decimal("18446744073709551615"),
        prepared_at=now,
        deadline=now + timedelta(minutes=15),
    )
    db_session.add(attempt)
    await db_session.flush()

    await db_session.delete(seller_wallet)
    await db_session.delete(buyer_wallet)
    await db_session.flush()
    await db_session.refresh(attempt)

    assert attempt.seller_wallet_id is None
    assert attempt.buyer_wallet_id is None
    assert attempt.seller_address_snapshot == seller_address
    assert attempt.buyer_address_snapshot == buyer_address
    assert attempt.query_id == Decimal("18446744073709551615")
    assert attempt.status is OrderDeliveryAttemptStatus.PREPARED


async def test_delivery_attempt_snapshot_columns_cannot_be_rewritten(
    db_session: AsyncSession,
) -> None:
    seller = await make_user(db_session, telegram_id=710000005)
    buyer = await make_user(db_session, telegram_id=710000006)
    asset = await make_asset(db_session, seller)
    now = datetime.now(UTC)
    listing = make_listing(seller, asset, ListingStatus.RESERVED)
    db_session.add(listing)
    await db_session.flush()
    order = Order(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        idempotency_key=f"delivery-immutable-{uuid4()}",
        status=OrderStatus.AWAITING_TRANSFER,
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        expires_at=now + timedelta(minutes=15),
    )
    db_session.add(order)
    await db_session.flush()
    attempt = OrderDeliveryAttempt(
        order_id=order.id,
        attempt_number=1,
        status=OrderDeliveryAttemptStatus.PREPARED,
        network="mainnet",
        item_address=asset.item_address or asset.external_id,
        seller_address_snapshot=f"0:{uuid4().hex}{uuid4().hex}",
        buyer_address_snapshot=f"0:{uuid4().hex}{uuid4().hex}",
        query_id=Decimal("7"),
        prepared_at=now,
        deadline=now + timedelta(minutes=15),
    )
    db_session.add(attempt)
    await db_session.flush()

    attempt.buyer_address_snapshot = f"0:{uuid4().hex}{uuid4().hex}"
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_delivery_attempt_active_and_verified_transfer_indexes_are_enforced(
    db_session: AsyncSession,
) -> None:
    seller = await make_user(db_session, telegram_id=710000003)
    buyer = await make_user(db_session, telegram_id=710000004)
    asset = await make_asset(db_session, seller)
    seller_wallet = Wallet(
        user_id=seller.id,
        address=f"0:{uuid4().hex}{uuid4().hex}",
        network="mainnet",
        is_verified=True,
    )
    buyer_wallet = Wallet(
        user_id=buyer.id,
        address=f"0:{uuid4().hex}{uuid4().hex}",
        network="mainnet",
        is_verified=True,
    )
    db_session.add_all([seller_wallet, buyer_wallet])
    await db_session.flush()
    listing = make_listing(seller, asset, ListingStatus.RESERVED)
    db_session.add(listing)
    await db_session.flush()
    now = datetime.now(UTC)
    order = Order(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        idempotency_key=f"delivery-index-{uuid4()}",
        status=OrderStatus.OBSERVING_TRANSFER,
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        expires_at=now + timedelta(minutes=15),
    )
    db_session.add(order)
    await db_session.flush()

    def make_attempt(number: int, status: OrderDeliveryAttemptStatus) -> OrderDeliveryAttempt:
        return OrderDeliveryAttempt(
            order_id=order.id,
            attempt_number=number,
            status=status,
            network="mainnet",
            item_address=asset.item_address or asset.external_id,
            seller_wallet_id=seller_wallet.id,
            seller_address_snapshot=seller_wallet.address,
            buyer_wallet_id=buyer_wallet.id,
            buyer_address_snapshot=buyer_wallet.address,
            query_id=Decimal(number),
            prepared_at=now,
            deadline=now + timedelta(minutes=15),
        )

    db_session.add(make_attempt(1, OrderDeliveryAttemptStatus.PREPARED))
    await db_session.flush()
    nested = await db_session.begin_nested()
    db_session.add(make_attempt(2, OrderDeliveryAttemptStatus.OBSERVING))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await nested.rollback()

    # The verified-transfer partial unique index: two distinct attempt numbers
    # claiming the same verified network/item/transaction_hash for this order
    # must be rejected, so one on-chain transfer cannot verify twice.
    verified_hash = f"0:{uuid4().hex}{uuid4().hex}"
    db_session.add(
        OrderDeliveryAttempt(
            order_id=order.id,
            attempt_number=3,
            status=OrderDeliveryAttemptStatus.VERIFIED,
            network="mainnet",
            item_address=asset.item_address or asset.external_id,
            seller_address_snapshot=seller_wallet.address,
            buyer_address_snapshot=buyer_wallet.address,
            query_id=Decimal("3"),
            transaction_hash=verified_hash,
            verified_at=now + timedelta(minutes=1),
            prepared_at=now,
            deadline=now + timedelta(minutes=15),
        )
    )
    await db_session.flush()
    nested = await db_session.begin_nested()
    db_session.add(
        OrderDeliveryAttempt(
            order_id=order.id,
            attempt_number=4,
            status=OrderDeliveryAttemptStatus.VERIFIED,
            network="mainnet",
            item_address=asset.item_address or asset.external_id,
            seller_address_snapshot=seller_wallet.address,
            buyer_address_snapshot=buyer_wallet.address,
            query_id=Decimal("4"),
            transaction_hash=verified_hash,
            verified_at=now + timedelta(minutes=1),
            prepared_at=now,
            deadline=now + timedelta(minutes=15),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await nested.rollback()


async def test_verified_delivery_attempt_requires_provider_evidence(
    db_session: AsyncSession,
) -> None:
    seller = await make_user(db_session, telegram_id=710000007)
    buyer = await make_user(db_session, telegram_id=710000008)
    asset = await make_asset(db_session, seller)
    listing = make_listing(seller, asset, ListingStatus.RESERVED)
    db_session.add(listing)
    await db_session.flush()
    now = datetime.now(UTC)
    order = Order(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        idempotency_key=f"verified-evidence-{uuid4()}",
        status=OrderStatus.OBSERVING_TRANSFER,
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        expires_at=now + timedelta(minutes=15),
    )
    db_session.add(order)
    await db_session.flush()

    def make_verified_attempt(
        number: int,
        *,
        transaction_hash: str | None,
        verified_at: datetime | None,
    ) -> OrderDeliveryAttempt:
        return OrderDeliveryAttempt(
            order_id=order.id,
            attempt_number=number,
            status=OrderDeliveryAttemptStatus.VERIFIED,
            network="mainnet",
            item_address=asset.item_address or asset.external_id,
            seller_address_snapshot=f"0:{uuid4().hex}{uuid4().hex}",
            buyer_address_snapshot=f"0:{uuid4().hex}{uuid4().hex}",
            query_id=Decimal(number),
            transaction_hash=transaction_hash,
            verified_at=verified_at,
            prepared_at=now,
            deadline=now + timedelta(minutes=15),
        )

    # A verified row without a transaction hash and verified_at is malformed:
    # it would bypass the verified-transfer deduplication guard entirely.
    nested = await db_session.begin_nested()
    db_session.add(make_verified_attempt(1, transaction_hash=None, verified_at=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await nested.rollback()

    # A hash without a verification timestamp is equally unverifiable evidence.
    nested = await db_session.begin_nested()
    db_session.add(
        make_verified_attempt(2, transaction_hash=f"0:{uuid4().hex}", verified_at=None)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await nested.rollback()

    # Fully evidenced attempts remain persistable.
    db_session.add(
        make_verified_attempt(
            3,
            transaction_hash=f"0:{uuid4().hex}",
            verified_at=now + timedelta(minutes=1),
        )
    )
    await db_session.flush()


async def test_legacy_reservation_rows_are_renamed_without_losing_order_history(
    test_database_url: str,
    migrated_database,
) -> None:
    config = Config(ALEMBIC_CONFIG_PATH)
    await asyncio.to_thread(command.downgrade, config, "0004_tg_notif_outbox")
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    user_seller, user_buyer, asset_id, listing_id, order_id, event_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    try:
        now = datetime.now(UTC)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, telegram_id, first_name, is_blocked) "
                    "VALUES (:id, :telegram_id, :first_name, false)"
                ),
                [
                    {"id": user_seller, "telegram_id": 719000001, "first_name": "Legacy seller"},
                    {"id": user_buyer, "telegram_id": 719000002, "first_name": "Legacy buyer"},
                ],
            )
            await connection.execute(
                text(
                    "INSERT INTO nft_assets (id, asset_type, network, external_id, owner_id, "
                    "verification_status) VALUES (:id, 'ton_nft', 'mainnet', :external_id, "
                    ":owner_id, 'verified')"
                ),
                {
                    "id": asset_id,
                    "external_id": f"legacy:{uuid4()}",
                    "owner_id": user_seller,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO listings (id, asset_id, seller_id, status, price_amount, "
                    "price_currency) VALUES (:id, :asset_id, :seller_id, 'reserved', "
                    "12.500000000, 'TON')"
                ),
                {"id": listing_id, "asset_id": asset_id, "seller_id": user_seller},
            )
            await connection.execute(
                text(
                    "INSERT INTO orders (id, listing_id, buyer_id, seller_id, idempotency_key, "
                    "status, price_amount, price_currency, expires_at) VALUES (:id, :listing_id, "
                    ":buyer_id, :seller_id, :idempotency_key, 'pending_payment', "
                    "12.500000000, 'TON', :expires_at)"
                ),
                {
                    "id": order_id,
                    "listing_id": listing_id,
                    "buyer_id": user_buyer,
                    "seller_id": user_seller,
                    "idempotency_key": "legacy-order-idempotency",
                    "expires_at": now + timedelta(minutes=15),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO order_events (id, order_id, from_status, to_status, actor_id, "
                    "actor_type) VALUES (:id, :order_id, NULL, 'pending_payment', "
                    ":actor_id, 'buyer')"
                ),
                {"id": event_id, "order_id": order_id, "actor_id": user_buyer},
            )

        await engine.dispose()
        await asyncio.to_thread(command.upgrade, config, "head")
        engine = create_async_engine(test_database_url, pool_pre_ping=True)
        async with engine.connect() as connection:
            order = (
                await connection.execute(
                    text(
                        "SELECT status, price_amount, price_currency, idempotency_key "
                        "FROM orders WHERE id = :id"
                    ),
                    {"id": order_id},
                )
            ).one()
            event = (
                await connection.execute(
                    text(
                        "SELECT from_status, to_status, actor_type FROM order_events "
                        "WHERE id = :id"
                    ),
                    {"id": event_id},
                )
            ).one()
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "0006_delivery_observer_leases"
            assert order.status == "reserved"
            assert order.price_amount == Decimal("12.500000000")
            assert order.price_currency == "TON"
            assert order.idempotency_key == "legacy-order-idempotency"
            assert event.from_status is None
            assert event.to_status == "reserved"
            assert event.actor_type == "buyer"
        # Remove the committed fixture rows: they hold an open listing, which
        # must not leak into subsequent integration tests sharing the database.
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM order_events WHERE order_id = :order_id"),
                {"order_id": order_id},
            )
            await connection.execute(
                text("DELETE FROM telegram_notification_outbox WHERE order_id = :order_id"),
                {"order_id": order_id},
            )
            await connection.execute(
                text("DELETE FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            )
            await connection.execute(
                text("DELETE FROM listings WHERE id = :listing_id"),
                {"listing_id": listing_id},
            )
            await connection.execute(
                text("DELETE FROM nft_assets WHERE id = :asset_id"),
                {"asset_id": asset_id},
            )
            await connection.execute(
                text("DELETE FROM users WHERE id IN (:seller_id, :buyer_id)"),
                {"seller_id": user_seller, "buyer_id": user_buyer},
            )
    finally:
        await engine.dispose()
        await asyncio.to_thread(command.upgrade, config, "head")


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
            listing = await session.get(Listing, listing_id)
            assert listing is not None
            listing.price_amount = Decimal("99")
            await session.commit()

        async with session_factory() as session:
            order = await session.get(Order, order_id)
            assert order is not None and order.price_amount == Decimal("1.250000000")

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
        price_amount=Decimal("1.25"),
        price_currency=PriceCurrency.TON,
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


async def test_upsert_verified_asset_listing_guard_is_scoped_to_conflicting_asset(
    db_session: AsyncSession,
) -> None:
    owner = await make_user(
        db_session,
        telegram_id=800_000_000 + uuid4().int % 100_000_000,
    )
    sync_owner = await make_user(
        db_session,
        telegram_id=900_000_000 + uuid4().int % 100_000_000,
    )
    address_a = f"0:{uuid4().hex}{uuid4().hex}"
    address_b = f"0:{uuid4().hex}{uuid4().hex}"
    original_attributes = ({"trait_type": "version", "value": "original"},)

    original_a = NFTItemSnapshot(
        address=address_a,
        initialized=True,
        index=1,
        collection_address=None,
        owner_address="0:owner-a",
        metadata=NFTMetadata(
            name="NFT A original",
            description="A protected description",
            image="https://example.test/a-original.png",
            attributes=original_attributes,
        ),
    )
    original_b = NFTItemSnapshot(
        address=address_b,
        initialized=True,
        index=2,
        collection_address=None,
        owner_address="0:owner-b",
        metadata=NFTMetadata(
            name="NFT B original",
            description="B old description",
            image="https://example.test/b-original.png",
            attributes=original_attributes,
        ),
    )
    asset_a = await _upsert_verified_asset(db_session, owner.id, "mainnet", original_a)
    asset_b = await _upsert_verified_asset(db_session, owner.id, "mainnet", original_b)
    assert asset_a is not None
    assert asset_b is not None

    db_session.add(make_listing(owner, asset_a, ListingStatus.ACTIVE))
    await db_session.flush()

    refreshed_a = NFTItemSnapshot(
        address=address_a,
        initialized=True,
        index=1,
        collection_address=None,
        owner_address="0:owner-a-refreshed",
        metadata=NFTMetadata(
            name="NFT A must stay protected",
            description="Must not overwrite A",
            image="https://example.test/a-refreshed.png",
            attributes=({"trait_type": "version", "value": "replacement"},),
        ),
    )
    refreshed_b = NFTItemSnapshot(
        address=address_b,
        initialized=True,
        index=2,
        collection_address=None,
        owner_address="0:owner-b-refreshed",
        metadata=NFTMetadata(
            name="NFT B refreshed",
            description="B updated while A is listed",
            image="https://example.test/b-refreshed.png",
            attributes=({"trait_type": "version", "value": "refreshed"},),
        ),
    )

    blocked = await _upsert_verified_asset(db_session, sync_owner.id, "mainnet", refreshed_a)
    updated_b = await _upsert_verified_asset(db_session, sync_owner.id, "mainnet", refreshed_b)

    assert blocked is None
    assert updated_b is not None
    assert updated_b.id == asset_b.id
    await db_session.refresh(updated_b)
    assert updated_b.owner_id == sync_owner.id
    assert updated_b.name == "NFT B refreshed"
    assert updated_b.description == "B updated while A is listed"
    assert updated_b.image_url == "https://example.test/b-refreshed.png"
    assert updated_b.metadata_json == {
        "attributes": [{"trait_type": "version", "value": "refreshed"}]
    }

    await db_session.refresh(asset_a)
    await db_session.refresh(asset_b)
    assert asset_a.owner_id == owner.id
    assert asset_a.name == "NFT A original"
    assert asset_a.description == "A protected description"
    assert asset_a.image_url == "https://example.test/a-original.png"
    assert asset_a.metadata_json == {
        "attributes": [{"trait_type": "version", "value": "original"}]
    }
    assert asset_b.owner_id == sync_owner.id
    assert asset_b.name == "NFT B refreshed"
    assert asset_b.description == "B updated while A is listed"
    assert asset_b.image_url == "https://example.test/b-refreshed.png"



async def _create_observer_fixture(session: AsyncSession):
    seller = await make_user(session, telegram_id=730_000_000 + uuid4().int % 100_000_000)
    buyer = await make_user(session, telegram_id=740_000_000 + uuid4().int % 100_000_000)
    item_address = "0:" + "a1" * 32
    seller_address = "0:" + "b2" * 32
    buyer_address = "0:" + "c3" * 32
    asset = await make_asset(
        session,
        seller,
        external_id=item_address,
        item_address=item_address,
    )
    listing = make_listing(seller, asset, ListingStatus.RESERVED)
    session.add(listing)
    await session.flush()
    now = datetime.now(UTC)
    order = Order(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        idempotency_key=f"observer-{uuid4()}",
        status=OrderStatus.AWAITING_TRANSFER,
        price_amount=Decimal("1.25"),
        price_currency=PriceCurrency.TON,
        expires_at=now + timedelta(minutes=30),
    )
    session.add(order)
    await session.flush()
    attempt = OrderDeliveryAttempt(
        order_id=order.id,
        attempt_number=1,
        status=OrderDeliveryAttemptStatus.PREPARED,
        network="mainnet",
        item_address=item_address,
        seller_address_snapshot=seller_address,
        buyer_address_snapshot=buyer_address,
        query_id=Decimal("123456"),
        prepared_at=now,
        deadline=now + timedelta(minutes=15),
    )
    session.add(attempt)
    await session.flush()
    return seller, buyer, asset, listing, order, attempt, now


async def _cleanup_observer_fixture(
    session_factory,
    *,
    seller_id,
    buyer_id,
    asset_id,
    listing_id,
    order_id,
    attempt_id,
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            OrderEvent.__table__.delete().where(OrderEvent.order_id == order_id)
        )
        await session.execute(
            OrderDeliveryAttempt.__table__.delete().where(
                OrderDeliveryAttempt.id == attempt_id
            )
        )
        await session.execute(Order.__table__.delete().where(Order.id == order_id))
        await session.execute(Listing.__table__.delete().where(Listing.id == listing_id))
        await session.execute(NFTAsset.__table__.delete().where(NFTAsset.id == asset_id))
        await session.execute(User.__table__.delete().where(User.id.in_([seller_id, buyer_id])))


async def test_delivery_observer_verifies_and_completes_only_exact_finalized_evidence(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, listing, order, attempt, now = await _create_observer_fixture(session)
    try:
        class _FinalizedProvider:
            async def verify_transfer(self, intent):
                assert intent.item_address == asset.item_address
                assert intent.network == "mainnet"
                assert intent.seller_wallet_address == "0:" + "b2" * 32
                assert intent.buyer_wallet_address == "0:" + "c3" * 32
                assert intent.query_id == 123456
                return DeliveryEvidenceResult(
                    status=DeliveryEvidenceStatus.VERIFIED_FINALIZED,
                    item_address=intent.item_address,
                    network=intent.network,
                    seller_wallet_address=intent.seller_wallet_address,
                    buyer_wallet_address=intent.buyer_wallet_address,
                    query_id=intent.query_id,
                    transaction_hash="ab" * 32,
                    trace_id="cd" * 32,
                    masterchain_seqno=123456,
                )

            async def aclose(self):
                return None

        result = await run_delivery_observer_pass(
            session_factory,
            now=now,
            provider_factory=lambda _network: _FinalizedProvider(),
        )
        assert result.claimed == 1
        assert result.verified == 1
        assert result.retried == 0
        assert result.manual_review == 0

        async with session_factory() as session:
            persisted_order = await session.get(Order, order.id)
            persisted_listing = await session.get(Listing, listing.id)
            persisted_asset = await session.get(NFTAsset, asset.id)
            persisted_attempt = await session.get(OrderDeliveryAttempt, attempt.id)
            assert persisted_order is not None
            assert persisted_order.status is OrderStatus.COMPLETED
            assert persisted_listing is not None
            assert persisted_listing.status is ListingStatus.SOLD
            assert persisted_asset is not None
            assert persisted_asset.owner_id == buyer.id
            assert persisted_attempt is not None
            assert persisted_attempt.status is OrderDeliveryAttemptStatus.VERIFIED
            assert persisted_attempt.transaction_hash == "ab" * 32
            assert persisted_attempt.masterchain_seqno == 123456
            completed_events = (
                await session.scalars(
                    select(OrderEvent).where(
                        OrderEvent.order_id == order.id,
                        OrderEvent.to_status == OrderStatus.COMPLETED,
                    )
                )
            ).all()
            assert len(completed_events) == 1
    finally:
        await _cleanup_observer_fixture(
            session_factory,
            seller_id=seller.id,
            buyer_id=buyer.id,
            asset_id=asset.id,
            listing_id=listing.id,
            order_id=order.id,
            attempt_id=attempt.id,
        )
        await engine.dispose()


async def test_delivery_observer_lease_fences_stale_worker_and_retries_inconclusive_evidence(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, listing, order, attempt, now = await _create_observer_fixture(session)
    try:
        async with session_factory() as session:
            first_claims = await claim_due_delivery_attempts(session, now=now)
            assert len(first_claims) == 1
            first_claim = first_claims[0]
            assert await claim_due_delivery_attempts(session, now=now) == []

        reclaimed_at = first_claim.lease_until + timedelta(seconds=1)
        async with session_factory() as session:
            second_claims = await claim_due_delivery_attempts(
                session, now=reclaimed_at
            )
            assert len(second_claims) == 1
            second_claim = second_claims[0]
            assert second_claim.lease_token != first_claim.lease_token
            assert second_claim.observer_attempt_count == 2

        stale_evidence = DeliveryEvidenceResult(
            status=DeliveryEvidenceStatus.VERIFIED_FINALIZED,
            item_address=first_claim.item_address,
            network=first_claim.network,
            seller_wallet_address=first_claim.seller_address,
            buyer_wallet_address=first_claim.buyer_address,
            query_id=first_claim.query_id,
            transaction_hash="ab" * 32,
            trace_id="cd" * 32,
            masterchain_seqno=123456,
        )
        async with session_factory() as session:
            stale_outcome = await apply_delivery_observation(
                session, first_claim, stale_evidence, now=reclaimed_at
            )
        assert stale_outcome == "lease_lost"

        inconclusive = DeliveryEvidenceResult(
            status=DeliveryEvidenceStatus.INCONCLUSIVE,
            item_address=second_claim.item_address,
            network=second_claim.network,
            seller_wallet_address=second_claim.seller_address,
            buyer_wallet_address=second_claim.buyer_address,
            query_id=second_claim.query_id,
            reason="trace not indexed yet",
        )
        async with session_factory() as session:
            retry_outcome = await apply_delivery_observation(
                session, second_claim, inconclusive, now=reclaimed_at
            )
        assert retry_outcome == "retried"

        async with session_factory() as session:
            persisted_order = await session.get(Order, order.id)
            persisted_listing = await session.get(Listing, listing.id)
            persisted_attempt = await session.get(OrderDeliveryAttempt, attempt.id)
            assert persisted_order is not None
            assert persisted_order.status is OrderStatus.OBSERVING_TRANSFER
            assert persisted_listing is not None
            assert persisted_listing.status is ListingStatus.RESERVED
            assert persisted_attempt is not None
            assert persisted_attempt.status is OrderDeliveryAttemptStatus.OBSERVING
            assert persisted_attempt.transaction_hash is None
            assert persisted_attempt.next_check_at is not None
            assert persisted_attempt.next_check_at > reclaimed_at
            assert persisted_attempt.observer_lease_token is None
    finally:
        await _cleanup_observer_fixture(
            session_factory,
            seller_id=seller.id,
            buyer_id=buyer.id,
            asset_id=asset.id,
            listing_id=listing.id,
            order_id=order.id,
            attempt_id=attempt.id,
        )
        await engine.dispose()


async def test_delivery_observer_quarantines_failed_transfer_without_releasing_listing(
    test_database_url: str, migrated_database
) -> None:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, listing, order, attempt, now = await _create_observer_fixture(session)
    try:
        async with session_factory() as session:
            claims = await claim_due_delivery_attempts(session, now=now)
            assert len(claims) == 1
            claim = claims[0]
        failed = DeliveryEvidenceResult(
            status=DeliveryEvidenceStatus.FAILED,
            item_address=claim.item_address,
            network=claim.network,
            seller_wallet_address=claim.seller_address,
            buyer_wallet_address="0:" + "d4" * 32,
            query_id=claim.query_id,
            reason="recipient mismatch",
        )
        async with session_factory() as session:
            outcome = await apply_delivery_observation(
                session, claim, failed, now=now + timedelta(seconds=1)
            )
        assert outcome == "manual_review"

        async with session_factory() as session:
            persisted_order = await session.get(Order, order.id)
            persisted_listing = await session.get(Listing, listing.id)
            persisted_asset = await session.get(NFTAsset, asset.id)
            persisted_attempt = await session.get(OrderDeliveryAttempt, attempt.id)
            assert persisted_order is not None
            assert persisted_order.status is OrderStatus.OBSERVING_TRANSFER
            assert persisted_listing is not None
            assert persisted_listing.status is ListingStatus.RESERVED
            assert persisted_asset is not None
            assert persisted_asset.owner_id == seller.id
            assert persisted_attempt is not None
            assert persisted_attempt.status is OrderDeliveryAttemptStatus.MANUAL_REVIEW
            assert persisted_attempt.reason_code == "transfer_mismatch_or_failed"
    finally:
        await _cleanup_observer_fixture(
            session_factory,
            seller_id=seller.id,
            buyer_id=buyer.id,
            asset_id=asset.id,
            listing_id=listing.id,
            order_id=order.id,
            attempt_id=attempt.id,
        )
        await engine.dispose()
