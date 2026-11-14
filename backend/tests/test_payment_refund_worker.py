from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

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
from app.db.payments import PaymentIntent, PaymentRefundJob, PaymentTransaction
from app.orders import payment_service, refund_worker
from app.orders.payment_service import record_stars_success
from app.orders.refund_worker import run_refund_worker_pass
from app.orders.service import _invalidate_lost_ownership, expire_pending_orders

pytestmark = pytest.mark.integration
ALEMBIC_CONFIG_PATH = str(Path(__file__).resolve().parents[1] / "alembic.ini")


@pytest.fixture(scope="session")
def refund_test_database() -> str:
    """Migrate only the explicitly supplied disposable TEST_DATABASE_URL."""

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("Refund worker integration tests require PostgreSQL TEST_DATABASE_URL")

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(Config(ALEMBIC_CONFIG_PATH), "head")
        yield url
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        get_settings.cache_clear()


def _enable_test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        environment="test",
        telegram_stars_test_enabled=True,
        telegram_stars_test_bot_token=SecretStr("synthetic-test-token"),
        telegram_stars_refund_worker_enabled=True,
        telegram_stars_refund_history_page_size=100,
        telegram_stars_refund_history_max_pages=10,
        telegram_stars_refund_max_attempts=5,
        telegram_stars_refund_retry_base_seconds=1,
        telegram_stars_refund_retry_max_seconds=10,
    )
    monkeypatch.setattr(payment_service, "get_settings", lambda: settings)
    monkeypatch.setattr(refund_worker, "get_settings", lambda: settings)


async def _seed_payment(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    intent_status: str = "refund_pending",
    transaction_status: str | None = "refund_pending",
    expires_in: timedelta = timedelta(minutes=15),
) -> dict[str, object]:
    suffix = uuid4().int % 900_000_000
    seller_id, buyer_id = uuid4(), uuid4()
    listing_id, asset_id, order_id = uuid4(), uuid4(), uuid4()
    seller_wallet_id, buyer_wallet_id = uuid4(), uuid4()
    buyer_telegram_id = 1_000_000_000 + suffix
    now = datetime.now(UTC)
    expires_at = now + expires_in
    transaction_id = uuid4()
    intent_id = uuid4()
    charge_id = f"test-charge-{uuid4()}"
    invoice_payload = f"refund-payload-{uuid4()}"

    async with session_factory.begin() as session:
        seller = User(
            id=seller_id,
            telegram_id=buyer_telegram_id + 1,
            first_name="Synthetic seller",
        )
        buyer = User(
            id=buyer_id,
            telegram_id=buyer_telegram_id,
            first_name="Synthetic buyer",
        )
        asset = NFTAsset(
            id=asset_id,
            asset_type=AssetType.TON_NFT,
            network="mainnet",
            external_id=f"refund-test-{uuid4()}",
            item_address=f"0:{uuid4().hex}{uuid4().hex}",
            owner_id=seller_id,
            name="Refund worker test NFT",
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
            title="Refund worker synthetic listing",
        )
        order = Order(
            id=order_id,
            listing_id=listing_id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            idempotency_key=f"refund-worker-{uuid4()}",
            status=OrderStatus.RESERVED,
            price_amount=Decimal("25"),
            price_currency=PriceCurrency.XTR,
            expires_at=expires_at,
        )
        intent = PaymentIntent(
            id=intent_id,
            order_id=order_id,
            provider="telegram_stars",
            status=intent_status,
            amount=Decimal("25"),
            currency="XTR",
            payer_telegram_id=buyer_telegram_id,
            invoice_payload=invoice_payload,
            expires_at=expires_at,
            paid_at=now if intent_status == "paid" else None,
        )
        transaction = None
        if transaction_status is not None:
            transaction = PaymentTransaction(
                id=transaction_id,
                payment_intent_id=intent_id,
                provider="telegram_stars",
                telegram_payment_charge_id=charge_id,
                amount=Decimal("25"),
                currency="XTR",
                payer_telegram_id=buyer_telegram_id,
                status=transaction_status,
                captured_at=now,
            )
        session.add_all([
            seller, buyer, asset, seller_wallet, buyer_wallet, listing, order, intent,
        ])
        if transaction is not None:
            session.add(transaction)
        await session.flush()
        if transaction_status == "refund_pending":
            session.add(
                PaymentRefundJob(
                    payment_transaction_id=transaction_id,
                    status="pending",
                    attempt_count=0,
                    next_attempt_at=now,
                )
            )

    return {
        "seller_id": seller_id,
        "buyer_id": buyer_id,
        "buyer_telegram_id": buyer_telegram_id,
        "listing_id": listing_id,
        "asset_id": asset_id,
        "order_id": order_id,
        "intent_id": intent_id,
        "transaction_id": transaction_id,
        "charge_id": charge_id,
        "invoice_payload": invoice_payload,
        "expires_at": expires_at,
        "seller_wallet_id": seller_wallet_id,
        "buyer_wallet_id": buyer_wallet_id,
    }


async def _cleanup(session_factory: async_sessionmaker[AsyncSession], ids: dict[str, object]) -> None:
    async with session_factory.begin() as session:
        order_id = ids["order_id"]
        await session.execute(
            text("ALTER TABLE payment_events DISABLE TRIGGER trg_payment_events_append_only")
        )
        try:
            await session.execute(
                text(
                    "DELETE FROM payment_events WHERE payment_intent_id IN "
                    "(SELECT id FROM payment_intents WHERE order_id = :order_id)"
                ),
                {"order_id": order_id},
            )
        finally:
            await session.execute(
                text("ALTER TABLE payment_events ENABLE TRIGGER trg_payment_events_append_only")
            )
        await session.execute(
            text(
                "DELETE FROM payment_refund_jobs WHERE payment_transaction_id IN "
                "(SELECT id FROM payment_transactions WHERE payment_intent_id IN "
                "(SELECT id FROM payment_intents WHERE order_id = :order_id))"
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


class FakeStarsProvider:
    """In-memory fake; it never talks to Telegram or transfers real Stars."""

    def __init__(self, *, payer_id: int, charge_id: str) -> None:
        self.payer_id = payer_id
        self.charge_id = charge_id
        self.calls = 0
        self.fail_after_apply = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block_request = False
        self.history = [
            SimpleNamespace(
                id=charge_id,
                source=SimpleNamespace(
                    type="user",
                    transaction_type="invoice_payment",
                    user=SimpleNamespace(id=payer_id),
                ),
                receiver=None,
            )
        ]

    async def get_star_transactions(self, *, offset: int, limit: int):
        return SimpleNamespace(transactions=self.history[offset : offset + limit])

    async def refund_star_payment(self, *, user_id: int, telegram_payment_charge_id: str):
        assert user_id == self.payer_id
        assert telegram_payment_charge_id == self.charge_id
        self.calls += 1
        self.started.set()
        if self.block_request:
            await self.release.wait()
        self.history.append(
            SimpleNamespace(
                id=self.charge_id,
                source=None,
                receiver=SimpleNamespace(
                    type="user",
                    user=SimpleNamespace(id=self.payer_id),
                ),
            )
        )
        if self.fail_after_apply:
            self.fail_after_apply = False
            raise TimeoutError("synthetic timeout after provider applied refund")
        return True


async def _make_store(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


@pytest.mark.parametrize("mismatch", ["amount", "payer"])
async def test_mismatched_successful_payment_is_queued_without_completing_order(
    refund_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    _enable_test_settings(monkeypatch)
    engine, factory = await _make_store(refund_test_database)
    ids = await _seed_payment(
        factory,
        intent_status="pending",
        transaction_status=None,
    )

    try:
        async with factory() as session:
            result = await record_stars_success(
                session,
                invoice_payload=str(ids["invoice_payload"]),
                payer_telegram_id=(
                    int(ids["buyer_telegram_id"]) + 99
                    if mismatch == "payer"
                    else int(ids["buyer_telegram_id"])
                ),
                total_amount=26 if mismatch == "amount" else 25,
                currency="XTR",
                telegram_payment_charge_id=f"bad-charge-{uuid4()}",
                provider_payment_charge_id=None,
                provider_event_id=f"bad-update-{uuid4()}",
            )
        assert result == "refund_pending"
        async with factory() as session:
            order = await session.get(Order, ids["order_id"])
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.payment_intent_id == ids["intent_id"]
                )
            )
            job = (
                await session.scalar(
                    select(PaymentRefundJob).where(
                        PaymentRefundJob.payment_transaction_id == transaction.id
                    )
                )
                if transaction is not None
                else None
            )
            assert order is not None and order.status is OrderStatus.RESERVED
            assert transaction is not None and transaction.status == "refund_pending"
            assert job is not None and job.status == "pending"
    finally:
        await _cleanup(factory, ids)
        await engine.dispose()


async def test_refund_crash_after_provider_success_reconciles_without_second_refund(
    refund_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_test_settings(monkeypatch)
    engine, factory = await _make_store(refund_test_database)
    ids = await _seed_payment(factory)
    provider = FakeStarsProvider(
        payer_id=int(ids["buyer_telegram_id"]),
        charge_id=str(ids["charge_id"]),
    )
    provider.fail_after_apply = True
    now = datetime.now(UTC)

    try:
        first = await run_refund_worker_pass(factory, provider, now=now)
        assert first.claimed == 1
        assert first.deferred == 1
        assert provider.calls == 1

        async with factory() as session:
            job = await session.scalar(
                select(PaymentRefundJob).where(
                    PaymentRefundJob.payment_transaction_id == ids["transaction_id"]
                )
            )
            transaction = await session.get(PaymentTransaction, ids["transaction_id"])
            assert job is not None and job.status == "reconciling"
            assert job.request_started_at is not None
            assert transaction is not None and transaction.status == "refund_pending"

        second = await run_refund_worker_pass(
            factory, provider, now=now + timedelta(seconds=5)
        )
        assert second.refunded == 1
        assert provider.calls == 1

        third = await run_refund_worker_pass(
            factory, provider, now=now + timedelta(seconds=10)
        )
        assert third.claimed == 0
        assert provider.calls == 1

        async with factory() as session:
            job = await session.scalar(
                select(PaymentRefundJob).where(
                    PaymentRefundJob.payment_transaction_id == ids["transaction_id"]
                )
            )
            transaction = await session.get(PaymentTransaction, ids["transaction_id"])
            intent = await session.get(PaymentIntent, ids["intent_id"])
            order = await session.get(Order, ids["order_id"])
            assert job is not None and job.status == "succeeded"
            assert transaction is not None and transaction.status == "refunded"
            assert intent is not None and intent.status == "refunded"
            assert order is not None and order.status is OrderStatus.RESERVED
    finally:
        await _cleanup(factory, ids)
        await engine.dispose()


async def test_two_concurrent_workers_cannot_send_the_same_refund_twice(
    refund_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_test_settings(monkeypatch)
    engine, factory = await _make_store(refund_test_database)
    ids = await _seed_payment(factory)
    provider = FakeStarsProvider(
        payer_id=int(ids["buyer_telegram_id"]),
        charge_id=str(ids["charge_id"]),
    )
    provider.block_request = True
    now = datetime.now(UTC)

    try:
        first_task = asyncio.create_task(
            run_refund_worker_pass(factory, provider, now=now)
        )
        await asyncio.wait_for(provider.started.wait(), timeout=5)
        second = await run_refund_worker_pass(factory, provider, now=now)
        assert second.claimed == 0
        assert provider.calls == 1

        provider.release.set()
        first = await asyncio.wait_for(first_task, timeout=5)
        assert first.refunded == 1
        assert provider.calls == 1

        async with factory() as session:
            transaction = await session.get(PaymentTransaction, ids["transaction_id"])
            job = await session.scalar(
                select(PaymentRefundJob).where(
                    PaymentRefundJob.payment_transaction_id == ids["transaction_id"]
                )
            )
            assert transaction is not None and transaction.status == "refunded"
            assert job is not None and job.status == "succeeded"
    finally:
        provider.release.set()
        await _cleanup(factory, ids)
        await engine.dispose()


async def test_expired_order_queues_captured_charge_for_refund(
    refund_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_test_settings(monkeypatch)
    engine, factory = await _make_store(refund_test_database)
    ids = await _seed_payment(
        factory,
        intent_status="paid",
        transaction_status="captured",
        expires_in=timedelta(seconds=-10),
    )
    try:
        async with factory() as session:
            expired = await expire_pending_orders(session, now=datetime.now(UTC))
            assert expired == 1

        async with factory() as session:
            transaction = await session.get(PaymentTransaction, ids["transaction_id"])
            job = await session.scalar(
                select(PaymentRefundJob).where(
                    PaymentRefundJob.payment_transaction_id == ids["transaction_id"]
                )
            )
            order = await session.get(Order, ids["order_id"])
            assert transaction is not None and transaction.status == "refund_pending"
            assert job is not None and job.status == "pending"
            assert order is not None and order.status is OrderStatus.EXPIRED
    finally:
        await _cleanup(factory, ids)
        await engine.dispose()


async def test_lost_seller_ownership_queues_captured_charge_for_refund(
    refund_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_test_settings(monkeypatch)
    engine, factory = await _make_store(refund_test_database)
    ids = await _seed_payment(factory, intent_status="paid", transaction_status="captured")
    try:
        async with factory.begin() as session:
            listing = await session.get(Listing, ids["listing_id"])
            asset = await session.get(NFTAsset, ids["asset_id"])
            assert listing is not None and asset is not None
            await _invalidate_lost_ownership(
                session,
                listing=listing,
                asset=asset,
                current_time=datetime.now(UTC),
            )

        async with factory() as session:
            transaction = await session.get(PaymentTransaction, ids["transaction_id"])
            job = await session.scalar(
                select(PaymentRefundJob).where(
                    PaymentRefundJob.payment_transaction_id == ids["transaction_id"]
                )
            )
            order = await session.get(Order, ids["order_id"])
            assert transaction is not None and transaction.status == "refund_pending"
            assert job is not None and job.status == "pending"
            assert order is not None and order.status is OrderStatus.CANCELLED
    finally:
        await _cleanup(factory, ids)
        await engine.dispose()


async def test_valid_payment_does_not_complete_nft_delivery(
    refund_test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_test_settings(monkeypatch)
    engine, factory = await _make_store(refund_test_database)
    ids = await _seed_payment(
        factory,
        intent_status="pending",
        transaction_status=None,
    )
    try:
        async with factory() as session:
            result = await record_stars_success(
                session,
                invoice_payload=str(ids["invoice_payload"]),
                payer_telegram_id=int(ids["buyer_telegram_id"]),
                total_amount=25,
                currency="XTR",
                telegram_payment_charge_id=f"valid-charge-{uuid4()}",
                provider_payment_charge_id=None,
                provider_event_id=f"valid-update-{uuid4()}",
            )
        assert result == "captured"
        async with factory() as session:
            order = await session.get(Order, ids["order_id"])
            assert order is not None
            assert order.status is OrderStatus.RESERVED
    finally:
        await _cleanup(factory, ids)
        await engine.dispose()
