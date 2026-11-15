from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
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
from app.db.payments import PaymentEvent, PaymentIntent, PaymentRefund, PaymentTransaction
from app.escrow.models import EscrowDeal, EscrowListingIntent, EscrowWalletActionRecord
from app.escrow.service import EscrowActionConflict, canonical_request_sha256, create_or_replay_action
from app.orders import payment_service
from app.orders.payment_service import (
    PaymentConflict,
    create_stars_payment_intent,
    record_stars_refund_result,
    record_stars_success,
    validate_stars_pre_checkout,
)
from app.orders.service import OrderConflict, cancel_order, prepare_delivery

pytestmark = pytest.mark.integration  # PostgreSQL-only payment safety suite.
# All fixtures use synthetic accounts and the isolated test Stars configuration.
ALEMBIC_CONFIG_PATH = str(Path(__file__).resolve().parents[1] / "alembic.ini")


@pytest.fixture(scope="session")
def payment_database() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("Payment integration tests require PostgreSQL")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError:
        pytest.fail("Payment integration tests received an invalid TEST_DATABASE_URL")
    database_name = parsed.path.lstrip("/").split("?", maxsplit=1)[0]
    if not (
        database_name.startswith("test_") or database_name.endswith("_test")
    ):
        pytest.fail("Payment integration tests require a test-named database")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1", "db", "postgres"}:
        pytest.fail("Payment integration tests may connect only to a local test DB")
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        config = Config(ALEMBIC_CONFIG_PATH)
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
    """Keep payment evidence and its FK parents; isolate later tests by state and IDs.

    The CI PostgreSQL service is disposable and is dropped after the job. Ledger
    records must not be deleted or have append-only guards disabled during fixture
    cleanup. Park outstanding refund jobs in manual review and release the test
    reservation so global workers/expiry passes cannot claim this fixture again.
    """
    async with session_factory.begin() as session:
        await session.execute(
            text(
                """
                UPDATE payment_refunds
                SET status = 'manual_review',
                    lease_token = NULL,
                    locked_until = NULL,
                    completed_at = NULL,
                    last_error_code = 'test_fixture_retained'
                WHERE payment_transaction_id IN (
                    SELECT pt.id
                    FROM payment_transactions AS pt
                    JOIN payment_intents AS pi ON pi.id = pt.payment_intent_id
                    WHERE pi.order_id = :order_id
                )
                """
            ),
            {"order_id": ids["order_id"]},
        )
        await session.execute(
            text("UPDATE orders SET status = 'cancelled' WHERE id = :order_id"),
            {"order_id": ids["order_id"]},
        )
        await session.execute(
            text(
                "UPDATE listings SET status = 'active' "
                "WHERE id = :listing_id AND status = 'reserved'"
            ),
            {"listing_id": ids["listing_id"]},
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
            assert not await validate_stars_pre_checkout(
                session,
                invoice_payload=intent.invoice_payload,
                payer_telegram_id=ids["telegram_id"] + 1,
                total_amount=25,
                currency="XTR",
            )
            assert not await validate_stars_pre_checkout(
                session,
                invoice_payload=intent.invoice_payload,
                payer_telegram_id=ids["telegram_id"],
                total_amount=26,
                currency="XTR",
            )
            assert not await validate_stars_pre_checkout(
                session,
                invoice_payload=intent.invoice_payload,
                payer_telegram_id=ids["telegram_id"],
                total_amount=25,
                currency="USD",
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
            persisted_order = await session.get(Order, ids["order_id"])
            assert persisted_order is not None
            assert persisted_order.status is OrderStatus.RESERVED
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
        config = Config(ALEMBIC_CONFIG_PATH)
        # Escrow and future isolated modules may add migrations after the payment
        # refund revision. The downgrade guard must preserve the repository's
        # current single head rather than a hard-coded historical revision.
        expected_head = ScriptDirectory.from_config(config).get_current_head()
        with pytest.raises(RuntimeError, match="payment ledger|payment refund workflow"):
            await asyncio.to_thread(
                command.downgrade,
                config,
                "0011_listing_pending_review",
            )
        async with engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            assert revision == expected_head
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



async def test_payment_event_journal_is_append_only(
    payment_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch)
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        with pytest.raises(DBAPIError, match="append-only"):
            async with session_factory.begin() as session:
                event = await session.scalar(
                    select(PaymentEvent).where(
                        PaymentEvent.payment_intent_id == intent.id
                    )
                )
                assert event is not None
                event.event_type = "payment_rejected"
        async with session_factory() as session:
            persisted = await session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.payment_intent_id == intent.id
                )
            )
            assert persisted is not None
            assert persisted.event_type == "intent_created"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()



async def test_mismatched_successful_payment_is_queued_for_refund(
    payment_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_test_stars(monkeypatch)
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        evidence = _payment_evidence(
            intent,
            ids,
            update_id=f"mismatch-update-{uuid4()}",
            charge_id=f"mismatch-charge-{uuid4()}"
        )
        evidence["total_amount"] = 26
        async with session_factory() as session:
            assert await record_stars_success(session, **evidence) == "refund_pending"
        async with session_factory() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id
                    == evidence["telegram_payment_charge_id"]
                )
            )
            persisted_intent = await session.scalar(
                select(PaymentIntent).where(PaymentIntent.order_id == ids["order_id"])
            )
            assert transaction is not None
            assert transaction.status == "refund_pending"
            assert transaction.last_error_code == "amount_mismatch"
            assert persisted_intent is not None
            assert persisted_intent.status == "refund_pending"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


async def test_mismatched_currency_charge_is_retained_and_queued_for_refund(
    payment_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_test_stars(monkeypatch)
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    try:
        intent = await _create_intent(session_factory, ids)
        evidence = _payment_evidence(
            intent,
            ids,
            update_id=f"wrong-currency-update-{uuid4()}",
            charge_id=f"wrong-currency-charge-{uuid4()}",
        )
        evidence["currency"] = "USD"

        async with session_factory() as session:
            result = await record_stars_success(session, **evidence)

        assert result == "refund_pending"

        async with session_factory() as session:
            transaction = await session.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.telegram_payment_charge_id
                    == evidence["telegram_payment_charge_id"]
                )
            )
            assert transaction is not None
            assert transaction.currency == "USD"
            assert transaction.status == "refund_pending"
            assert transaction.last_error_code == "currency_mismatch"

            refund = await session.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.payment_transaction_id == transaction.id
                )
            )
            assert refund is not None
            assert refund.status == "queued"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


async def test_escrow_deal_terms_are_immutable_in_postgres(
    payment_database: str,
) -> None:
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    intent_id = uuid4()
    deal_id = uuid4()
    listing_key = uuid4().hex * 2
    seller_address = "0:" + "a" * 64
    buyer_address = "0:" + "b" * 64
    try:
        async with session_factory.begin() as session:
            session.add(
                EscrowListingIntent(
                    id=intent_id,
                    marketplace_listing_id=ids["listing_id"],
                    asset_id=ids["asset_id"],
                    seller_id=ids["seller_id"],
                    seller_wallet_id=ids["seller_wallet_id"],
                    network="testnet",
                    item_address="0:" + "c" * 64,
                    listing_key=listing_key,
                    collection_address_snapshot="0:" + "d" * 64,
                    seller_address_snapshot=seller_address,
                    price_amount=Decimal("2.5"),
                    price_currency="TON",
                    status="reserved",
                    idempotency_key=f"escrow-listing-{uuid4()}",
                )
            )
            await session.flush()
            session.add(
                EscrowDeal(
                    id=deal_id,
                    listing_intent_id=intent_id,
                    marketplace_listing_id=ids["listing_id"],
                    listing_key_snapshot=listing_key,
                    seller_id=ids["seller_id"],
                    buyer_id=ids["buyer_id"],
                    buyer_wallet_id=ids["buyer_wallet_id"],
                    network="testnet",
                    deal_salt=uuid4().hex * 2,
                    collection_address_snapshot="0:" + "d" * 64,
                    contract_address=None,
                    contract_abi_version=None,
                    item_address="0:" + "c" * 64,
                    seller_address_snapshot=seller_address,
                    buyer_address_snapshot=buyer_address,
                    price_amount=Decimal("2.5"),
                    price_currency="TON",
                    principal_nanotons=Decimal("2500000000"),
                    status="intent_created",
                    last_chain_seqno=None,
                    last_chain_logical_time=None,
                    idempotency_key=f"escrow-deal-{uuid4()}",
                )
            )

        with pytest.raises(DBAPIError):
            async with session_factory.begin() as session:
                await session.execute(
                    text(
                        "UPDATE escrow_deals SET buyer_address_snapshot = :address "
                        "WHERE id = :deal_id"
                    ),
                    {"address": "0:" + "e" * 64, "deal_id": deal_id},
                )
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()


async def test_escrow_migration_upgrade_and_downgrade_preserve_payments(
    payment_database: str,
) -> None:
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    config = Config(ALEMBIC_CONFIG_PATH)
    script = ScriptDirectory.from_config(config)
    escrow_revision = script.get_revision("e20261114_ton_escrow")
    assert escrow_revision is not None
    parent_revision = escrow_revision.down_revision
    assert isinstance(parent_revision, str)
    try:
        await asyncio.to_thread(command.downgrade, config, parent_revision)
        async with engine.connect() as connection:
            escrow_table = await connection.scalar(
                text("SELECT to_regclass('public.escrow_deals')")
            )
            payment_table = await connection.scalar(
                text("SELECT to_regclass('public.payment_intents')")
            )
            orders_table = await connection.scalar(
                text("SELECT to_regclass('public.orders')")
            )
            assert escrow_table is None
            assert payment_table == "payment_intents"
            assert orders_table == "orders"
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            assert revision == parent_revision

        await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.connect() as connection:
            escrow_table = await connection.scalar(
                text("SELECT to_regclass('public.escrow_deals')")
            )
            trigger_exists = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_trigger "
                    "WHERE tgname = 'escrow_deal_terms_immutable' AND NOT tgisinternal)"
                )
            )
            payment_table = await connection.scalar(
                text("SELECT to_regclass('public.payment_intents')")
            )
            assert escrow_table == "escrow_deals"
            assert trigger_exists is True
            assert payment_table == "payment_intents"
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            assert revision == script.get_current_head()
    finally:
        await engine.dispose()



async def test_escrow_wallet_action_idempotency_replay_is_postgres_backed(
    payment_database: str,
) -> None:
    """A durable blocked action replays by identity; changed payloads never duplicate it."""
    engine = create_async_engine(payment_database, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed_order(session_factory)
    listing_intent_id = uuid4()
    deal_id = uuid4()
    actor_id = ids["buyer_id"]
    idem_key = f"escrow-replay-{uuid4().hex[:20]}"
    request_hash = canonical_request_sha256(
        {"deal_id": str(deal_id), "action": "fund_deal", "amount": "2500000000"}
    )
    try:
        async with session_factory.begin() as session:
            session.add(
                EscrowListingIntent(
                    id=listing_intent_id,
                    marketplace_listing_id=ids["listing_id"],
                    asset_id=ids["asset_id"],
                    seller_id=ids["seller_id"],
                    seller_wallet_id=ids["seller_wallet_id"],
                    network="testnet",
                    item_address="0:" + "c" * 64,
                    listing_key=uuid4().hex * 2,
                    collection_address_snapshot="0:" + "d" * 64,
                    seller_address_snapshot="0:" + "a" * 64,
                    price_amount=Decimal("2.5"),
                    price_currency="TON",
                    status="reserved",
                    idempotency_key=f"escrow-listing-{uuid4()}",
                )
            )
            await session.flush()
            session.add(
                EscrowDeal(
                    id=deal_id,
                    listing_intent_id=listing_intent_id,
                    marketplace_listing_id=ids["listing_id"],
                    listing_key_snapshot=uuid4().hex * 2,
                    seller_id=ids["seller_id"],
                    buyer_id=actor_id,
                    buyer_wallet_id=ids["buyer_wallet_id"],
                    network="testnet",
                    deal_salt=uuid4().hex * 2,
                    collection_address_snapshot="0:" + "d" * 64,
                    contract_address=None,
                    contract_abi_version=None,
                    item_address="0:" + "c" * 64,
                    seller_address_snapshot="0:" + "a" * 64,
                    buyer_address_snapshot="0:" + "b" * 64,
                    price_amount=Decimal("2.5"),
                    price_currency="TON",
                    principal_nanotons=Decimal("2500000000"),
                    status="awaiting_buyer_funds",
                    last_chain_seqno=None,
                    last_chain_logical_time=None,
                    idempotency_key=f"escrow-deal-{uuid4()}",
                )
            )

        async with session_factory.begin() as session:
            original, created = await create_or_replay_action(
                session,
                actor_id=actor_id,
                deal_id=deal_id,
                action_type="fund_deal",
                idempotency_key=idem_key,
                request_sha256=request_hash,
            )
            assert created is True
            original_id = original.id
            original.status = "blocked_abi"
            original.last_error_code = "deployment_snapshot_incomplete"

        # A fresh DB session must replay the persisted row, not create another action.
        async with session_factory.begin() as session:
            replay, created = await create_or_replay_action(
                session,
                actor_id=actor_id,
                deal_id=deal_id,
                action_type="fund_deal",
                idempotency_key=idem_key,
                request_sha256=request_hash,
            )
            assert created is False
            assert replay.id == original_id
            assert replay.status == "blocked_abi"
            assert replay.last_error_code == "deployment_snapshot_incomplete"

        # Same key with a changed canonical payload is a conflict and must not mutate
        # or add an action row.
        changed_hash = canonical_request_sha256(
            {"deal_id": str(deal_id), "action": "fund_deal", "amount": "3500000000"}
        )
        async with session_factory() as session:
            with pytest.raises(EscrowActionConflict, match="idempotency_payload_conflict"):
                await create_or_replay_action(
                    session,
                    actor_id=actor_id,
                    deal_id=deal_id,
                    action_type="fund_deal",
                    idempotency_key=idem_key,
                    request_sha256=changed_hash,
                )
            await session.rollback()

        async with session_factory() as session:
            rows = (
                await session.scalars(
                    select(EscrowWalletActionRecord).where(
                        EscrowWalletActionRecord.actor_id == actor_id,
                        EscrowWalletActionRecord.action_type == "fund_deal",
                        EscrowWalletActionRecord.idempotency_key == idem_key,
                    )
                )
            ).all()
            assert len(rows) == 1
            assert rows[0].id == original_id
            assert rows[0].status == "blocked_abi"
            assert rows[0].last_error_code == "deployment_snapshot_incomplete"
    finally:
        await _cleanup(session_factory, ids)
        await engine.dispose()
