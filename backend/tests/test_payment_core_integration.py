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
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
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
from app.db.payments import PaymentEvent, PaymentIntent, PaymentTransaction
from app.orders import payment_service
from app.orders.payment_service import (
    PaymentConflict,
    create_stars_payment_intent,
    record_stars_refund_result,
    record_stars_success,
    validate_stars_pre_checkout,
)
from app.orders.service import OrderConflict, cancel_order, prepare_delivery

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def payment_database() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("Payment integration tests require PostgreSQL")
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


class ExplodingVerifier:
    async def verify(self, item_address: str, expected_owner_address: str):
        raise AssertionError("payment gate must run before the TON provider")


async def _seed_order(session_factory, *, expires_in: timedelta = timedelta(minutes=15)):
    seller_id = uuid4()
    buyer_id = uuid4()
    order_id = uuid4()
    listing_id = uuid4()
    asset_id = uuid4()
    seller_wallet_id = uuid4()
    buyer_wallet_id = uuid4()
    buyer_telegram_id = 900_000_000 + uuid4().int % 90_000_000
    now = datetime.now(UTC)

    async with session_factory.begin() as session:
        seller = User(
            id=seller_id,
            telegram_id=buyer_telegram_id + 1,
            first_name="Payment seller",
        )
        buyer = User(
            id=buyer_id,
            telegram_id=buyer_telegram_id,
            first_name="Payment buyer",
        )
        asset = NFTAsset(
            id=asset_id,
            asset_type=AssetType.TON_NFT,
            network="mainnet",
            external_id=f"payment-{uuid4()}",
            item_address=f"0:{uuid4().hex}{uuid4().hex}",
            owner_id=seller_id,
            name="Payment test NFT",
            verification_status=AssetVerificationStatus.VERIFIED,
        )
        seller_wallet = Wallet(
            id=seller_wallet_id,
            user_id=seller_id,
            address=f"0:{uuid4().hex}{uuid4().hex}",
            network="mainnet",
            is_verified=True,
            is_primary=True,
        )
        buyer_wallet = Wallet(
            id=buyer_wallet_id,
            user_id=buyer_id,
            address=f"0:{uuid4().hex}{uuid4().hex}",
            network="mainnet",
            is_verified=True,
            is_primary=True,
        )
        listing = Listing(
            id=listing_id,
            asset_id=asset_id,
            seller_id=seller_id,
            status=ListingStatus.RESERVED,
            price_amount=Decimal("25"),
            price_currency=PriceCurrency.XTR,
            title="Payment test listing",
        )
        order = Order(
            id=order_id,
            listing_id=listing_id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            idempotency_key=f"payment-{uuid4()}",
            status=OrderStatus.RESERVED,
            price_amount=Decimal("25"),
            price_currency=PriceCurrency.XTR,
            expires_at=now + expires_in,
        )
        session.add_all([seller, buyer, asset, seller_wallet, buyer_wallet, listing, order])
    return {
        "order_id": order_id,
        "buyer_id": buyer_id,
        "seller_id": seller_id,
        "seller_wallet_id": seller_wallet_id,
        "telegram_id": buyer_telegram_id,
        "listing_id": listing_id,
        "asset_id": asset_id,
        "buyer_wallet_id": buyer_wallet_id,
    }


async def _cleanup(session_factory, ids: dict[str, object]) -> None:
    async with session_factory.begin() as session:
        order_id = ids["order_id"]
        await session.execute(
            text(
                "DELETE FROM payment_events WHERE payment_intent_id IN "
                "(SELECT id FROM payment_intents WHERE order_id = :order_id)"
            ),
            {"order_id": order_id},
        )
        await session.execute(
            text(
                "DELETE FROM payment_transactions WHERE payment_intent_id IN "
                "(SELECT id FROM payment_intents WHERE order_id = :order_id)"
            ),
            {"order_id": order_id},
        )
        await session.execute(
            PaymentIntent.__table__.delete().where(PaymentIntent.order_id == order_id)
        )
        await session.execute(
            text("DELETE FROM order_events WHERE order_id = :order_id"),
            {"order_id": order_id},
        )
        await session.execute(
            text("DELETE FROM telegram_notification_outbox WHERE order_id = :order_id"),
            {"order_id": order_id},
        )
        await session.execute(Order.__table__.delete().where(Order.id == order_id))
        await session.execute(Listing.__table__.delete().where(Listing.id == ids["listing_id"]))
        await session.execute(NFTAsset.__table__.delete().where(NFTAsset.id == ids["asset_id"]))
        await session.execute(
            Wallet.__table__.delete().where(
                Wallet.id.in_([ids["seller_wallet_id"], ids["buyer_wallet_id"]])
            )
        )
        await session.execute(
            User.__table__.delete().where(User.id.in_([ids["buyer_id"], ids["seller_id"]]))
        )


def _enable_test_stars(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        environment="test",
        telegram_stars_test_enabled=True,
        telegram_stars_test_bot_token=SecretStr("isolated-test-token"),
    )
    monkeypatch.setattr(payment_service, "get_settings", lambda: settings)


async def _create_intent(session_factory, ids):
    async with session_factory() as session:
        return await create_stars_payment_intent(
            session, order_id=ids["order_id"], buyer_id=ids["buyer_id"]
        )


def _payment_evidence(intent, ids, *, update_id: str, charge_id: str):
    return {
        "invoice_payload": intent.invoice_payload,
        "payer_telegram_id": ids["telegram_id"],
        "total_amount": 25,
        "currency": "XTR",
        "telegram_payment_charge_id": charge_id,
        "provider_payment_charge_id": None,
        "provider_event_id": update_id,
    }


async def test_stars_intent_validation_and_success_are_idempotent(
    payment_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch)
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        async with session_factory() as session:
            assert await validate_stars_pre_checkout(
                session,
                invoice_payload=intent.invoice_payload,
                payer_telegram_id=ids["telegram_id"],
                total_amount=25,
                currency="XTR",
            )
        evidence = _payment_evidence(
            intent, ids, update_id=f"update-{uuid4()}", charge_id=f"charge-{uuid4()}"
        )
        async with session_factory() as session:
            assert await record_stars_success(session, **evidence) == "captured"
        async with session_factory() as session:
            assert await record_stars_success(session, **evidence) == "captured"
        async with session_factory() as session:
            persisted = await session.scalar(
                select(PaymentIntent).where(PaymentIntent.order_id == ids["order_id"])
            )
            transactions = (
                await session.scalars(
                    select(PaymentTransaction).where(
                        PaymentTransaction.payment_intent_id == intent.id
                    )
                )
            ).all()
            events = (
                await session.scalars(
                    select(PaymentEvent).where(PaymentEvent.payment_intent_id == intent.id)
                )
            ).all()
            assert persisted is not None and persisted.status == "paid"
            assert len(transactions) == 1
            assert len(events) == 2
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


async def test_reusable_invoice_second_charge_is_refundable(
    payment_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch)
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        async with session_factory() as session:
            assert await record_stars_success(
                session,
                **_payment_evidence(
                    intent, ids, update_id=f"update-{uuid4()}", charge_id=f"charge-{uuid4()}"
                ),
            ) == "captured"
        duplicate_evidence = _payment_evidence(
            intent, ids, update_id=f"update-{uuid4()}", charge_id=f"second-charge-{uuid4()}"
        )
        async with session_factory() as session:
            assert await record_stars_success(session, **duplicate_evidence) == "refund_pending"
        async with session_factory() as session:
            extra = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id
                    == duplicate_evidence["telegram_payment_charge_id"]
                )
            )
            assert extra is not None
            extra_id = extra.id
        async with session_factory() as session:
            assert await record_stars_refund_result(
                session,
                transaction_id=extra_id,
                provider_event_id=f"refund-{uuid4()}",
                succeeded=True,
            ) == "refunded"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


async def test_late_successful_charge_is_marked_for_refund(
    payment_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch)
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        async with session_factory() as session:
            result = await record_stars_success(
                session,
                **_payment_evidence(
                    intent,
                    ids,
                    update_id=f"late-update-{uuid4()}",
                    charge_id=f"late-charge-{uuid4()}"
                ),
                now=datetime.now(UTC) + timedelta(hours=1),
            )
        assert result == "refund_pending"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


async def test_xtr_delivery_is_blocked_without_paid_intent(
    payment_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch)
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        async with session_factory() as session:
            with pytest.raises(OrderConflict, match="Stars payment must be confirmed"):
                await prepare_delivery(
                    session,
                    order_id=ids["order_id"],
                    seller_id=ids["seller_id"],
                    seller_wallet_id=ids["seller_wallet_id"],
                    idempotency_key=f"delivery-{uuid4()}",
                    verifier=ExplodingVerifier(),
                )
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


async def test_production_environment_cannot_enable_test_stars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="production",
        telegram_stars_test_enabled=True,
        telegram_stars_test_bot_token=SecretStr("must-not-be-used"),
    )
    monkeypatch.setattr(payment_service, "get_settings", lambda: settings)
    with pytest.raises(PaymentConflict, match="outside test environments"):
        payment_service._assert_test_stars_enabled()



async def test_migration_refuses_to_drop_payment_evidence(
    payment_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch)
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        await _create_intent(session_factory, ids)
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with pytest.raises(RuntimeError, match="payment ledger"):
            await asyncio.to_thread(
                command.downgrade,
                config,
                "0011_listing_pending_review",
            )
        async with engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            assert revision == "0012_telegram_stars_payments"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()



async def test_cancelling_paid_xtr_order_queues_a_refund(
    payment_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch)
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        async with session_factory() as session:
            assert await record_stars_success(
                session,
                **_payment_evidence(
                    intent,
                    ids,
                    update_id=f"cancel-update-{uuid4()}",
                    charge_id=f"cancel-charge-{uuid4()}",
                ),
            ) == "captured"

        async with session_factory() as session:
            await cancel_order(
                session,
                order_id=ids["order_id"],
                buyer_id=ids["buyer_id"],
            )

        async with session_factory() as session:
            persisted_intent = await session.scalar(
                select(PaymentIntent).where(PaymentIntent.order_id == ids["order_id"])
            )
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.payment_intent_id == intent.id
                )
            )
            order = await session.get(Order, ids["order_id"])
            assert order is not None and order.status is OrderStatus.CANCELLED
            assert persisted_intent is not None and persisted_intent.status == "refund_pending"
            assert transaction is not None and transaction.status == "refund_pending"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()
