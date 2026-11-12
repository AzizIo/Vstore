from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

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
)
from app.notifications.diagnostics import (
    NotificationOutboxHealth,
    inspect_notification_outbox,
)


def _summary(**overrides: object) -> NotificationOutboxHealth:
    values: dict[str, object] = {
        "sampled_at": datetime(2026, 11, 12, 12, 0, tzinfo=UTC),
        "max_due_age_seconds": 300,
        "pending_count": 0,
        "processing_count": 0,
        "delivered_count": 0,
        "failed_count": 0,
        "due_pending_count": 0,
        "expired_processing_lease_count": 0,
        "oldest_due_pending_age_seconds": None,
        "oldest_failed_age_seconds": None,
    }
    values.update(overrides)
    return NotificationOutboxHealth(**values)


class _FakeResult:
    def one(self):
        return SimpleNamespace(
            pending_count=0,
            processing_count=0,
            delivered_count=0,
            failed_count=0,
            due_pending_count=0,
            expired_processing_lease_count=0,
            oldest_due_pending_created_at=None,
            oldest_failed_created_at=None,
        )


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement):
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.statements.append(compiled)
        return _FakeResult()


def test_empty_queue_is_healthy() -> None:
    summary = _summary()

    assert summary.status == "healthy"
    assert summary.total_count == 0
    assert summary.degraded_reasons == ()


def test_due_pending_threshold_is_inclusive_and_only_exceeds_degrade() -> None:
    at_threshold = _summary(
        pending_count=1,
        due_pending_count=1,
        oldest_due_pending_age_seconds=300,
    )
    over_threshold = _summary(
        pending_count=1,
        due_pending_count=1,
        oldest_due_pending_age_seconds=301,
    )

    assert at_threshold.status == "healthy"
    assert over_threshold.status == "degraded"
    assert over_threshold.degraded_reasons == ("due_pending_backlog_too_old",)


def test_future_scheduled_pending_rows_do_not_degrade() -> None:
    summary = _summary(pending_count=4, due_pending_count=0)

    assert summary.status == "healthy"


def test_active_processing_lease_does_not_degrade() -> None:
    summary = _summary(processing_count=2, expired_processing_lease_count=0)

    assert summary.status == "healthy"


def test_missing_or_expired_processing_lease_degrades() -> None:
    summary = _summary(
        processing_count=1,
        expired_processing_lease_count=1,
    )

    assert summary.status == "degraded"
    assert summary.degraded_reasons == ("expired_processing_leases_present",)


def test_failed_rows_degrade_and_are_counted() -> None:
    summary = _summary(failed_count=2, oldest_failed_age_seconds=45)

    assert summary.status == "degraded"
    assert summary.total_count == 2
    assert summary.degraded_reasons == ("failed_notifications_present",)


def test_json_document_has_stable_aggregate_only_schema() -> None:
    summary = _summary(
        pending_count=2,
        processing_count=1,
        delivered_count=3,
        failed_count=1,
        due_pending_count=1,
        expired_processing_lease_count=1,
        oldest_due_pending_age_seconds=400,
        oldest_failed_age_seconds=25,
    )

    payload = summary.to_dict()
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["status"] == "degraded"
    assert payload["sampled_at"] == "2026-11-12T12:00:00Z"
    assert payload["counts"] == {
        "total": 7,
        "pending": 2,
        "processing": 1,
        "delivered": 3,
        "failed": 1,
    }
    assert payload["degraded_reasons"] == [
        "failed_notifications_present",
        "expired_processing_leases_present",
        "due_pending_backlog_too_old",
    ]
    for forbidden in (
        "telegram_id",
        "recipient",
        "order_id",
        "wallet",
        "last_error",
        "DATABASE_URL",
    ):
        assert forbidden.lower() not in serialized.lower()


@pytest.mark.asyncio
async def test_diagnostic_uses_one_select_without_row_locking_or_mutation() -> None:
    session = _FakeSession()

    summary = await inspect_notification_outbox(
        session, now=datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    )

    assert summary.status == "healthy"
    assert len(session.statements) == 1
    statement = session.statements[0].upper()
    assert statement.lstrip().startswith("SELECT")
    assert "FOR UPDATE" not in statement
    assert "UPDATE " not in statement
    assert "DELETE " not in statement


@pytest.mark.asyncio
async def test_diagnostic_rejects_negative_threshold_before_query() -> None:
    session = _FakeSession()

    with pytest.raises(ValueError, match="non-negative"):
        await inspect_notification_outbox(session, max_due_age_seconds=-1)

    assert session.statements == []


def test_cli_returns_zero_for_healthy_json(monkeypatch, capsys) -> None:
    from scripts import notification_outbox_health as cli

    async def fake_inspect(max_due_age_seconds: int):
        assert max_due_age_seconds == 300
        return _summary()

    monkeypatch.setattr(cli, "_inspect", fake_inspect)

    assert cli.main(["--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "healthy"


def test_cli_returns_one_for_degraded_queue(monkeypatch, capsys) -> None:
    from scripts import notification_outbox_health as cli

    async def fake_inspect(max_due_age_seconds: int):
        return _summary(failed_count=1)

    monkeypatch.setattr(cli, "_inspect", fake_inspect)

    assert cli.main([]) == 1
    output = capsys.readouterr().out
    assert "DEGRADED" in output
    assert "failed_notifications_present" in output


def test_cli_returns_two_without_leaking_database_exception(monkeypatch, capsys) -> None:
    from scripts import notification_outbox_health as cli

    async def fake_inspect(max_due_age_seconds: int):
        raise RuntimeError("postgresql://operator:super-secret@db/private")

    monkeypatch.setattr(cli, "_inspect", fake_inspect)

    assert cli.main([]) == 2
    captured = capsys.readouterr()
    assert "diagnostic failed" in captured.err
    assert "super-secret" not in captured.err


def test_cli_rejects_negative_threshold_with_usage_error() -> None:
    from scripts import notification_outbox_health as cli

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--max-due-age-seconds", "-1"])

    assert exc_info.value.code == 2


@pytest.fixture(scope="session")
def migrated_outbox_health_database() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("Outbox diagnostic integration test requires PostgreSQL")

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
async def outbox_health_session(migrated_outbox_health_database: str):
    engine = create_async_engine(migrated_outbox_health_database, pool_pre_ping=True)
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_diagnostic_reports_persisted_states_without_mutating_rows(
    outbox_health_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    buyer = User(
        telegram_id=910_000_000 + uuid4().int % 80_000_000,
        first_name="Buyer",
    )
    seller = User(
        telegram_id=920_000_000 + uuid4().int % 80_000_000,
        first_name="Seller",
    )
    outbox_health_session.add_all([buyer, seller])
    await outbox_health_session.flush()

    asset = NFTAsset(
        asset_type=AssetType.TON_NFT,
        external_id=f"outbox-health-{uuid4()}",
        item_address=f"0:{uuid4().hex}{uuid4().hex}",
        owner_id=seller.id,
        name="Outbox diagnostic test NFT",
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    outbox_health_session.add(asset)
    await outbox_health_session.flush()

    listing = Listing(
        asset_id=asset.id,
        seller_id=seller.id,
        status=ListingStatus.ACTIVE,
        price_amount=Decimal("2.5"),
        price_currency=PriceCurrency.TON,
        title="Outbox diagnostic test listing",
    )
    outbox_health_session.add(listing)
    await outbox_health_session.flush()

    order = Order(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        idempotency_key=f"outbox-health-{uuid4()}",
        status=OrderStatus.RESERVED,
        price_amount=Decimal("2.5"),
        price_currency=PriceCurrency.TON,
        expires_at=now + timedelta(minutes=15),
    )
    outbox_health_session.add(order)
    await outbox_health_session.flush()

    rows = [
        TelegramNotificationOutbox(
            dedupe_key=f"due-{uuid4()}",
            order_id=order.id,
            recipient_telegram_id=buyer.telegram_id,
            recipient_role="buyer",
            event_type="order_created",
            status="pending",
            attempt_count=1,
            next_attempt_at=now - timedelta(seconds=100),
            created_at=now - timedelta(seconds=500),
        ),
        TelegramNotificationOutbox(
            dedupe_key=f"scheduled-{uuid4()}",
            order_id=order.id,
            recipient_telegram_id=seller.telegram_id,
            recipient_role="seller",
            event_type="order_created",
            status="pending",
            attempt_count=1,
            next_attempt_at=now + timedelta(seconds=180),
            created_at=now - timedelta(seconds=20),
        ),
        TelegramNotificationOutbox(
            dedupe_key=f"expired-processing-{uuid4()}",
            order_id=order.id,
            recipient_telegram_id=buyer.telegram_id,
            recipient_role="buyer",
            event_type="order_created",
            status="processing",
            attempt_count=2,
            next_attempt_at=now,
            locked_until=now - timedelta(seconds=10),
            claim_token=uuid4(),
            created_at=now - timedelta(seconds=80),
        ),
        TelegramNotificationOutbox(
            dedupe_key=f"active-processing-{uuid4()}",
            order_id=order.id,
            recipient_telegram_id=seller.telegram_id,
            recipient_role="seller",
            event_type="order_created",
            status="processing",
            attempt_count=1,
            next_attempt_at=now,
            locked_until=now + timedelta(seconds=120),
            claim_token=uuid4(),
            created_at=now - timedelta(seconds=30),
        ),
        TelegramNotificationOutbox(
            dedupe_key=f"delivered-{uuid4()}",
            order_id=order.id,
            recipient_telegram_id=buyer.telegram_id,
            recipient_role="buyer",
            event_type="order_created",
            status="delivered",
            attempt_count=1,
            next_attempt_at=now,
            delivered_at=now - timedelta(seconds=2),
            created_at=now - timedelta(seconds=15),
        ),
        TelegramNotificationOutbox(
            dedupe_key=f"failed-{uuid4()}",
            order_id=order.id,
            recipient_telegram_id=seller.telegram_id,
            recipient_role="seller",
            event_type="order_created",
            status="failed",
            attempt_count=8,
            next_attempt_at=now,
            last_error="synthetic failure text must not be exposed",
            created_at=now - timedelta(seconds=25),
        ),
    ]
    outbox_health_session.add_all(rows)
    await outbox_health_session.flush()
    await outbox_health_session.commit()

    before = list(
        (
            await outbox_health_session.scalars(
                select(TelegramNotificationOutbox).order_by(
                    TelegramNotificationOutbox.dedupe_key
                )
            )
        ).all()
    )
    before_state = [
        (row.id, row.status, row.attempt_count, row.locked_until, row.claim_token)
        for row in before
    ]

    summary = await inspect_notification_outbox(
        outbox_health_session,
        now=now,
        max_due_age_seconds=300,
    )

    after = list(
        (
            await outbox_health_session.scalars(
                select(TelegramNotificationOutbox).order_by(
                    TelegramNotificationOutbox.dedupe_key
                )
            )
        ).all()
    )
    after_state = [
        (row.id, row.status, row.attempt_count, row.locked_until, row.claim_token)
        for row in after
    ]

    assert summary.total_count == 6
    assert summary.pending_count == 2
    assert summary.processing_count == 2
    assert summary.delivered_count == 1
    assert summary.failed_count == 1
    assert summary.due_pending_count == 1
    assert summary.expired_processing_lease_count == 1
    assert summary.oldest_due_pending_age_seconds == 500
    assert summary.oldest_failed_age_seconds == 25
    assert summary.status == "degraded"
    assert after_state == before_state
