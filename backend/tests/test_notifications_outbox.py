from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.assets.ton_nft.models import VerificationResult, VerificationStatus
from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    Order,
    PriceCurrency,
    TelegramNotificationOutbox,
    User,
    Wallet,
)
from app.notifications.service import (
    PermanentNotificationError,
    TransientNotificationError,
    process_due_notifications,
)
from app.orders.service import cancel_order, create_order, expire_pending_orders

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def migrated_notifications_database() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("Notification integration tests require PostgreSQL")
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


@pytest.fixture
async def notification_session(migrated_notifications_database: str):
    engine = create_async_engine(migrated_notifications_database, pool_pre_ping=True)
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


class VerifiedOwnerStub:
    """Stand-in for TONNFTVerifier that reports the expected owner as current."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session
        self.calls: list[tuple[str, str]] = []
        self.status = VerificationStatus.VERIFIED

    async def verify(self, item_address: str, expected_owner_address: str):
        if self.session is not None:
            assert not self.session.in_transaction(), (
                "provider checks must run outside database transactions"
            )
        self.calls.append((item_address, expected_owner_address))
        return VerificationResult(
            status=self.status,
            item_address=item_address,
            owner_address=expected_owner_address,
            expected_owner_address=expected_owner_address,
        )


async def _seed_active_listing(
    session: AsyncSession,
) -> tuple[User, User, Listing, Wallet]:
    suffix = uuid4().int % 1_000_000_000
    buyer = User(telegram_id=700_000_000 + suffix, first_name="Buyer")
    seller = User(telegram_id=800_000_000 + suffix, first_name="Seller")
    session.add_all([buyer, seller])
    await session.flush()

    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        external_id=f"notification-{uuid4()}",
        item_address=f"0:{uuid4().hex}{uuid4().hex}",
        owner_id=seller.id,
        name="Notification test NFT",
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
        title="Notification test listing",
    )
    session.add(listing)
    await session.flush()
    await session.commit()
    return buyer, seller, listing, wallet


class _FakeSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[tuple[int, str]] = []

    async def send_message(
        self, *, chat_id: int, text: str, disable_web_page_preview: bool = True
    ) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((chat_id, text))


async def _outbox_rows(session: AsyncSession) -> list[TelegramNotificationOutbox]:
    rows = await session.scalars(
        select(TelegramNotificationOutbox).order_by(TelegramNotificationOutbox.created_at)
    )
    return list(rows)


async def test_order_creation_enqueues_both_recipients_once(
    notification_session: AsyncSession,
) -> None:
    buyer, seller, listing, wallet = await _seed_active_listing(notification_session)

    order_id = await create_order(
        notification_session,
        buyer_id=buyer.id,
        listing_id=listing.id,
        idempotency_key="notification-create-once",
        verifier=VerifiedOwnerStub(notification_session),
    )
    await notification_session.commit()
    replayed_id = await create_order(
        notification_session,
        buyer_id=buyer.id,
        listing_id=listing.id,
        idempotency_key="notification-create-once",
        verifier=VerifiedOwnerStub(notification_session),
    )

    assert replayed_id == order_id
    rows = await _outbox_rows(notification_session)
    assert len(rows) == 2
    assert {row.event_type for row in rows} == {"order_created"}
    assert {row.recipient_role for row in rows} == {"buyer", "seller"}
    assert {row.recipient_telegram_id for row in rows} == {
        buyer.telegram_id,
        seller.telegram_id,
    }


async def test_cancel_and_expiry_enqueue_both_parties_atomically(
    notification_session: AsyncSession,
) -> None:
    buyer, _, listing, wallet = await _seed_active_listing(notification_session)

    cancelled_id = await create_order(
        notification_session,
        buyer_id=buyer.id,
        listing_id=listing.id,
        idempotency_key="notification-cancel",
        verifier=VerifiedOwnerStub(notification_session),
    )
    await notification_session.commit()
    await cancel_order(
        notification_session, order_id=cancelled_id, buyer_id=buyer.id
    )
    await notification_session.commit()

    expired_id = await create_order(
        notification_session,
        buyer_id=buyer.id,
        listing_id=listing.id,
        idempotency_key="notification-expire",
        verifier=VerifiedOwnerStub(notification_session),
    )
    order = await notification_session.get(Order, expired_id)
    assert order is not None
    expiry_time = order.expires_at + timedelta(seconds=1)
    await notification_session.commit()
    expired_count = await expire_pending_orders(
        notification_session, now=expiry_time
    )

    assert expired_count == 1
    rows = await _outbox_rows(notification_session)
    assert len(rows) == 8
    assert sum(row.event_type == "order_created" for row in rows) == 4
    assert sum(row.event_type == "order_cancelled" for row in rows) == 2
    assert sum(row.event_type == "order_expired" for row in rows) == 2
    for event_type in ("order_created", "order_cancelled", "order_expired"):
        recipients = {
            row.recipient_role for row in rows if row.event_type == event_type
        }
        assert recipients == {"buyer", "seller"}


async def test_worker_delivers_and_does_not_claim_delivered_rows_again(
    notification_session: AsyncSession,
) -> None:
    buyer, _, listing, wallet = await _seed_active_listing(notification_session)
    await create_order(
        notification_session,
        buyer_id=buyer.id,
        listing_id=listing.id,
        idempotency_key="notification-delivery-success",
        verifier=VerifiedOwnerStub(notification_session),
    )
    await notification_session.commit()

    sender = _FakeSender()
    first = await process_due_notifications(notification_session, sender)
    second = await process_due_notifications(notification_session, sender)

    assert (first.claimed, first.delivered, first.retried, first.failed) == (2, 2, 0, 0)
    assert second.claimed == 0
    assert len(sender.sent) == 2
    assert all("Сумма: 1.25 TON" in message for _, message in sender.sent)
    assert all("Оплата пока не подключена. Платёж не принимался." in message for _, message in sender.sent)
    rows = await _outbox_rows(notification_session)
    assert {row.status for row in rows} == {"delivered"}
    assert all(row.delivered_at is not None for row in rows)


async def test_worker_retries_transient_errors_with_bounded_backoff(
    notification_session: AsyncSession,
) -> None:
    buyer, _, listing, wallet = await _seed_active_listing(notification_session)
    await create_order(
        notification_session,
        buyer_id=buyer.id,
        listing_id=listing.id,
        idempotency_key="notification-delivery-retry",
        verifier=VerifiedOwnerStub(notification_session),
    )
    await notification_session.commit()

    now = datetime.now(UTC)
    failing_sender = _FakeSender(TransientNotificationError("temporary outage"))
    first = await process_due_notifications(
        notification_session, failing_sender, now=now
    )
    rows = await _outbox_rows(notification_session)

    assert first.claimed == 2
    assert first.retried == 2
    assert {row.status for row in rows} == {"pending"}
    assert all(row.attempt_count == 1 for row in rows)
    assert all(row.next_attempt_at > now for row in rows)
    await notification_session.commit()

    recovered_sender = _FakeSender()
    second = await process_due_notifications(
        notification_session,
        recovered_sender,
        now=now + timedelta(hours=2),
    )
    assert second.delivered == 2
    assert len(recovered_sender.sent) == 2
    assert {row.status for row in await _outbox_rows(notification_session)} == {"delivered"}


async def test_worker_records_permanent_failures_without_retry(
    notification_session: AsyncSession,
) -> None:
    buyer, _, listing, wallet = await _seed_active_listing(notification_session)
    await create_order(
        notification_session,
        buyer_id=buyer.id,
        listing_id=listing.id,
        idempotency_key="notification-permanent-failure",
        verifier=VerifiedOwnerStub(notification_session),
    )
    await notification_session.commit()

    sender = _FakeSender(PermanentNotificationError("bot was blocked"))
    result = await process_due_notifications(notification_session, sender)
    rows = await _outbox_rows(notification_session)

    assert result.failed == 2
    assert result.retried == 0
    assert {row.status for row in rows} == {"failed"}
    assert all(row.last_error == "bot was blocked" for row in rows)
    assert all(row.attempt_count == 1 for row in rows)


async def test_worker_respects_claim_leases_for_duplicate_processing(
    notification_session: AsyncSession,
) -> None:
    buyer, _, listing, wallet = await _seed_active_listing(notification_session)
    await create_order(
        notification_session,
        buyer_id=buyer.id,
        listing_id=listing.id,
        idempotency_key="notification-claim-lease",
        verifier=VerifiedOwnerStub(notification_session),
    )
    await notification_session.commit()

    now = datetime.now(UTC)
    sender = _FakeSender(TransientNotificationError("temporary outage"))
    first = await process_due_notifications(notification_session, sender, now=now)
    second = await process_due_notifications(notification_session, sender, now=now)

    assert first.claimed == 2
    assert second.claimed == 0
    assert {row.attempt_count for row in await _outbox_rows(notification_session)} == {1}



async def test_transient_retries_stop_at_configured_max_attempts(
    notification_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import app.notifications.service as notification_service

    buyer, _, listing, wallet = await _seed_active_listing(notification_session)
    await create_order(
        notification_session,
        buyer_id=buyer.id,
        listing_id=listing.id,
        idempotency_key="notification-max-attempts",
        verifier=VerifiedOwnerStub(notification_session),
    )
    await notification_session.commit()

    monkeypatch.setattr(
        notification_service,
        "get_settings",
        lambda: SimpleNamespace(
            notification_batch_size=10,
            notification_claim_lease_seconds=300,
            notification_max_attempts=2,
            notification_retry_base_seconds=5,
            notification_retry_max_seconds=30,
            telegram_mini_app_direct_link=None,
        ),
    )

    now = datetime.now(UTC)
    sender = _FakeSender(TransientNotificationError("still unavailable"))
    first = await process_due_notifications(notification_session, sender, now=now)
    assert first.retried == 2
    await notification_session.commit()

    second = await process_due_notifications(
        notification_session, sender, now=now + timedelta(seconds=10)
    )
    assert second.failed == 2
    rows = await _outbox_rows(notification_session)
    assert {row.status for row in rows} == {"failed"}
    assert {row.attempt_count for row in rows} == {2}
