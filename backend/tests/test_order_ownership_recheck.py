"""Issue #28: fresh TEP-62 ownership re-check before listing reservation.

These tests need PostgreSQL; they skip when TEST_DATABASE_URL is absent.
"""

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
    User,
    Wallet,
)
from app.orders.service import OrderConflict, OrderVerificationUnavailable, create_order

from tests.database_safety import require_test_database_url

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def reservation_database() -> str:
    url = require_test_database_url("Reservation ownership tests")
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


class RecordingVerifier:
    """TEP-62 stand-in that records transaction state around each provider call.

    The recorded flag proves whether the provider was contacted while a database
    transaction (and therefore any row lock) was still open.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        status: VerificationStatus = VerificationStatus.VERIFIED,
        owner_address: str | None = None,
        callback=None,
    ) -> None:
        self.session = session
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


class ExplodingVerifier:
    async def verify(self, item_address: str, expected_owner_address: str):
        raise AssertionError("the provider must not be called for this case")


async def _make_user(session: AsyncSession, *, offset: int) -> User:
    user = User(
        telegram_id=offset + uuid4().int % 1_000_000_000,
        first_name="Reservation user",
    )
    session.add(user)
    await session.flush()
    return user


async def _seed(
    session: AsyncSession,
) -> tuple[User, User, NFTAsset, Wallet, Listing]:
    seller = await _make_user(session, offset=700_000_000)
    buyer = await _make_user(session, offset=800_000_000)
    item_address = f"0:{uuid4().hex}{uuid4().hex}"
    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        network="mainnet",
        external_id=item_address,
        item_address=item_address,
        owner_id=seller.id,
        name="Reservation NFT",
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
        title="Reservation listing",
    )
    session.add(listing)
    await session.flush()
    return seller, buyer, asset, wallet, listing


async def _cleanup(
    session_factory,
    *,
    listing_id,
    asset_id,
    wallet_id,
    user_ids,
) -> None:
    async with session_factory.begin() as session:
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
            Listing.__table__.delete().where(Listing.id == listing_id)
        )
        await session.execute(
            NFTAsset.__table__.delete().where(NFTAsset.id == asset_id)
        )
        await session.execute(Wallet.__table__.delete().where(Wallet.id == wallet_id))
        await session.execute(User.__table__.delete().where(User.id.in_(user_ids)))


async def _orders_for(session: AsyncSession, listing_id) -> list[Order]:
    return list(
        (
            await session.scalars(select(Order).where(Order.listing_id == listing_id))
        ).all()
    )


async def test_reservation_verifies_ownership_outside_any_transaction(
    reservation_database: str,
) -> None:
    engine = create_async_engine(reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await _seed(session)

    try:
        async with session_factory() as session:
            verifier = RecordingVerifier(session=session)
            order_id = await create_order(
                session,
                buyer_id=buyer.id,
                listing_id=listing.id,
                idempotency_key="fresh-owner-check",
                verifier=verifier,
            )

        assert verifier.calls == [(asset.item_address, wallet.address)]
        assert verifier.transaction_states == [False]

        async with session_factory() as session:
            stored_listing = await session.get(Listing, listing.id)
            stored_order = await session.get(Order, order_id)
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.RESERVED
            assert stored_order is not None
            assert stored_order.status is OrderStatus.RESERVED
            assert stored_order.price_amount == Decimal("1.250000000")
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


async def test_stale_database_ownership_cannot_be_reserved(
    reservation_database: str,
) -> None:
    engine = create_async_engine(reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await _seed(session)

    try:
        async with session_factory() as session:
            verifier = RecordingVerifier(
                session=session,
                status=VerificationStatus.OWNER_MISMATCH,
                owner_address=f"0:{uuid4().hex}{uuid4().hex}",
            )
            with pytest.raises(
                OrderConflict, match="ownership could not be freshly verified"
            ):
                await create_order(
                    session,
                    buyer_id=buyer.id,
                    listing_id=listing.id,
                    idempotency_key="stale-owner",
                    verifier=verifier,
                )

        async with session_factory() as session:
            stored_asset = await session.get(NFTAsset, asset.id)
            stored_listing = await session.get(Listing, listing.id)
            assert stored_asset is not None
            assert stored_asset.verification_status is AssetVerificationStatus.STALE
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.EXPIRED
            assert await _orders_for(session, listing.id) == []
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


async def test_inconclusive_provider_answer_never_reserves(
    reservation_database: str,
) -> None:
    """NOT_FOUND / UNSUPPORTED / INVALID_DATA must all fail closed.

    None of these prove a transfer, so the asset keeps its verification status,
    but the listing must not be reserved on an unconfirmed owner.
    """

    engine = create_async_engine(reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    for index, status in enumerate(
        (
            VerificationStatus.NOT_FOUND,
            VerificationStatus.UNSUPPORTED,
            VerificationStatus.INVALID_DATA,
        )
    ):
        async with session_factory.begin() as session:
            seller, buyer, asset, wallet, listing = await _seed(session)

        try:
            async with session_factory() as session:
                verifier = RecordingVerifier(
                    session=session,
                    status=status,
                    owner_address=f"0:{uuid4().hex}{uuid4().hex}",
                )
                with pytest.raises(
                    OrderConflict, match="ownership could not be freshly verified"
                ):
                    await create_order(
                        session,
                        buyer_id=buyer.id,
                        listing_id=listing.id,
                        idempotency_key=f"inconclusive-{index}",
                        verifier=verifier,
                    )

            async with session_factory() as session:
                stored_asset = await session.get(NFTAsset, asset.id)
                stored_listing = await session.get(Listing, listing.id)
                assert stored_asset is not None
                # Inconclusive is not proof of a transfer: do not mark it stale.
                assert (
                    stored_asset.verification_status
                    is AssetVerificationStatus.VERIFIED
                )
                assert stored_listing is not None
                assert stored_listing.status is ListingStatus.ACTIVE
                assert await _orders_for(session, listing.id) == []
        finally:
            await _cleanup(
                session_factory,
                listing_id=listing.id,
                asset_id=asset.id,
                wallet_id=wallet.id,
                user_ids=[seller.id, buyer.id],
            )

    await engine.dispose()


async def test_provider_outage_is_retryable_and_changes_no_state(
    reservation_database: str,
) -> None:
    engine = create_async_engine(reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await _seed(session)

    try:
        async with session_factory() as session:
            verifier = RecordingVerifier(
                session=session, status=VerificationStatus.PROVIDER_UNAVAILABLE
            )
            with pytest.raises(OrderVerificationUnavailable):
                await create_order(
                    session,
                    buyer_id=buyer.id,
                    listing_id=listing.id,
                    idempotency_key="provider-outage",
                    verifier=verifier,
                )

        async with session_factory() as session:
            stored_asset = await session.get(NFTAsset, asset.id)
            stored_listing = await session.get(Listing, listing.id)
            assert stored_asset is not None
            assert stored_asset.verification_status is AssetVerificationStatus.VERIFIED
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.ACTIVE
            assert await _orders_for(session, listing.id) == []

        # A later successful attempt must still work: the outage was not fatal.
        async with session_factory() as session:
            order_id = await create_order(
                session,
                buyer_id=buyer.id,
                listing_id=listing.id,
                idempotency_key="provider-outage",
                verifier=RecordingVerifier(session=session),
            )
        async with session_factory() as session:
            stored_order = await session.get(Order, order_id)
            assert stored_order is not None
            assert stored_order.status is OrderStatus.RESERVED
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


async def test_wallet_revoked_during_verification_blocks_the_reservation(
    reservation_database: str,
) -> None:
    engine = create_async_engine(reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await _seed(session)

    async def revoke_wallet() -> None:
        async with session_factory.begin() as session:
            stored_wallet = await session.get(Wallet, wallet.id)
            assert stored_wallet is not None
            stored_wallet.is_verified = False

    try:
        async with session_factory() as session:
            verifier = RecordingVerifier(session=session, callback=revoke_wallet)
            with pytest.raises(OrderConflict):
                await create_order(
                    session,
                    buyer_id=buyer.id,
                    listing_id=listing.id,
                    idempotency_key="wallet-revoked",
                    verifier=verifier,
                )

        async with session_factory() as session:
            stored_listing = await session.get(Listing, listing.id)
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.ACTIVE
            assert await _orders_for(session, listing.id) == []
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


async def test_listing_closed_during_verification_cannot_be_reserved(
    reservation_database: str,
) -> None:
    engine = create_async_engine(reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await _seed(session)

    async def close_listing() -> None:
        async with session_factory.begin() as session:
            stored_listing = await session.get(Listing, listing.id)
            assert stored_listing is not None
            stored_listing.status = ListingStatus.CANCELLED

    try:
        async with session_factory() as session:
            verifier = RecordingVerifier(session=session, callback=close_listing)
            with pytest.raises(OrderConflict, match="Listing is not available"):
                await create_order(
                    session,
                    buyer_id=buyer.id,
                    listing_id=listing.id,
                    idempotency_key="listing-closed",
                    verifier=verifier,
                )

        async with session_factory() as session:
            assert await _orders_for(session, listing.id) == []
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


async def test_seller_without_a_verified_wallet_never_reaches_the_provider(
    reservation_database: str,
) -> None:
    engine = create_async_engine(reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await _seed(session)
        stored_wallet = await session.get(Wallet, wallet.id)
        assert stored_wallet is not None
        stored_wallet.is_verified = False

    try:
        async with session_factory() as session:
            with pytest.raises(OrderConflict, match="Listing is not available"):
                await create_order(
                    session,
                    buyer_id=buyer.id,
                    listing_id=listing.id,
                    idempotency_key="no-verified-wallet",
                    verifier=ExplodingVerifier(),
                )
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


async def test_idempotent_retry_does_not_repeat_the_provider_check(
    reservation_database: str,
) -> None:
    engine = create_async_engine(reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, buyer, asset, wallet, listing = await _seed(session)

    try:
        async with session_factory() as session:
            first_id = await create_order(
                session,
                buyer_id=buyer.id,
                listing_id=listing.id,
                idempotency_key="idempotent-retry",
                verifier=RecordingVerifier(session=session),
            )

        async with session_factory() as session:
            replay_id = await create_order(
                session,
                buyer_id=buyer.id,
                listing_id=listing.id,
                idempotency_key="idempotent-retry",
                verifier=ExplodingVerifier(),
            )

        assert replay_id == first_id
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, buyer.id],
        )
        await engine.dispose()


async def test_concurrent_buyers_still_produce_exactly_one_reservation(
    reservation_database: str,
) -> None:
    engine = create_async_engine(reservation_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        seller, first_buyer, asset, wallet, listing = await _seed(session)
        second_buyer = await _make_user(session, offset=900_000_000)

    async def attempt(buyer_id):
        async with session_factory() as session:
            try:
                return await create_order(
                    session,
                    buyer_id=buyer_id,
                    listing_id=listing.id,
                    idempotency_key=f"race-{buyer_id}",
                    verifier=RecordingVerifier(session=session),
                )
            except OrderConflict:
                return None

    try:
        outcomes = await asyncio.gather(
            attempt(first_buyer.id), attempt(second_buyer.id)
        )
        assert len([outcome for outcome in outcomes if outcome is not None]) == 1

        async with session_factory() as session:
            stored_listing = await session.get(Listing, listing.id)
            orders = await _orders_for(session, listing.id)
            assert stored_listing is not None
            assert stored_listing.status is ListingStatus.RESERVED
            assert len(orders) == 1
    finally:
        await _cleanup(
            session_factory,
            listing_id=listing.id,
            asset_id=asset.id,
            wallet_id=wallet.id,
            user_ids=[seller.id, first_buyer.id, second_buyer.id],
        )
        await engine.dispose()