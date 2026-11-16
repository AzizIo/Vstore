"""PostgreSQL race tests for ordinary Order vs TON escrow reservations."""

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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
from app.escrow.models import EscrowDeal, EscrowListingIntent
from app.escrow.reservation import (
    EscrowListingReservationConflict,
    reserve_listing_for_escrow,
)
from app.orders.service import OrderConflict, create_order
from tests.database_safety import require_test_database_url

_ALEMBIC_CONFIG_PATH = str(Path(__file__).resolve().parents[1] / "alembic.ini")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def escrow_reservation_database() -> str:
    url = require_test_database_url("Escrow/order reservation integration tests")
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        config = Config(_ALEMBIC_CONFIG_PATH)
        command.upgrade(config, "head")
        yield url
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        get_settings.cache_clear()


class EventVerifier:
    def __init__(self, verified: asyncio.Event) -> None:
        self.verified = verified

    async def verify(self, item_address: str, expected_owner_address: str):
        self.verified.set()
        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            item_address=item_address,
            owner_address=expected_owner_address,
            expected_owner_address=expected_owner_address,
        )


async def _seed(session, *, include_identity_snapshot: bool = True):
    seller = User(telegram_id=700_000_000 + uuid4().int % 100_000_000, first_name="Escrow seller")
    buyer = User(telegram_id=800_000_000 + uuid4().int % 100_000_000, first_name="Escrow buyer")
    session.add_all([seller, buyer])
    await session.flush()

    item_address = "0:" + uuid4().hex + uuid4().hex
    seller_address = "0:" + uuid4().hex + uuid4().hex
    collection_address = "0:" + uuid4().hex + uuid4().hex
    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        network="testnet",
        external_id=item_address,
        item_address=item_address,
        owner_id=seller.id,
        name="Escrow race fixture",
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    wallet = Wallet(
        user_id=seller.id,
        address=seller_address,
        network="testnet",
        is_verified=True,
        is_primary=True,
    )
    session.add_all([asset, wallet])
    await session.flush()
    listing = Listing(
        asset_id=asset.id,
        seller_id=seller.id,
        status=ListingStatus.ACTIVE,
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        title="Escrow race listing",
    )
    session.add(listing)
    await session.flush()
    intent = EscrowListingIntent(
        marketplace_listing_id=listing.id,
        asset_id=asset.id,
        seller_id=seller.id,
        seller_wallet_id=wallet.id,
        network="testnet",
        item_address=item_address,
        listing_key=uuid4().hex * 2,
        collection_address_snapshot=collection_address,
        **(
            {
                "nft_identity_snapshot_json": {
                    "evidence_sha256": "f" * 64,
                    "network": "testnet",
                    "item_address": item_address,
                    "collection_address": collection_address,
                },
                "nft_identity_snapshot_sha256": "f" * 64,
            }
            if include_identity_snapshot
            else {}
        ),
        seller_address_snapshot=seller_address,
        price_amount=Decimal("1.250000000"),
        price_currency="TON",
        status="active",
        idempotency_key="escrow-listing-" + uuid4().hex[:20],
    )
    session.add(intent)
    await session.flush()
    return seller, buyer, asset, wallet, listing, intent


async def _cleanup(
    session_factory,
    *,
    listing_id,
    intent_id,
    asset_id,
    wallet_id,
    user_ids,
    extra_wallet_ids=(),
):
    async with session_factory.begin() as session:
        await session.execute(
            text("DELETE FROM escrow_wallet_actions WHERE deal_id IN "
                 "(SELECT id FROM escrow_deals WHERE listing_intent_id = :intent_id)"),
            {"intent_id": intent_id},
        )
        await session.execute(
            text("DELETE FROM escrow_idempotency_records WHERE resource_id IN "
                 "(SELECT id FROM escrow_deals WHERE listing_intent_id = :intent_id)"),
            {"intent_id": intent_id},
        )
        await session.execute(
            text("DELETE FROM escrow_chain_events WHERE deal_id IN "
                 "(SELECT id FROM escrow_deals WHERE listing_intent_id = :intent_id)"),
            {"intent_id": intent_id},
        )
        await session.execute(
            text("DELETE FROM escrow_disputes WHERE deal_id IN "
                 "(SELECT id FROM escrow_deals WHERE listing_intent_id = :intent_id)"),
            {"intent_id": intent_id},
        )
        await session.execute(
            text("DELETE FROM escrow_deals WHERE listing_intent_id = :intent_id"),
            {"intent_id": intent_id},
        )
        await session.execute(
            text("DELETE FROM escrow_listing_intents WHERE id = :intent_id"),
            {"intent_id": intent_id},
        )
        await session.execute(
            text("DELETE FROM order_events WHERE order_id IN "
                 "(SELECT id FROM orders WHERE listing_id = :listing_id)"),
            {"listing_id": listing_id},
        )
        await session.execute(
            text("DELETE FROM telegram_notification_outbox WHERE order_id IN "
                 "(SELECT id FROM orders WHERE listing_id = :listing_id)"),
            {"listing_id": listing_id},
        )
        await session.execute(text("DELETE FROM orders WHERE listing_id = :listing_id"),
                              {"listing_id": listing_id})
        await session.execute(Listing.__table__.delete().where(Listing.id == listing_id))
        await session.execute(NFTAsset.__table__.delete().where(NFTAsset.id == asset_id))
        await session.execute(
            Wallet.__table__.delete().where(Wallet.id.in_([wallet_id, *extra_wallet_ids]))
        )
        await session.execute(User.__table__.delete().where(User.id.in_(user_ids)))




@pytest.mark.asyncio
async def test_postgres_listing_identity_snapshot_is_immutable_but_status_can_advance(
    escrow_reservation_database: str,
) -> None:
    engine = create_async_engine(escrow_reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing, intent = await _seed(session)
    original_item_address = intent.item_address
    original_snapshot_hash = intent.nft_identity_snapshot_sha256

    try:
        with pytest.raises(
            DBAPIError,
            match="Persisted escrow NFT identity and bound terms are immutable",
        ):
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text(
                            "UPDATE escrow_listing_intents SET item_address = :new_address "
                            "WHERE id = :intent_id"
                        ),
                        {
                            "new_address": "0:" + "9" * 64,
                            "intent_id": intent.id,
                        },
                    )

        with pytest.raises(
            DBAPIError,
            match="Persisted escrow listing NFT identity binding is immutable",
        ):
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text(
                            "UPDATE escrow_listing_intents SET listing_key = :new_key "
                            "WHERE id = :intent_id"
                        ),
                        {
                            "new_key": "e" * 64,
                            "intent_id": intent.id,
                        },
                    )

        async with session_factory.begin() as session:
            stored = await session.get(EscrowListingIntent, intent.id)
            assert stored is not None
            assert stored.item_address == original_item_address
            assert stored.nft_identity_snapshot_sha256 == original_snapshot_hash
            stored.status = "reserved"

        async with session_factory() as session:
            stored = await session.get(EscrowListingIntent, intent.id)
            assert stored is not None
            assert stored.status == "reserved"
            assert stored.item_address == original_item_address
            assert stored.nft_identity_snapshot_sha256 == original_snapshot_hash
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            intent_id=intent.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()



@pytest.mark.asyncio
async def test_postgres_deal_identity_snapshot_is_immutable_but_status_can_advance(
    escrow_reservation_database: str,
) -> None:
    engine = create_async_engine(escrow_reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing, intent = await _seed(session)
        buyer_wallet = Wallet(
            user_id=buyer.id,
            address="0:" + uuid4().hex + uuid4().hex,
            network="testnet",
            is_verified=True,
            is_primary=True,
        )
        session.add(buyer_wallet)
        await session.flush()
        deal = EscrowDeal(
            listing_intent_id=intent.id,
            marketplace_listing_id=listing.id,
            listing_key_snapshot=intent.listing_key,
            seller_id=seller.id,
            buyer_id=buyer.id,
            buyer_wallet_id=buyer_wallet.id,
            network="testnet",
            deal_salt=uuid4().hex * 2,
            collection_address_snapshot=intent.collection_address_snapshot,
            item_address=intent.item_address,
            seller_address_snapshot=intent.seller_address_snapshot,
            buyer_address_snapshot=buyer_wallet.address,
            price_amount=Decimal("1.250000000"),
            price_currency="TON",
            principal_nanotons=Decimal("1250000000"),
            status="intent_created",
            nft_identity_snapshot_json=intent.nft_identity_snapshot_json,
            nft_identity_snapshot_sha256=intent.nft_identity_snapshot_sha256,
            idempotency_key="escrow-deal-" + uuid4().hex[:20],
        )
        session.add(deal)
        await session.flush()
    deal_id = deal.id
    original_hash = deal.nft_identity_snapshot_sha256

    try:
        with pytest.raises(
            DBAPIError,
            match="Persisted escrow NFT identity and bound terms are immutable",
        ):
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text(
                            "UPDATE escrow_deals SET collection_address_snapshot = :address "
                            "WHERE id = :deal_id"
                        ),
                        {"address": "0:" + "8" * 64, "deal_id": deal_id},
                    )

        for column, value in (
            ("buyer_address_snapshot", "0:" + "7" * 64),
            ("deal_salt", "9" * 64),
            ("principal_nanotons", Decimal("999")),
        ):
            with pytest.raises(
                DBAPIError,
                match="Persisted escrow deal NFT identity and bound terms are immutable",
            ):
                async with session_factory() as session:
                    async with session.begin():
                        await session.execute(
                            text(f"UPDATE escrow_deals SET {column} = :value WHERE id = :deal_id"),
                            {"value": value, "deal_id": deal_id},
                        )

        async with session_factory.begin() as session:
            await session.execute(
                text("UPDATE escrow_deals SET status = 'manual_review' WHERE id = :deal_id"),
                {"deal_id": deal_id},
            )
        async with session_factory() as session:
            stored = await session.get(EscrowDeal, deal_id)
            assert stored is not None
            assert stored.status == "manual_review"
            assert stored.nft_identity_snapshot_sha256 == original_hash
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            intent_id=intent.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
            extra_wallet_ids=[buyer_wallet.id],
        )
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_legacy_listing_intent_cannot_be_retrofitted_with_identity_snapshot(
    escrow_reservation_database: str,
) -> None:
    engine = create_async_engine(escrow_reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing, intent = await _seed(
            session, include_identity_snapshot=False
        )

    snapshot_json = '{"evidence_sha256":"' + "f" * 64 + '"}'
    try:
        with pytest.raises(
            DBAPIError,
            match="Persisted escrow NFT identity and bound terms are immutable",
        ):
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text(
                            "UPDATE escrow_listing_intents "
                            "SET nft_identity_snapshot_json = CAST(:snapshot AS JSON), "
                            "nft_identity_snapshot_sha256 = :digest WHERE id = :intent_id"
                        ),
                        {
                            "snapshot": snapshot_json,
                            "digest": "f" * 64,
                            "intent_id": intent.id,
                        },
                    )

        async with session_factory() as session:
            stored = await session.get(EscrowListingIntent, intent.id)
            assert stored is not None
            assert stored.nft_identity_snapshot_json is None
            assert stored.nft_identity_snapshot_sha256 is None
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            intent_id=intent.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()



@pytest.mark.asyncio
async def test_postgres_migration_downgrade_refuses_to_drop_identity_snapshots(
    escrow_reservation_database: str,
) -> None:
    engine = create_async_engine(escrow_reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing, intent = await _seed(session)

    try:
        config = Config(_ALEMBIC_CONFIG_PATH)
        with pytest.raises(
            RuntimeError,
            match="Cannot downgrade while escrow NFT identity evidence is referenced",
        ):
            await asyncio.to_thread(
                command.downgrade, config, "0019_escrow_deployment_snapshots"
            )

        async with session_factory() as session:
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "0020_escrow_nft_identity"
            stored = await session.get(EscrowListingIntent, intent.id)
            assert stored is not None
            assert stored.nft_identity_snapshot_sha256 == "f" * 64
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            intent_id=intent.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


@pytest.mark.asyncio
async def test_escrow_reservation_wins_race_against_ordinary_order(
    escrow_reservation_database: str,
) -> None:
    engine = create_async_engine(escrow_reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing, intent = await _seed(session)

    listing_locked = asyncio.Event()
    order_verified = asyncio.Event()

    async def escrow_reservation() -> None:
        async with session_factory() as session:
            async with session.begin():
                locked_listing = await session.scalar(
                    select(Listing)
                    .where(Listing.id == listing.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                assert locked_listing is not None
                listing_locked.set()
                await asyncio.wait_for(order_verified.wait(), timeout=10)
                locked_intent = await session.scalar(
                    select(EscrowListingIntent)
                    .where(EscrowListingIntent.id == intent.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                assert locked_intent is not None
                reserve_listing_for_escrow(locked_listing, locked_intent)

    async def ordinary_order() -> bool:
        await asyncio.wait_for(listing_locked.wait(), timeout=10)
        async with session_factory() as session:
            try:
                await create_order(
                    session,
                    buyer_id=buyer.id,
                    listing_id=listing.id,
                    idempotency_key="order-race-" + uuid4().hex[:20],
                    verifier=EventVerifier(order_verified),
                )
            except OrderConflict:
                return False
        return True

    try:
        escrow_task = asyncio.create_task(escrow_reservation())
        order_task = asyncio.create_task(ordinary_order())
        _, order_won = await asyncio.gather(escrow_task, order_task)
        assert order_won is False
        async with session_factory() as session:
            stored_listing = await session.get(Listing, listing.id)
            stored_intent = await session.get(EscrowListingIntent, intent.id)
            orders = list((await session.scalars(
                select(Order).where(Order.listing_id == listing.id)
            )).all())
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.RESERVED
            assert stored_intent is not None and stored_intent.status == "reserved"
            assert not any(order.status is OrderStatus.RESERVED for order in orders)
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            intent_id=intent.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


@pytest.mark.asyncio
async def test_ordinary_order_reservation_blocks_escrow_reservation(
    escrow_reservation_database: str,
) -> None:
    engine = create_async_engine(escrow_reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing, intent = await _seed(session)

    try:
        async with session_factory() as session:
            order_id = await create_order(
                session,
                buyer_id=buyer.id,
                listing_id=listing.id,
                idempotency_key="order-first-" + uuid4().hex[:20],
                verifier=EventVerifier(asyncio.Event()),
            )
        assert order_id is not None
        async with session_factory.begin() as session:
            locked_listing = await session.scalar(
                select(Listing).where(Listing.id == listing.id).with_for_update()
            )
            locked_intent = await session.scalar(
                select(EscrowListingIntent).where(EscrowListingIntent.id == intent.id)
            )
            assert locked_listing is not None and locked_intent is not None
            with pytest.raises(EscrowListingReservationConflict):
                reserve_listing_for_escrow(locked_listing, locked_intent)
        async with session_factory() as session:
            stored_listing = await session.get(Listing, listing.id)
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.RESERVED
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            intent_id=intent.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()
