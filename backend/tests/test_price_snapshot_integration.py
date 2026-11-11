"""Issue #54: the price model is a product invariant.

VILTARA is a marketplace: a listing carries the seller's price, and an order
carries the snapshot of that price at reservation time. These tests exist so
that a change removing prices from listings or orders (see PR #49) fails loudly
instead of passing silently.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.listings import (
    ListingCreateRequest,
    create_listing_draft,
    get_listings,
)
from app.assets.ton_nft.models import VerificationResult, VerificationStatus
from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    Order,
    OrderStatus,
    PriceCurrency,
    User,
    Wallet,
)
from app.listings.service import publish_listing
from app.orders.service import create_order

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def price_database() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("Price model tests require PostgreSQL")
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


async def test_money_columns_exist_in_both_tables(price_database: str) -> None:
    """Prices are part of the listing AND the order — the PR #49 regression guard."""

    engine = create_async_engine(price_database, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            for table in ("listings", "orders"):
                columns = await connection.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_name = :table AND column_name LIKE 'price_%'"
                    ),
                    {"table": table},
                )
                rows = {row[0]: (row[1], row[2]) for row in columns}
                assert "price_amount" in rows, f"{table} lost price_amount"
                assert "price_currency" in rows, f"{table} lost price_currency"
                assert rows["price_amount"][0] == "numeric", "money must be numeric"
                assert rows["price_amount"][1] == "NO", "price must be NOT NULL"

            constraints = await connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conname IN ('ck_listings_price_positive', 'ck_orders_price_positive')"
                )
            )
            names = {row[0] for row in constraints}
            assert "ck_listings_price_positive" in names
            assert "ck_orders_price_positive" in names
    finally:
        await engine.dispose()


async def test_order_snapshots_xtr_price_from_listing(price_database: str) -> None:
    """An XTR listing produces an XTR order with the exact reserved amount.

    The order is created through the real `create_order` service — with its
    ownership verification, idempotency and reservation transition — because
    the point of this test is what the service actually persists, not what
    the ORM would accept from a hand-built row.
    """

    engine = create_async_engine(price_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().int % 1_000_000_000

    async with session_factory.begin() as session:
        seller = User(
            telegram_id=700_000_000 + suffix, first_name="XTR seller"
        )
        buyer = User(
            telegram_id=800_000_000 + suffix, first_name="XTR buyer"
        )
        session.add_all([seller, buyer])
        await session.flush()
        item_address = f"0:{uuid4().hex}{uuid4().hex}"
        asset = NFTAsset(
            asset_type=AssetType.TON_NFT,
            network="mainnet",
            external_id=item_address,
            item_address=item_address,
            owner_id=seller.id,
            verification_status=AssetVerificationStatus.VERIFIED,
        )
        wallet = Wallet(
            user_id=seller.id,
            address=f"0:{uuid4().hex}{uuid4().hex}",
            network="mainnet",
            is_verified=True,
            is_primary=True,
        )
        session.add_all([asset, wallet])
        await session.flush()
        listing = Listing(
            asset_id=asset.id,
            seller_id=seller.id,
            status=ListingStatus.ACTIVE,
            price_amount=Decimal("250.000000000"),
            price_currency=PriceCurrency.XTR,
            title="Stars-priced listing",
        )
        session.add(listing)
        await session.flush()
        ids = (listing.id, asset.id, wallet.id, seller.id, buyer.id)

    class _OwnerVerifier:
        def __init__(self) -> None:
            self.network = "mainnet"
            self.calls: list[tuple[str, str]] = []

        async def verify(self, item_address: str, expected_owner_address: str):
            self.calls.append((item_address, expected_owner_address))
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                item_address=item_address,
                owner_address=expected_owner_address,
                expected_owner_address=expected_owner_address,
            )

    try:
        verifier = _OwnerVerifier()
        async with session_factory() as session:
            order_id = await create_order(
                session,
                buyer_id=ids[4],
                listing_id=ids[0],
                idempotency_key=f"xtr-{suffix}",
                verifier=verifier,
            )

        assert verifier.calls, "the ownership verifier must have been consulted"
        assert verifier.calls[0][0] == asset.item_address
        assert verifier.calls[0][1] == wallet.address

        async with session_factory() as session:
            stored = await session.get(Order, order_id)
            assert stored is not None
            assert stored.status is OrderStatus.PENDING_PAYMENT
            assert stored.buyer_id == ids[4]
            assert stored.seller_id == ids[3]
            assert stored.price_amount == Decimal("250.000000000")
            assert stored.price_currency is PriceCurrency.XTR

        async with session_factory() as session:
            # Idempotent replay through the service returns the same order.
            replayed = await create_order(
                session,
                buyer_id=ids[4],
                listing_id=ids[0],
                idempotency_key=f"xtr-{suffix}",
                verifier=_OwnerVerifier(),
            )
            assert replayed == order_id

        async with session_factory() as session:
            stored_listing = await session.get(Listing, ids[0])
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.RESERVED
            # Changing the listing price later must not touch existing orders.
            stored_listing.price_amount = Decimal("999")
            await session.commit()

        async with session_factory() as session:
            stored = await session.get(Order, order_id)
            assert stored is not None
            assert stored.price_amount == Decimal("250.000000000")
            assert stored.price_currency is PriceCurrency.XTR
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "DELETE FROM order_events WHERE order_id IN "
                    "(SELECT id FROM orders WHERE listing_id = :listing_id)"
                ),
                {"listing_id": ids[0]},
            )
            await session.execute(
                text(
                    "DELETE FROM telegram_notification_outbox WHERE order_id IN "
                    "(SELECT id FROM orders WHERE listing_id = :listing_id)"
                ),
                {"listing_id": ids[0]},
            )
            await session.execute(
                text("DELETE FROM orders WHERE listing_id = :listing_id"),
                {"listing_id": ids[0]},
            )
            await session.execute(
                Listing.__table__.delete().where(Listing.id == ids[0])
            )
            await session.execute(
                NFTAsset.__table__.delete().where(NFTAsset.id == ids[1])
            )
            await session.execute(
                Wallet.__table__.delete().where(Wallet.id == ids[2])
            )
            await session.execute(
                User.__table__.delete().where(User.id.in_([ids[3], ids[4]]))
            )
        await engine.dispose()

async def test_priced_listing_draft_publish_catalog_and_order_snapshot(
    price_database: str,
) -> None:
    """Issue #45: exercise draft -> publish -> public catalog -> reserved order."""
    engine = create_async_engine(price_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().int % 1_000_000_000
    amount = Decimal("37.123456789")
    item_address = f"0:{uuid4().hex}{uuid4().hex}"
    wallet_address = f"0:{uuid4().hex}{uuid4().hex}"

    async with session_factory.begin() as session:
        seller = User(
            telegram_id=710_000_000 + suffix,
            first_name="Priced listing seller",
        )
        buyer = User(
            telegram_id=810_000_000 + suffix,
            first_name="Priced listing buyer",
        )
        session.add_all([seller, buyer])
        await session.flush()
        asset = NFTAsset(
            asset_type=AssetType.TON_NFT,
            network="mainnet",
            external_id=item_address,
            item_address=item_address,
            owner_id=seller.id,
            name="Issue 45 integration NFT",
            verification_status=AssetVerificationStatus.VERIFIED,
        )
        wallet = Wallet(
            user_id=seller.id,
            address=wallet_address,
            network="mainnet",
            is_verified=True,
            is_primary=True,
        )
        session.add_all([asset, wallet])
        await session.flush()
        seller_id = seller.id
        buyer_id = buyer.id
        asset_id = asset.id
        wallet_id = wallet.id

    class _OwnerVerifier:
        def __init__(self) -> None:
            self.network = "mainnet"
            self.calls: list[tuple[str, str]] = []

        async def verify(self, requested_item: str, expected_owner: str):
            self.calls.append((requested_item, expected_owner))
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                item_address=requested_item,
                owner_address=expected_owner,
                expected_owner_address=expected_owner,
            )

    verifier = _OwnerVerifier()
    listing_id = None
    order_id = None
    try:
        async with session_factory() as session:
            seller = await session.get(User, seller_id)
            assert seller is not None
            draft = await create_listing_draft(
                ListingCreateRequest(
                    asset_id=asset_id,
                    price_amount=amount,
                    price_currency=PriceCurrency.XTR,
                    title="Priced draft to order",
                ),
                seller,
                session,
                verifier,
            )
            listing_id = draft.id

        async with session_factory() as session:
            published = await publish_listing(
                session,
                listing_id=listing_id,
                seller_id=seller_id,
                verifier=verifier,
            )
            assert published.status is ListingStatus.ACTIVE
            assert published.price_amount == amount
            assert published.price_currency is PriceCurrency.XTR

        # The public catalogue must expose the same amount/currency that were
        # entered on the draft and retained through the publish transition.
        async with session_factory() as session:
            page = await get_listings(
                session,
                limit=100,
                offset=0,
                asset_type=AssetType.TON_NFT,
                currency=PriceCurrency.XTR,
                search="Issue 45 integration NFT",
                sort="newest",
            )
            visible = next((item for item in page.items if item.id == listing_id), None)
            assert visible is not None
            assert visible.price_amount == amount
            assert visible.price_currency is PriceCurrency.XTR
            assert visible.status is ListingStatus.ACTIVE

        async with session_factory() as session:
            order_id = await create_order(
                session,
                buyer_id=buyer_id,
                listing_id=listing_id,
                idempotency_key=f"issue-45-{suffix}",
                verifier=verifier,
            )

        async with session_factory() as session:
            stored_order = await session.get(Order, order_id)
            stored_listing = await session.get(Listing, listing_id)
            assert stored_order is not None
            assert stored_listing is not None
            assert stored_order.status is OrderStatus.PENDING_PAYMENT
            assert stored_order.price_amount == amount
            assert stored_order.price_currency is PriceCurrency.XTR
            assert stored_listing.status is ListingStatus.RESERVED

        assert (item_address, wallet_address) in verifier.calls
    finally:
        async with session_factory.begin() as session:
            if order_id is not None:
                await session.execute(
                    text("DELETE FROM order_events WHERE order_id = :order_id"),
                    {"order_id": order_id},
                )
                await session.execute(
                    text("DELETE FROM telegram_notification_outbox WHERE order_id = :order_id"),
                    {"order_id": order_id},
                )
                await session.execute(
                    text("DELETE FROM orders WHERE id = :order_id"),
                    {"order_id": order_id},
                )
            if listing_id is not None:
                await session.execute(
                    Listing.__table__.delete().where(Listing.id == listing_id)
                )
            await session.execute(
                NFTAsset.__table__.delete().where(NFTAsset.id == asset_id)
            )
            await session.execute(
                Wallet.__table__.delete().where(Wallet.id == wallet_id)
            )
            await session.execute(
                User.__table__.delete().where(User.id.in_([seller_id, buyer_id]))
            )
        await engine.dispose()
