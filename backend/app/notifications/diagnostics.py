from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TelegramNotificationOutbox


@dataclass(frozen=True, slots=True)
class NotificationOutboxHealth:
    sampled_at: datetime
    max_due_age_seconds: int
    pending_count: int
    processing_count: int
    delivered_count: int
    failed_count: int
    due_pending_count: int
    expired_processing_lease_count: int
    oldest_due_pending_age_seconds: int | None
    oldest_failed_age_seconds: int | None

    @property
    def degraded_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.failed_count:
            reasons.append("failed_notifications_present")
        if self.expired_processing_lease_count:
            reasons.append("expired_processing_leases_present")
        oldest_due_age = self.oldest_due_pending_age_seconds
        if oldest_due_age is not None and oldest_due_age > self.max_due_age_seconds:
            reasons.append("due_pending_backlog_too_old")
        return tuple(reasons)

    @property
    def status(self) -> str:
        return "degraded" if self.degraded_reasons else "healthy"

    @property
    def total_count(self) -> int:
        return (
            self.pending_count
            + self.processing_count
            + self.delivered_count
            + self.failed_count
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "sampled_at": _format_utc(self.sampled_at),
            "thresholds": {
                "max_due_age_seconds": self.max_due_age_seconds,
            },
            "counts": {
                "total": self.total_count,
                "pending": self.pending_count,
                "processing": self.processing_count,
                "delivered": self.delivered_count,
                "failed": self.failed_count,
            },
            "due_pending_count": self.due_pending_count,
            "expired_processing_lease_count": self.expired_processing_lease_count,
            "oldest_due_pending_age_seconds": self.oldest_due_pending_age_seconds,
            "oldest_failed_age_seconds": self.oldest_failed_age_seconds,
            "degraded_reasons": list(self.degraded_reasons),
        }


def _format_utc(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def _age_seconds(now: datetime, occurred_at: datetime | None) -> int | None:
    if occurred_at is None:
        return None
    age = int((now - occurred_at).total_seconds())
    return max(0, age)


async def inspect_notification_outbox(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    max_due_age_seconds: int = 300,
) -> NotificationOutboxHealth:
    """Return aggregate queue health using one read-only SQL statement."""
    if max_due_age_seconds < 0:
        raise ValueError("max_due_age_seconds must be non-negative")

    sampled_at = now or datetime.now(UTC)
    state = TelegramNotificationOutbox.status
    pending = state == "pending"
    processing = state == "processing"
    failed = state == "failed"
    due_pending = pending & (TelegramNotificationOutbox.next_attempt_at <= sampled_at)
    expired_processing = processing & or_(
        TelegramNotificationOutbox.locked_until.is_(None),
        TelegramNotificationOutbox.claim_token.is_(None),
        TelegramNotificationOutbox.locked_until <= sampled_at,
    )

    statement = select(
        func.count().filter(pending).label("pending_count"),
        func.count().filter(processing).label("processing_count"),
        func.count().filter(state == "delivered").label("delivered_count"),
        func.count().filter(failed).label("failed_count"),
        func.count().filter(due_pending).label("due_pending_count"),
        func.count().filter(expired_processing).label("expired_processing_lease_count"),
        func.min(TelegramNotificationOutbox.created_at)
        .filter(due_pending)
        .label("oldest_due_pending_created_at"),
        func.min(TelegramNotificationOutbox.updated_at)
        .filter(failed)
        .label("oldest_failed_updated_at"),
    )

    row = (await session.execute(statement)).one()
    return NotificationOutboxHealth(
        sampled_at=sampled_at,
        max_due_age_seconds=max_due_age_seconds,
        pending_count=int(row.pending_count or 0),
        processing_count=int(row.processing_count or 0),
        delivered_count=int(row.delivered_count or 0),
        failed_count=int(row.failed_count or 0),
        due_pending_count=int(row.due_pending_count or 0),
        expired_processing_lease_count=int(row.expired_processing_lease_count or 0),
        oldest_due_pending_age_seconds=_age_seconds(
            sampled_at, row.oldest_due_pending_created_at
        ),
        oldest_failed_age_seconds=_age_seconds(
            sampled_at, row.oldest_failed_updated_at
        ),
    )
