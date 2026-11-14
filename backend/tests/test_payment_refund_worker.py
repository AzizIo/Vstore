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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    Order,
    OrderDeliveryAttempt,
    OrderEvent,
    OrderStatus,
    PriceCurrency,
    TelegramNotificationOutbox,
    User,
    Wallet,
)
from app.db.payments import PaymentIntent, PaymentRefund, PaymentTransaction
from app.orders import payment_service, refund_worker
from app.orders.payment_service import (
    create_stars_payment_intent,
    record_stars_success,
)
from app.orders.refund_worker import (
    RefundCallOutcome,
    RefundCallResult,
    RefundLookupResult,
    process_due_refunds,
)
from app.orders.service import _invalidate_lost_ownership, cancel_order
from tests.database_safety import require_test_database_url

pytestmark = pytest.mark.integration
ALEMBIC_CONFIG_PATH = str(Path(__file__).resolve().parents[1] / "alembic.ini")


@pytest.fixture(scope="session")
def refund_database() -> str:
    url = require_test_database_url("Refund integration tests")

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    from app.core.config import get_settings

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


def _enable_test_stars(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Settings:
    settings = Settings(
        environment="test",
        database_url=database_url,
        bot_token="654321:primary-test-token",
        telegram_stars_test_enabled=True,
        telegram_stars_test_bot_token=SecretStr("123456:isolated-test-token"),
        payment_refund_reconcile_delay_seconds=1,
        payment_refund_lease_seconds=120,
        payment_refund_retry_base_seconds=1,
        payment_refund_retry_max_seconds=60,
        payment_refund_max_attempts=4,
        payment_refund_max_reconcile_attempts=4,
    )
    monkeypatch.setattr(payment_service, "get_settings", lambda: settings)
    monkeypatch.setattr(refund_worker, "get_settings", lambda: settings)
    return settings


async def _seed_order(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    expires_in: timedelta = timedelta(minutes=15),
) -> dict[str, object]:
    seller_id, buyer_id, order_id, listing_id, asset_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    seller_wallet_id, buyer_wallet_id = uuid4(), uuid4()
    buyer_telegram_id = 1_000_000_000 + uuid4().int % 80_000_000
    now = datetime.now(UTC)

    async with session_factory.begin() as session:
        seller = User(
            id=seller_id,
            telegram_id=buyer_telegram_id + 1,
            first_name="Refund seller",
        )
        buyer = User(
            id=buyer_id,
            telegram_id=buyer_telegram_id,
            first_name="Refund buyer",
        )
        asset = NFTAsset(
            id=asset_id,
            asset_type=AssetType.TON_NFT,
            network="mainnet",
            external_id=f"refund-{uuid4()}",
            item_address=f"0:{uuid4().hex}{uuid4().hex}",
            owner_id=seller_id,
            name="Refund test NFT",
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
            title="Refund test listing",
        )
        order = Order(
            id=order_id,
            listing_id=listing_id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            idempotency_key=f"refund-{uuid4()}",
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
        "telegram_id": buyer_telegram_id,
        "listing_id": listing_id,
        "asset_id": asset_id,
        "seller_wallet_id": seller_wallet_id,
        "buyer_wallet_id": buyer_wallet_id,
    }


async def _cleanup(
    session_factory: async_sessionmaker[AsyncSession], ids: dict[str, object]
) -> None:
    order_id = ids["order_id"]
    async with session_factory.begin() as session:
        transaction_ids = select(PaymentTransaction.id).join(
            PaymentIntent, PaymentIntent.id == PaymentTransaction.payment_intent_id
        ).where(PaymentIntent.order_id == order_id)
        await session.execute(
            PaymentRefund.__table__.delete().where(
                PaymentRefund.payment_transaction_id.in_(transaction_ids)
            )
        )
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
            PaymentTransaction.__table__.delete().where(
                PaymentTransaction.payment_intent_id.in_(
                    select(PaymentIntent.id).where(PaymentIntent.order_id == order_id)
                )
            )
        )
        await session.execute(
            PaymentIntent.__table__.delete().where(PaymentIntent.order_id == order_id)
        )
        await session.execute(
            OrderEvent.__table__.delete().where(OrderEvent.order_id == order_id)
        )
        await session.execute(
            TelegramNotificationOutbox.__table__.delete().where(
                TelegramNotificationOutbox.order_id == order_id
            )
        )
        await session.execute(
            OrderDeliveryAttempt.__table__.delete().where(
                OrderDeliveryAttempt.order_id == order_id
            )
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
            User.__table__.delete().where(
                User.id.in_([ids["buyer_id"], ids["seller_id"]])
            )
        )


async def _create_intent(
    session_factory: async_sessionmaker[AsyncSession], ids: dict[str, object]
) -> PaymentIntent:
    async with session_factory() as session:
        return await create_stars_payment_intent(
            session,
            order_id=ids["order_id"],
            buyer_id=ids["buyer_id"],
        )


def _evidence(intent: PaymentIntent, ids: dict[str, object], *, event: str, charge: str):
    return {
        "invoice_payload": intent.invoice_payload,
        "payer_telegram_id": ids["telegram_id"],
        "total_amount": 25,
        "currency": "XTR",
        "telegram_payment_charge_id": charge,
        "provider_payment_charge_id": None,
        "provider_event_id": event,
    }


async def _record(
    session_factory: async_sessionmaker[AsyncSession],
    evidence: dict[str, object],
    *,
    now: datetime | None = None,
) -> str:
    async with session_factory() as session:
        return await record_stars_success(session, **evidence, now=now)


async def _make_refund_pending(
    session_factory: async_sessionmaker[AsyncSession],
    ids: dict[str, object],
) -> tuple[PaymentIntent, str]:
    intent = await _create_intent(session_factory, ids)
    evidence = _evidence(intent, ids, event=f"bad-payment-{uuid4()}", charge=f"charge-{uuid4()}")
    evidence["total_amount"] = 24
    result = await _record(session_factory, evidence)
    assert result == "refund_pending"
    return intent, str(evidence["telegram_payment_charge_id"])


class FakeRefundProvider:
    def __init__(
        self,
        *,
        outcome: RefundCallOutcome = RefundCallOutcome.SUCCEEDED,
        side_effect_before_ambiguous: bool = False,
        retry_after_seconds: int | None = None,
        lookup_result: RefundLookupResult | None = None,
    ) -> None:
        self.outcome = outcome
        self.side_effect_before_ambiguous = side_effect_before_ambiguous
        self.retry_after_seconds = retry_after_seconds
        self.lookup_result = lookup_result
        self.refund_calls = 0
        self.lookup_calls = 0
        self.refunded_charges: set[str] = set()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block_refund = False

    async def refund_payment(
        self, *, payer_telegram_id: int, telegram_payment_charge_id: str
    ) -> RefundCallResult:
        self.refund_calls += 1
        self.started.set()
        if self.block_refund:
            await self.release.wait()
        if self.outcome is RefundCallOutcome.SUCCEEDED or self.side_effect_before_ambiguous:
            self.refunded_charges.add(telegram_payment_charge_id)
        return RefundCallResult(
            self.outcome,
            error_code=(
                "synthetic_gateway_result"
                if self.outcome is not RefundCallOutcome.SUCCEEDED
                else None
            ),
            retry_after_seconds=self.retry_after_seconds,
        )

    async def lookup_refund(
        self, *, telegram_payment_charge_id: str
    ) -> RefundLookupResult:
        self.lookup_calls += 1
        if self.lookup_result is not None:
            return self.lookup_result
        if telegram_payment_charge_id in self.refunded_charges:
            return RefundLookupResult.REFUNDED
        return RefundLookupResult.NOT_REFUNDED


@pytest.mark.asyncio
async def test_concurrent_successful_payment_replay_is_idempotent_and_never_completes_delivery(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        evidence = _evidence(intent, ids, event=f"update-{uuid4()}", charge=f"charge-{uuid4()}")
        results = await asyncio.gather(
            _record(session_factory, evidence),
            _record(session_factory, evidence),
        )
        assert results == ["captured", "captured"]

        async with session_factory() as session:
            persisted_intent = await session.scalar(
                select(PaymentIntent).where(PaymentIntent.order_id == ids["order_id"])
            )
            transactions = (
                await session.scalars(
                    select(PaymentTransaction).where(
                        PaymentTransaction.payment_intent_id == intent.id
                    )
                )
            ).all()
            order = await session.get(Order, ids["order_id"])
            attempts = (
                await session.scalars(
                    select(OrderDeliveryAttempt).where(
                        OrderDeliveryAttempt.order_id == ids["order_id"]
                    )
                )
            ).all()
            assert persisted_intent is not None and persisted_intent.status == "paid"
            assert len(transactions) == 1 and transactions[0].status == "captured"
            assert order is not None and order.status is OrderStatus.RESERVED
            assert attempts == []
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_two_successful_charges_for_one_invoice_queue_only_the_extra_charge_for_refund(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        evidence_a = _evidence(intent, ids, event=f"update-{uuid4()}", charge=f"charge-{uuid4()}")
        evidence_b = _evidence(intent, ids, event=f"update-{uuid4()}", charge=f"charge-{uuid4()}")
        results = await asyncio.gather(
            _record(session_factory, evidence_a),
            _record(session_factory, evidence_b),
        )
        assert sorted(results) == ["captured", "refund_pending"]

        async with session_factory() as session:
            rows = (
                await session.scalars(
                    select(PaymentTransaction).where(
                        PaymentTransaction.payment_intent_id == intent.id
                    )
                )
            ).all()
            jobs = (
                await session.scalars(
                    select(PaymentRefund).where(
                        PaymentRefund.payment_transaction_id.in_(
                            select(PaymentTransaction.id).where(
                                PaymentTransaction.payment_intent_id == intent.id
                            )
                        )
                    )
                )
            ).all()
            assert sorted(row.status for row in rows) == ["captured", "refund_pending"]
            assert len(jobs) == 1
            assert jobs[0].status == "queued"
            assert jobs[0].reason_code == "duplicate_charge"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.parametrize(
    ("mismatch", "expected_error"),
    [("amount", "amount_mismatch"), ("payer", "payer_mismatch"), ("late", "order_not_live")],
)
@pytest.mark.asyncio
async def test_invalid_or_late_successful_payment_is_durable_refund_work(
    refund_database: str,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
    expected_error: str,
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        evidence = _evidence(intent, ids, event=f"update-{uuid4()}", charge=f"charge-{uuid4()}")
        now = datetime.now(UTC)
        if mismatch == "amount":
            evidence["total_amount"] = 24
        elif mismatch == "payer":
            evidence["payer_telegram_id"] = int(ids["telegram_id"]) + 100
        else:
            now += timedelta(hours=1)

        result = await _record(session_factory, evidence, now=now)
        assert result == "refund_pending"
        async with session_factory() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id
                    == evidence["telegram_payment_charge_id"]
                )
            )
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id == transaction.id
                )
            )
            assert transaction is not None and transaction.last_error_code == expected_error
            assert job is not None and job.status == "queued"
            assert job.reason_code == expected_error
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancelling_paid_order_queues_refund_and_does_not_duplicate_the_job(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        evidence = _evidence(intent, ids, event=f"update-{uuid4()}", charge=f"charge-{uuid4()}")
        assert await _record(session_factory, evidence) == "captured"
        async with session_factory() as session:
            await cancel_order(
                session,
                order_id=ids["order_id"],
                buyer_id=ids["buyer_id"],
            )
        async with session_factory() as session:
            await cancel_order(
                session,
                order_id=ids["order_id"],
                buyer_id=ids["buyer_id"],
            )
            jobs = (await session.scalars(select(PaymentRefund))).all()
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.payment_intent_id == intent.id
                )
            )
            order = await session.get(Order, ids["order_id"])
            assert len(jobs) == 1 and jobs[0].status == "queued"
            assert transaction is not None and transaction.status == "refund_pending"
            assert order is not None and order.status is OrderStatus.CANCELLED
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_lost_seller_ownership_queues_refund_for_paid_reserved_order(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        evidence = _evidence(intent, ids, event=f"update-{uuid4()}", charge=f"charge-{uuid4()}")
        assert await _record(session_factory, evidence) == "captured"
        async with session_factory() as session:
            async with session.begin():
                listing = await session.scalar(
                    select(Listing).where(Listing.id == ids["listing_id"]).with_for_update()
                )
                asset = await session.scalar(
                    select(NFTAsset).where(NFTAsset.id == ids["asset_id"]).with_for_update()
                )
                assert listing is not None and asset is not None
                await _invalidate_lost_ownership(
                    session,
                    listing=listing,
                    asset=asset,
                    current_time=datetime.now(UTC),
                )
        async with session_factory() as session:
            job = await session.scalar(select(PaymentRefund))
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.payment_intent_id == intent.id
                )
            )
            asset = await session.get(NFTAsset, ids["asset_id"])
            assert job is not None and job.status == "queued"
            assert job.reason_code == "seller_ownership_lost"
            assert transaction is not None and transaction.status == "refund_pending"
            assert asset is not None and asset.verification_status is AssetVerificationStatus.STALE
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_refund_worker_pass_never_calls_provider_twice_after_success(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent, charge_id = await _make_refund_pending(session_factory, ids)
        provider = FakeRefundProvider()
        now = datetime.now(UTC)
        async with session_factory() as session:
            first = await process_due_refunds(session, provider, now=now)
        async with session_factory() as session:
            second = await process_due_refunds(
                session, provider, now=now + timedelta(minutes=1)
            )

        async with session_factory() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id == charge_id
                )
            )
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id == transaction.id
                )
            )
            intent_row = await session.get(PaymentIntent, intent.id)
            assert first.succeeded == 1
            assert second.claimed == 0
            assert provider.refund_calls == 1
            assert transaction is not None and transaction.status == "refunded"
            assert job is not None and job.status == "succeeded"
            assert intent_row is not None and intent_row.status == "refunded"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_crash_after_provider_refund_is_reconciled_without_a_second_refund_call(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent, charge_id = await _make_refund_pending(session_factory, ids)
        provider = FakeRefundProvider(
            outcome=RefundCallOutcome.AMBIGUOUS,
            side_effect_before_ambiguous=True,
        )
        now = datetime.now(UTC)
        async with session_factory() as session:
            first = await process_due_refunds(session, provider, now=now)
        async with session_factory() as session:
            interim = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id
                    == select(PaymentTransaction.id)
                    .where(PaymentTransaction.telegram_payment_charge_id == charge_id)
                    .scalar_subquery()
                )
            )
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id == charge_id
                )
            )
            assert first.reconciliations == 1
            assert interim is not None and interim.status == "reconciliation_required"
            assert transaction is not None and transaction.status == "refund_pending"

        async with session_factory() as session:
            second = await process_due_refunds(
                session, provider, now=now + timedelta(seconds=5)
            )
        async with session_factory() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id == charge_id
                )
            )
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id == transaction.id
                )
            )
            assert second.succeeded == 1
            assert provider.refund_calls == 1
            assert provider.lookup_calls == 1
            assert transaction is not None and transaction.status == "refunded"
            assert job is not None and job.status == "succeeded"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_workers_claim_a_refund_only_once(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        await _make_refund_pending(session_factory, ids)
        provider = FakeRefundProvider()
        provider.block_refund = True
        now = datetime.now(UTC)

        async def first_worker():
            async with session_factory() as session:
                return await process_due_refunds(session, provider, now=now)

        async def second_worker():
            async with session_factory() as session:
                return await process_due_refunds(session, provider, now=now)

        first_task = asyncio.create_task(first_worker())
        await asyncio.wait_for(provider.started.wait(), timeout=5)
        second_result = await second_worker()
        provider.release.set()
        first_result = await first_task

        assert second_result.claimed == 0
        assert first_result.succeeded == 1
        assert provider.refund_calls == 1
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_retryable_provider_failure_uses_backoff_without_immediate_repeat(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        _, charge_id = await _make_refund_pending(session_factory, ids)
        provider = FakeRefundProvider(
            outcome=RefundCallOutcome.RETRYABLE_FAILURE,
            retry_after_seconds=120,
        )
        now = datetime.now(UTC)
        async with session_factory() as session:
            result = await process_due_refunds(session, provider, now=now)
        async with session_factory() as session:
            second = await process_due_refunds(session, provider, now=now + timedelta(seconds=5))
        async with session_factory() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id == charge_id
                )
            )
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id == transaction.id
                )
            )
            assert result.retried == 1
            assert second.claimed == 0
            assert provider.refund_calls == 1
            assert transaction is not None and transaction.status == "refund_pending"
            assert job is not None and job.status == "retry_wait"
            assert job.next_attempt_at >= now + timedelta(seconds=120)
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_failure_after_refund_call_recovers_by_reconciliation(
    refund_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        _, charge_id = await _make_refund_pending(session_factory, ids)
        provider = FakeRefundProvider()
        now = datetime.now(UTC)
        persist = refund_worker._persist_claim_result
        first_call = True

        async def fail_once(*args, **kwargs):
            nonlocal first_call
            if first_call:
                first_call = False
                raise RuntimeError("synthetic database failure after provider accepted refund")
            return await persist(*args, **kwargs)

        monkeypatch.setattr(refund_worker, "_persist_claim_result", fail_once)
        async with session_factory() as session:
            with pytest.raises(RuntimeError, match="synthetic database failure"):
                await process_due_refunds(session, provider, now=now)

        async with session_factory() as session:
            still_processing = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id
                    == select(PaymentTransaction.id)
                    .where(PaymentTransaction.telegram_payment_charge_id == charge_id)
                    .scalar_subquery()
                )
            )
            assert still_processing is not None
            assert still_processing.status == "processing"

        async with session_factory() as session:
            result = await process_due_refunds(
                session, provider, now=now + timedelta(minutes=2)
            )

        async with session_factory() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id == charge_id
                )
            )
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id == transaction.id
                )
            )
            assert result.succeeded == 1
            assert provider.refund_calls == 1
            assert provider.lookup_calls == 1
            assert transaction is not None and transaction.status == "refunded"
            assert job is not None and job.status == "succeeded"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_reconciliation_never_retries_refund_without_proof(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        _, charge_id = await _make_refund_pending(session_factory, ids)
        provider = FakeRefundProvider(
            outcome=RefundCallOutcome.AMBIGUOUS,
            lookup_result=RefundLookupResult.UNKNOWN,
        )
        now = datetime.now(UTC)
        async with session_factory() as session:
            first = await process_due_refunds(session, provider, now=now)
        async with session_factory() as session:
            second = await process_due_refunds(
                session, provider, now=now + timedelta(seconds=5)
            )
        async with session_factory() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id == charge_id
                )
            )
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id == transaction.id
                )
            )
            assert first.reconciliations == 1
            assert second.reconciliations == 1
            assert provider.refund_calls == 1
            assert provider.lookup_calls == 1
            assert transaction is not None and transaction.status == "refund_pending"
            assert job is not None and job.status == "reconciliation_required"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_stale_refund_job_never_calls_provider_for_captured_transaction(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        evidence = _evidence(
            intent, ids, event=f"update-{uuid4()}", charge=f"charge-{uuid4()}"
        )
        assert await _record(session_factory, evidence) == "captured"
        async with session_factory.begin() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id
                    == evidence["telegram_payment_charge_id"]
                )
            )
            assert transaction is not None and transaction.status == "captured"
            session.add(
                PaymentRefund(
                    payment_transaction_id=transaction.id,
                    status="queued",
                    reason_code="stale_test_fixture",
                    next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )

        provider = FakeRefundProvider()
        async with session_factory() as session:
            result = await process_due_refunds(session, provider)
        async with session_factory() as session:
            job = await session.scalar(select(PaymentRefund))
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id
                    == evidence["telegram_payment_charge_id"]
                )
            )
            assert result.claimed == 0
            assert provider.refund_calls == 0
            assert transaction is not None and transaction.status == "captured"
            assert job is not None and job.status == "manual_review"
            assert job.last_error_code == "transaction_not_refund_pending"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_refund_retry_requires_two_complete_negative_reconciliations(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        _, charge_id = await _make_refund_pending(session_factory, ids)
        provider = FakeRefundProvider(
            outcome=RefundCallOutcome.AMBIGUOUS,
            lookup_result=RefundLookupResult.NOT_REFUNDED,
        )
        now = datetime.now(UTC)
        async with session_factory() as session:
            first = await process_due_refunds(session, provider, now=now)
        async with session_factory() as session:
            second = await process_due_refunds(
                session, provider, now=now + timedelta(seconds=5)
            )
        async with session_factory() as session:
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id
                    == select(PaymentTransaction.id)
                    .where(PaymentTransaction.telegram_payment_charge_id == charge_id)
                    .scalar_subquery()
                )
            )
            assert first.reconciliations == 1
            assert second.reconciliations == 1
            assert provider.refund_calls == 1
            assert job is not None and job.status == "reconciliation_required"

        async with session_factory() as session:
            third = await process_due_refunds(
                session, provider, now=now + timedelta(seconds=10)
            )
        async with session_factory() as session:
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id
                    == select(PaymentTransaction.id)
                    .where(PaymentTransaction.telegram_payment_charge_id == charge_id)
                    .scalar_subquery()
                )
            )
            assert third.retried == 1
            assert provider.refund_calls == 1
            assert job is not None and job.status == "retry_wait"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


def test_refund_worker_runtime_rejects_production_before_any_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://test:test@localhost:5432/viltara_test",
        bot_token="654321:primary-token",
        telegram_stars_test_enabled=True,
        telegram_stars_test_bot_token=SecretStr("123456:dedicated-test-token"),
    )
    monkeypatch.setattr(refund_worker, "get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="cannot run in production"):
        refund_worker._validate_worker_runtime()


def test_refund_worker_runtime_rejects_non_test_database_and_shared_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_token_settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://test:test@localhost:5432/viltara_test",
        bot_token="123456:dedicated-test-token",
        telegram_stars_test_enabled=True,
        telegram_stars_test_bot_token=SecretStr("123456:dedicated-test-token"),
    )
    monkeypatch.setattr(refund_worker, "get_settings", lambda: shared_token_settings)
    with pytest.raises(RuntimeError, match="must not use the production bot token"):
        refund_worker._validate_worker_runtime()

    unsafe_database_settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://test:test@payments-prod.example:5432/viltara",
        bot_token="654321:primary-token",
        telegram_stars_test_enabled=True,
        telegram_stars_test_bot_token=SecretStr("123456:dedicated-test-token"),
    )
    monkeypatch.setattr(refund_worker, "get_settings", lambda: unsafe_database_settings)
    with pytest.raises(RuntimeError, match="dedicated test database"):
        refund_worker._validate_worker_runtime()

@pytest.mark.asyncio
async def test_refund_processing_entrypoint_rejects_production_even_with_fake_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://test:test@localhost:5432/viltara_test",
        bot_token="654321:primary-token",
        telegram_stars_test_enabled=True,
        telegram_stars_test_bot_token=SecretStr("123456:dedicated-test-token"),
    )
    monkeypatch.setattr(refund_worker, "get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="cannot run in production"):
        await process_due_refunds(None, FakeRefundProvider())  # type: ignore[arg-type]

@pytest.mark.asyncio
async def test_late_provider_success_cannot_mark_a_captured_transaction_refunded(
    refund_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch, refund_database)
    engine = create_async_engine(refund_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        evidence = _evidence(
            intent, ids, event=f"update-{uuid4()}", charge=f"charge-{uuid4()}"
        )
        assert await _record(session_factory, evidence) == "captured"
        now = datetime.now(UTC)
        lease_token = uuid4()
        async with session_factory.begin() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id
                    == evidence["telegram_payment_charge_id"]
                )
            )
            assert transaction is not None
            job = PaymentRefund(
                payment_transaction_id=transaction.id,
                status="processing",
                reason_code="invalid_stale_job",
                attempt_count=1,
                next_attempt_at=now,
                lease_token=lease_token,
                locked_until=now + timedelta(minutes=5),
            )
            session.add(job)
            await session.flush()

        async with session_factory() as session:
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id
                    == select(PaymentTransaction.id)
                    .where(PaymentTransaction.telegram_payment_charge_id
                    == evidence["telegram_payment_charge_id"])
                    .scalar_subquery()
                )
            )
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id
                    == evidence["telegram_payment_charge_id"]
                )
            )
            assert job is not None and transaction is not None
            claim = refund_worker.RefundClaim(
                refund_id=job.id,
                claim_token=lease_token,
                transaction_id=transaction.id,
                intent_id=intent.id,
                order_id=ids["order_id"],
                payer_telegram_id=int(ids["telegram_id"]),
                telegram_payment_charge_id=str(evidence["telegram_payment_charge_id"]),
                attempt_count=1,
                reconciliation_count=0,
                needs_reconciliation=False,
            )
            persisted = await refund_worker._persist_claim_result(
                session,
                claim,
                now=now,
                target_status="succeeded",
                succeeded=True,
            )
            assert persisted is False

        async with session_factory() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id
                    == evidence["telegram_payment_charge_id"]
                )
            )
            job = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id == transaction.id
                )
            )
            assert transaction is not None and transaction.status == "captured"
            assert job is not None and job.status == "manual_review"
            assert job.last_error_code == "transaction_not_refund_pending"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()
