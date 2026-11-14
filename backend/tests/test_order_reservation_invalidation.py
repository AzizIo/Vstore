"""Review regressions for issue #28.

Covers three review findings on the fresh-ownership reservation path:

1. the verifier must not query a different TON network than the persisted asset;
2. reservation lock order must match `publish_listing` (listing -> wallet -> asset);
3. losing ownership while a listing is already RESERVED must close that listing
   and its pending order, and no release path may re-expose a stale asset.

These tests need PostgreSQL; they skip when TEST_DATABASE_URL is absent.
"""

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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
    TelegramNotificationOutbox,
    User,
    Wallet,
)
from app.listings.service import publish_listing
from app.orders.service import (
    OrderConflict,
    OrderVerificationUnavailable,
    cancel_order,
    create_order,
    expire_pending_orders,
)

from tests.database_safety import require_test_database_url

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def invalidation_database() -> str:
    url = require_test_database_url("Reservation invalidation tests")
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


class TaggedVerifier:
    """TEP-62 stand-in carrying the network it queries plus recorded calls."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        network: str | None = "mainnet",
        status: VerificationStatus = VerificationStatus.VERIFIED,
        owner_address: str | None = None,
        callback=None,
    ) -> None:
        self.session = session
        self.network = network
        self.status = status
        self.owner_address = owner_address
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
            item_address=item_address,
            owner_address=self.owner_address or expected_owner_address,
            expected_owner_address=expected_owner_address,
        )


async def make_user(session: AsyncSession, *, offset: int) -> User:
    user = User(
        telegram_id=offset + uuid4().int % 1_000_000_000,
        first_name="Invalidation user",
    )
    session.add(user)
    await session.flush()
    return user


async def seed_active_listing(
    session: AsyncSession,
) -> tuple[User, User, NFTAsset, Wallet, Listing]:
    seller = await make_user(session, offset=700_000_000)
    buyer = await make_user(session, offset=800_000_000)
    item_address = f"0:{uuid4().hex}{uuid4().hex}"
    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        network="mainnet",
        external_id=item_address,
        item_address=item_address,
        owner_id=seller.id,
        name="Invalidation NFT",
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
        price_amount=Decimal("1.250000000"),
        price_currency=PriceCurrency.TON,
        title="Invalidation listing",
    )
    session.add(listing)
    await session.flush()
    return seller, buyer, asset, wallet, listing


async def cleanup(
    session_factory,
    *,
    listing_ids,
    asset_id,
    wallet_id,
    user_ids,
) -> None:
    async with session_factory.begin() as session:
        for listing_id in listing_ids:
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
            Listing.__table__.delete().where(Listing.id.in_(listing_ids))
        )
        await session.execute(
            NFTAsset.__table__.delete().where(NFTAsset.id == asset_id)
        )
        await session.execute(Wallet.__table__.delete().where(Wallet.id == wallet_id))
        await session.execute(User.__table__.delete().where(User.id.in_(user_ids)))


async def orders_for(session: AsyncSession, listing_id) -> list[Order]:
    return list(
        (
            await session.scalars(select(Order).where(Order.listing_id == listing_id))
        ).all()
    )


# --- Finding 3: network guard -------------------------------------------------


async def test_network_mismatch_fails_closed_before_any_provider_call(
    invalidation_database: str,
) -> None:
    engine = create_async_engine(invalidation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await seed_active_listing(session)

    try:
        async with session_factory() as session:
            verifier = TaggedVerifier(network="testnet", session=session)
            with pytest.raises(OrderVerificationUnavailable, match="network"):
                await create_order(
                    session,
                    buyer_id=buyer.id,
                    listing_id=listing.id,
                    idempotency_key="network-mismatch",
                    verifier=verifier,
                )

        assert verifier.calls == []
        async with session_factory() as session:
            stored_listing = await session.get(Listing, listing.id)
            stored_asset = await session.get(NFTAsset, asset.id)
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.ACTIVE
            assert stored_asset is not None
            assert stored_asset.verification_status is AssetVerificationStatus.VERIFIED
            assert await orders_for(session, listing.id) == []
    finally:
        await cleanup(
            session_factory,
            listing_ids=[listing.id],
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


async def test_matching_network_still_reserves(invalidation_database: str) -> None:
    engine = create_async_engine(invalidation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await seed_active_listing(session)

    try:
        async with session_factory() as session:
            order_id = await create_order(
                session,
                buyer_id=buyer.id,
                listing_id=listing.id,
                idempotency_key="network-match",
                verifier=TaggedVerifier(network="mainnet", session=session),
            )
        async with session_factory() as session:
            stored_order = await session.get(Order, order_id)
            assert stored_order is not None
            assert stored_order.status is OrderStatus.RESERVED
    finally:
        await cleanup(
            session_factory,
            listing_ids=[listing.id],
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


# --- Finding 1: ownership lost while already RESERVED -------------------------


async def test_reserved_listing_and_its_order_close_when_ownership_is_lost(
    invalidation_database: str,
) -> None:
    """Interleaving from the review.

    Buyer B takes an ACTIVE snapshot and starts its provider check. While B is
    waiting on the provider, buyer A reserves the listing. B's check then returns
    OWNER_MISMATCH, so B must invalidate the asset *and* the reservation A holds —
    not leave the listing RESERVED with a live pending order.
    """

    engine = create_async_engine(invalidation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer_a, asset, wallet, listing = await seed_active_listing(session)
        buyer_b = await make_user(session, offset=900_000_000)

    reserved: dict[str, object] = {}

    async def reserve_as_buyer_a() -> None:
        async with session_factory() as session:
            reserved["order_id"] = await create_order(
                session,
                buyer_id=buyer_a.id,
                listing_id=listing.id,
                idempotency_key="reserved-by-a",
                verifier=TaggedVerifier(session=session),
            )

    try:
        async with session_factory() as session:
            verifier = TaggedVerifier(
                session=session,
                status=VerificationStatus.OWNER_MISMATCH,
                owner_address=f"0:{uuid4().hex}{uuid4().hex}",
                callback=reserve_as_buyer_a,
            )
            with pytest.raises(OrderConflict, match="ownership could not be freshly verified"):
                await create_order(
                    session,
                    buyer_id=buyer_b.id,
                    listing_id=listing.id,
                    idempotency_key="stale-second-buyer",
                    verifier=verifier,
                )

        order_a_id = reserved["order_id"]
        assert order_a_id is not None

        async with session_factory() as session:
            stored_listing = await session.get(Listing, listing.id)
            stored_asset = await session.get(NFTAsset, asset.id)
            order_a = await session.get(Order, order_a_id)
            assert stored_asset is not None
            assert stored_asset.verification_status is AssetVerificationStatus.STALE
            assert stored_listing is not None
            # Not left RESERVED, and never re-exposed as ACTIVE.
            assert stored_listing.status is ListingStatus.EXPIRED
            assert order_a is not None
            assert order_a.status is OrderStatus.CANCELLED
    finally:
        await cleanup(
            session_factory,
            listing_ids=[listing.id],
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer_a.id, buyer_b.id],
        )
        await engine.dispose()


async def test_invalidation_notifies_both_parties_through_the_outbox(
    invalidation_database: str,
) -> None:
    """Closing a reservation on lost ownership must notify buyer and seller once."""

    engine = create_async_engine(invalidation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer_a, asset, wallet, listing = await seed_active_listing(session)
        buyer_b = await make_user(session, offset=900_000_000)

    reserved: dict[str, object] = {}

    async def reserve_as_buyer_a() -> None:
        async with session_factory() as session:
            reserved["order_id"] = await create_order(
                session,
                buyer_id=buyer_a.id,
                listing_id=listing.id,
                idempotency_key="outbox-reserved-by-a",
                verifier=TaggedVerifier(session=session),
            )

    try:
        async with session_factory() as session:
            with pytest.raises(OrderConflict):
                await create_order(
                    session,
                    buyer_id=buyer_b.id,
                    listing_id=listing.id,
                    idempotency_key="outbox-stale-second-buyer",
                    verifier=TaggedVerifier(
                        session=session,
                        status=VerificationStatus.OWNER_MISMATCH,
                        owner_address=f"0:{uuid4().hex}{uuid4().hex}",
                        callback=reserve_as_buyer_a,
                    ),
                )

        order_a_id = reserved["order_id"]
        assert order_a_id is not None
        async with session_factory() as session:
            cancellations = (
                await session.scalars(
                    select(TelegramNotificationOutbox).where(
                        TelegramNotificationOutbox.order_id == order_a_id,
                        TelegramNotificationOutbox.event_type == "order_cancelled",
                    )
                )
            ).all()
            # Exactly one notification per party, addressed to that order.
            assert {row.recipient_role for row in cancellations} == {"buyer", "seller"}
            assert len({row.dedupe_key for row in cancellations}) == 2
    finally:
        await cleanup(
            session_factory,
            listing_ids=[listing.id],
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer_a.id, buyer_b.id],
        )
        await engine.dispose()


# --- Finding 1b: no release path re-exposes a stale asset ---------------------


async def test_cancellation_does_not_reactivate_a_stale_listing(
    invalidation_database: str,
) -> None:
    engine = create_async_engine(invalidation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await seed_active_listing(session)

    try:
        async with session_factory() as session:
            order_id = await create_order(
                session,
                buyer_id=buyer.id,
                listing_id=listing.id,
                idempotency_key="cancel-guard",
                verifier=TaggedVerifier(session=session),
            )

        async with session_factory.begin() as session:
            stored_asset = await session.get(NFTAsset, asset.id)
            assert stored_asset is not None
            stored_asset.verification_status = AssetVerificationStatus.STALE

        async with session_factory() as session:
            await cancel_order(session, order_id=order_id, buyer_id=buyer.id)

        async with session_factory() as session:
            stored_listing = await session.get(Listing, listing.id)
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.EXPIRED
    finally:
        await cleanup(
            session_factory,
            listing_ids=[listing.id],
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


async def test_expiry_worker_does_not_reactivate_a_stale_listing(
    invalidation_database: str,
) -> None:
    engine = create_async_engine(invalidation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await seed_active_listing(session)

    try:
        async with session_factory() as session:
            await create_order(
                session,
                buyer_id=buyer.id,
                listing_id=listing.id,
                idempotency_key="expiry-guard",
                verifier=TaggedVerifier(session=session),
            )

        async with session_factory.begin() as session:
            stored_asset = await session.get(NFTAsset, asset.id)
            assert stored_asset is not None
            stored_asset.verification_status = AssetVerificationStatus.STALE

        async with session_factory() as session:
            expired = await expire_pending_orders(
                session, now=datetime.now(UTC) + timedelta(hours=2)
            )
            assert expired == 1

        async with session_factory() as session:
            stored_listing = await session.get(Listing, listing.id)
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.EXPIRED
    finally:
        await cleanup(
            session_factory,
            listing_ids=[listing.id],
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


# --- Finding 2: lock order ----------------------------------------------------


async def test_reservation_and_publication_do_not_deadlock(invalidation_database: str) -> None:
    """Reserve the active listing while publishing a second draft for the asset.

    Before the lock-order fix this formed a cycle (reservation took the asset then
    the wallet, publication took the wallet then the asset). Both paths now lock
    listing -> wallet -> asset, so both must finish.
    """

    engine = create_async_engine(invalidation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await seed_active_listing(session)
        draft = Listing(
            asset_id=asset.id,
            seller_id=seller.id,
            status=ListingStatus.DRAFT,
            price_amount=Decimal("2.5"),
            price_currency=PriceCurrency.TON,
            title="Second draft",
        )
        session.add(draft)
        await session.flush()

    async def reserve():
        async with session_factory() as session:
            try:
                return await create_order(
                    session,
                    buyer_id=buyer.id,
                    listing_id=listing.id,
                    idempotency_key="deadlock-reserve",
                    verifier=TaggedVerifier(session=session),
                )
            except OrderConflict as exc:
                return exc

    async def publish():
        async with session_factory() as session:
            try:
                return await publish_listing(
                    session,
                    listing_id=draft.id,
                    seller_id=seller.id,
                    verifier=TaggedVerifier(session=session),
                )
            except Exception as exc:  # noqa: BLE001 - expected conflicts are results here
                return exc

    try:
        results = await asyncio.wait_for(
            asyncio.gather(reserve(), publish()), timeout=30
        )
        # Neither arm may surface a database deadlock; a business conflict is fine.
        for result in results:
            assert not isinstance(result, Exception) or isinstance(
                result, (OrderConflict,)
            ) or type(result).__name__.endswith("Error") is False
    finally:
        await cleanup(
            session_factory,
            listing_ids=[listing.id, draft.id],
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()