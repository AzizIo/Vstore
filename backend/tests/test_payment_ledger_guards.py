from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
)
from app.db.payments import PaymentEvent, PaymentIntent, PaymentTransaction
from tests.database_safety import require_test_database_url

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def ledger_guard_database() -> str:
    import os

    url = require_test_database_url("Payment ledger guard integration tests")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


async def test_payment_snapshots_and_evidence_cannot_be_rewritten_or_removed(
    ledger_guard_database: str,
) -> None:
    engine = create_async_engine(ledger_guard_database, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    seller_id, buyer_id = uuid4(), uuid4()
    listing_id, asset_id, order_id = uuid4(), uuid4(), uuid4()
    intent_id, transaction_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    telegram_id = 900_000_000 + uuid4().int % 90_000_000

    try:
        async with factory() as session:
            transaction = await session.begin()
            try:
                session.add_all(
                    [
                        User(id=seller_id, telegram_id=telegram_id + 1, first_name="Seller"),
                        User(id=buyer_id, telegram_id=telegram_id, first_name="Buyer"),
                        NFTAsset(
                            id=asset_id,
                            asset_type=AssetType.TON_NFT,
                            network="mainnet",
                            external_id=f"ledger-guard-{uuid4()}",
                            item_address=f"0:{uuid4().hex}{uuid4().hex}",
                            owner_id=seller_id,
                            name="Ledger guard fixture",
                            verification_status=AssetVerificationStatus.VERIFIED,
                        ),
                    ]
                )
                await session.flush()
                session.add(
                    Listing(
                        id=listing_id,
                        asset_id=asset_id,
                        seller_id=seller_id,
                        status=ListingStatus.RESERVED,
                        price_amount=Decimal("25"),
                        price_currency=PriceCurrency.XTR,
                        title="Ledger guard fixture",
                    )
                )
                session.add(
                    Order(
                        id=order_id,
                        listing_id=listing_id,
                        buyer_id=buyer_id,
                        seller_id=seller_id,
                        idempotency_key=f"ledger-guard-{uuid4()}",
                        status=OrderStatus.RESERVED,
                        price_amount=Decimal("25"),
                        price_currency=PriceCurrency.XTR,
                        expires_at=now + timedelta(minutes=10),
                    )
                )
                await session.flush()
                session.add(
                    PaymentIntent(
                        id=intent_id,
                        order_id=order_id,
                        provider="telegram_stars",
                        status="paid",
                        amount=Decimal("25"),
                        currency="XTR",
                        payer_telegram_id=telegram_id,
                        invoice_payload=f"ledger-guard-{uuid4()}",
                        expires_at=now + timedelta(minutes=10),
                        paid_at=now,
                    )
                )
                await session.flush()
                session.add(
                    PaymentTransaction(
                        id=transaction_id,
                        payment_intent_id=intent_id,
                        provider="telegram_stars",
                        telegram_payment_charge_id=f"charge-{uuid4()}",
                        provider_payment_charge_id=f"provider-charge-{uuid4()}",
                        amount=Decimal("25"),
                        currency="XTR",
                        payer_telegram_id=telegram_id,
                        status="captured",
                        captured_at=now,
                    )
                )
                await session.flush()
                session.add(
                    PaymentEvent(
                        payment_intent_id=intent_id,
                        payment_transaction_id=transaction_id,
                        provider="telegram_stars",
                        provider_event_id=f"event-{uuid4()}",
                        event_type="payment_succeeded",
                        payload_sha256="a" * 64,
                    )
                )
                await session.flush()

                async def assert_rejected(statement, params=None) -> None:
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(statement, params or {})

                await assert_rejected(
                    text("UPDATE payment_intents SET amount = 26 WHERE id = :id"),
                    {"id": intent_id},
                )
                await assert_rejected(
                    text(
                        "UPDATE payment_transactions SET telegram_payment_charge_id = "
                        "'rewritten' WHERE id = :id"
                    ),
                    {"id": transaction_id},
                )
                await assert_rejected(
                    text("DELETE FROM payment_transactions WHERE id = :id"),
                    {"id": transaction_id},
                )
                await assert_rejected(text("TRUNCATE payment_events"))

                # Lifecycle changes remain possible; only the evidence snapshot is frozen.
                await session.execute(
                    text(
                        "UPDATE payment_transactions SET status = 'refund_pending' "
                        "WHERE id = :id"
                    ),
                    {"id": transaction_id},
                )
                status = await session.scalar(
                    text("SELECT status FROM payment_transactions WHERE id = :id"),
                    {"id": transaction_id},
                )
                assert status == "refund_pending"
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
