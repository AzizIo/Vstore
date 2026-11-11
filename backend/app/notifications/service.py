from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Order, TelegramNotificationOutbox
from app.telegram_direct_link import (
    telegram_direct_link_with_startapp,
    validate_telegram_direct_link,
)


class NotificationSender(Protocol):
    async def send_message(
        self, *, chat_id: int, text: str, disable_web_page_preview: bool = True
    ) -> object: ...


class PermanentNotificationError(Exception):
    """Telegram rejected a message for a non-retryable recipient or request."""


class TransientNotificationError(Exception):
    """Telegram or the network failed temporarily."""

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class UnsupportedNotificationEvent(PermanentNotificationError):
    """An outbox event has no explicitly supported Telegram message."""


@dataclass(frozen=True)
class NotificationDelivery:
    id: uuid.UUID
    claim_token: uuid.UUID
    recipient_telegram_id: int
    recipient_role: str
    event_type: str
    order_id: uuid.UUID
    price_amount: Decimal
    price_currency: str
    attempt_count: int


@dataclass(frozen=True)
class NotificationBatchResult:
    claimed: int = 0
    delivered: int = 0
    retried: int = 0
    failed: int = 0


async def claim_due_notifications(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[NotificationDelivery]:
    settings = get_settings()
    current_time = now or datetime.now(UTC)
    batch_limit = limit or settings.notification_batch_size
    deliveries: list[NotificationDelivery] = []

    async with session.begin():
        result = await session.execute(
            select(
                TelegramNotificationOutbox,
                Order.price_amount,
                Order.price_currency,
            )
            .join(Order, Order.id == TelegramNotificationOutbox.order_id)
            .where(
                or_(
                    (
                        (TelegramNotificationOutbox.status == "pending")
                        & (TelegramNotificationOutbox.next_attempt_at <= current_time)
                    ),
                    (
                        (TelegramNotificationOutbox.status == "processing")
                        & (TelegramNotificationOutbox.locked_until <= current_time)
                    ),
                )
            )
            .order_by(
                TelegramNotificationOutbox.next_attempt_at.asc(),
                TelegramNotificationOutbox.created_at.asc(),
            )
            .limit(batch_limit)
            .with_for_update(skip_locked=True, of=TelegramNotificationOutbox)
        )
        for notification, price_amount, price_currency in result:
            claim_token = uuid.uuid4()
            notification.status = "processing"
            notification.claim_token = claim_token
            notification.locked_until = current_time + timedelta(
                seconds=settings.notification_claim_lease_seconds
            )
            notification.attempt_count += 1
            deliveries.append(
                NotificationDelivery(
                    id=notification.id,
                    claim_token=claim_token,
                    recipient_telegram_id=notification.recipient_telegram_id,
                    recipient_role=notification.recipient_role,
                    event_type=notification.event_type,
                    order_id=notification.order_id,
                    price_amount=Decimal(price_amount),
                    price_currency=(
                        price_currency.value
                        if hasattr(price_currency, "value")
                        else str(price_currency)
                    ),
                    attempt_count=notification.attempt_count,
                )
            )

    return deliveries


async def _mark_delivered(
    session: AsyncSession, delivery: NotificationDelivery, now: datetime
) -> None:
    async with session.begin():
        notification = await session.scalar(
            select(TelegramNotificationOutbox)
            .where(
                TelegramNotificationOutbox.id == delivery.id,
                TelegramNotificationOutbox.claim_token == delivery.claim_token,
                TelegramNotificationOutbox.status == "processing",
            )
            .with_for_update()
        )
        if notification is None:
            return
        notification.status = "delivered"
        notification.delivered_at = now
        notification.locked_until = None
        notification.claim_token = None
        notification.last_error = None


async def _mark_failed_or_retry(
    session: AsyncSession,
    delivery: NotificationDelivery,
    error: Exception,
    *,
    now: datetime,
    permanent: bool,
    retry_after_seconds: int | None = None,
) -> bool:
    settings = get_settings()
    async with session.begin():
        notification = await session.scalar(
            select(TelegramNotificationOutbox)
            .where(
                TelegramNotificationOutbox.id == delivery.id,
                TelegramNotificationOutbox.claim_token == delivery.claim_token,
                TelegramNotificationOutbox.status == "processing",
            )
            .with_for_update()
        )
        if notification is None:
            return False

        notification.last_error = str(error)[:1000]
        notification.locked_until = None
        notification.claim_token = None

        if permanent or notification.attempt_count >= settings.notification_max_attempts:
            notification.status = "failed"
            return True

        base_delay = settings.notification_retry_base_seconds * (
            2 ** max(notification.attempt_count - 1, 0)
        )
        delay = retry_after_seconds if retry_after_seconds is not None else base_delay
        delay = max(1, min(delay, settings.notification_retry_max_seconds))
        notification.status = "pending"
        notification.next_attempt_at = now + timedelta(seconds=delay)
        return False


def build_notification_message(delivery: NotificationDelivery) -> str:
    order_reference = str(delivery.order_id).replace("-", "")[:8].upper()
    amount = format(delivery.price_amount.normalize(), "f")

    if delivery.event_type == "order_created":
        description = (
            "Your order was created and the listing is reserved."
            if delivery.recipient_role == "buyer"
            else "A buyer reserved your listing."
        )
        status = "Reserved"
    elif delivery.event_type == "order_cancelled":
        description = (
            "You cancelled the order."
            if delivery.recipient_role == "buyer"
            else "The buyer cancelled the order."
        )
        status = "Cancelled"
    elif delivery.event_type == "order_expired":
        description = "The order reservation expired automatically."
        status = "Expired"
    else:
        raise UnsupportedNotificationEvent(
            f"Unsupported Telegram notification event_type: {delivery.event_type!r}"
        )

    lines = [
        f"VILTARA SHOP · Order #{order_reference}",
        description,
        f"Status: {status}",
        f"Amount: {amount} {delivery.price_currency}",
    ]
    settings = get_settings()
    app_url = validate_telegram_direct_link(settings.telegram_mini_app_direct_link)
    if app_url is not None:
        order_url = telegram_direct_link_with_startapp(
            app_url,
            startapp=f"order_{delivery.order_id.hex}",
        )
        if order_url is not None:
            lines.append(f"Open in Mini App: {order_url}")

    lines.append("Payment is not enabled. No payment has been received.")
    return "\n".join(lines)


async def process_due_notifications(
    session: AsyncSession,
    sender: NotificationSender,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> NotificationBatchResult:
    current_time = now or datetime.now(UTC)
    deliveries = await claim_due_notifications(session, now=current_time, limit=limit)
    delivered = 0
    retried = 0
    failed = 0

    for delivery in deliveries:
        try:
            await sender.send_message(
                chat_id=delivery.recipient_telegram_id,
                text=build_notification_message(delivery),
                disable_web_page_preview=True,
            )
        except PermanentNotificationError as exc:
            await _mark_failed_or_retry(
                session, delivery, exc, now=current_time, permanent=True
            )
            failed += 1
        except TransientNotificationError as exc:
            is_failed = await _mark_failed_or_retry(
                session,
                delivery,
                exc,
                now=current_time,
                permanent=False,
                retry_after_seconds=exc.retry_after_seconds,
            )
            failed += int(is_failed)
            retried += int(not is_failed)
        except Exception as exc:
            is_failed = await _mark_failed_or_retry(
                session, delivery, exc, now=current_time, permanent=False
            )
            failed += int(is_failed)
            retried += int(not is_failed)
        else:
            await _mark_delivered(session, delivery, current_time)
            delivered += 1

    return NotificationBatchResult(
        claimed=len(deliveries),
        delivered=delivered,
        retried=retried,
        failed=failed,
    )
