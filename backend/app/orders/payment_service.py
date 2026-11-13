from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Order, OrderStatus, PriceCurrency, User
from app.db.payments import PaymentEvent, PaymentIntent


class PaymentConflict(Exception):
    """A payment action does not match the persisted order/payment state."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _assert_test_stars_enabled() -> None:
    settings = get_settings()
    if not settings.telegram_stars_test_enabled:
        raise PaymentConflict("Telegram Stars test payments are disabled")
    if settings.environment.lower() not in {"local", "development", "test"}:
        raise PaymentConflict("Telegram Stars test payments are unavailable outside test environments")
    if settings.telegram_stars_test_bot_token is None:
        raise PaymentConflict("A dedicated Telegram Stars test bot token is required")


async def create_stars_payment_intent(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    buyer_id: uuid.UUID,
    now: datetime | None = None,
) -> PaymentIntent:
    """Create or return the single immutable Stars intent for an XTR order."""

    _assert_test_stars_enabled()
    current_time = now or datetime.now(UTC)

    async with session.begin():
        order = await session.scalar(
            select(Order).where(Order.id == order_id).with_for_update()
        )
        if order is None or order.buyer_id != buyer_id:
            raise PaymentConflict("Order not found")
        if order.price_currency is not PriceCurrency.XTR:
            raise PaymentConflict("Only XTR orders can use Telegram Stars")
        if order.status is not OrderStatus.RESERVED or order.expires_at <= current_time:
            raise PaymentConflict("Order is no longer available for payment")

        buyer = await session.scalar(select(User).where(User.id == buyer_id))
        if buyer is None or buyer.telegram_id <= 0:
            raise PaymentConflict("The order buyer has no valid Telegram identity")

        existing = await session.scalar(
            select(PaymentIntent)
            .where(PaymentIntent.order_id == order.id)
            .with_for_update()
        )
        if existing is not None:
            if (
                existing.payer_telegram_id != buyer.telegram_id
                or existing.amount != Decimal(order.price_amount)
                or existing.currency != "XTR"
            ):
                raise PaymentConflict("Existing payment intent does not match the order")
            return existing

        amount = Decimal(order.price_amount)
        if amount != amount.to_integral_value():
            raise PaymentConflict("Telegram Stars order amount must be a whole number")
        payload = secrets.token_urlsafe(32)
        intent = PaymentIntent(
            order_id=order.id,
            status="pending",
            amount=amount,
            currency="XTR",
            payer_telegram_id=buyer.telegram_id,
            invoice_payload=payload,
            expires_at=order.expires_at,
        )
        session.add(intent)
        await session.flush()
        session.add(
            PaymentEvent(
                payment_intent_id=intent.id,
                provider="telegram_stars",
                provider_event_id=f"intent:{intent.id}",
                event_type="intent_created",
                payload_sha256=_digest(
                    f"{intent.id}:{intent.order_id}:{intent.amount}:XTR:{intent.payer_telegram_id}"
                ),
            )
        )
        return intent


async def validate_stars_pre_checkout(
    session: AsyncSession,
    *,
    invoice_payload: str,
    payer_telegram_id: int,
    total_amount: int,
    currency: str,
    now: datetime | None = None,
) -> bool:
    """Validate a pre-checkout query against the immutable server-side snapshot."""

    _assert_test_stars_enabled()
    current_time = now or datetime.now(UTC)
    intent = await session.scalar(
        select(PaymentIntent).where(PaymentIntent.invoice_payload == invoice_payload)
    )
    if intent is None:
        return False
    order = await session.scalar(select(Order).where(Order.id == intent.order_id))
    return bool(
        order is not None
        and intent.status == "pending"
        and order.status is OrderStatus.RESERVED
        and intent.expires_at > current_time
        and order.expires_at > current_time
        and intent.payer_telegram_id == payer_telegram_id
        and total_amount == int(intent.amount)
        and intent.amount == intent.amount.to_integral_value()
        and currency == "XTR"
        and intent.currency == "XTR"
    )


async def record_stars_success(
    session: AsyncSession,
    *,
    invoice_payload: str,
    payer_telegram_id: int,
    total_amount: int,
    currency: str,
    telegram_payment_charge_id: str,
    provider_payment_charge_id: str | None,
    provider_event_id: str,
    now: datetime | None = None,
) -> str:
    """Persist trusted successful_payment evidence; return paid or refund_pending.

    A late or mismatched charge is not silently discarded: it is recorded as
    refund_pending so the bot worker can issue/reconcile a full Stars refund.
    """

    _assert_test_stars_enabled()
    current_time = now or datetime.now(UTC)
    if not telegram_payment_charge_id or not provider_event_id:
        raise PaymentConflict("Telegram payment evidence is missing a required identifier")

    digest = _digest(
        "|".join(
            (
                invoice_payload,
                str(payer_telegram_id),
                str(total_amount),
                currency,
                telegram_payment_charge_id,
                provider_payment_charge_id or "",
            )
        )
    )

    async with session.begin():
        duplicate = await session.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == "telegram_stars",
                PaymentEvent.provider_event_id == provider_event_id,
            )
        )
        if duplicate is not None:
            if duplicate.payload_sha256 != digest:
                raise PaymentConflict("Telegram update ID was replayed with different payment data")
            intent = await session.scalar(
                select(PaymentIntent).where(PaymentIntent.id == duplicate.payment_intent_id)
            )
            return intent.status if intent is not None else "unknown"

        intent = await session.scalar(
            select(PaymentIntent)
            .where(PaymentIntent.invoice_payload == invoice_payload)
            .with_for_update()
        )
        if intent is None:
            raise PaymentConflict("Successful payment references an unknown invoice")

        order = await session.scalar(
            select(Order).where(Order.id == intent.order_id).with_for_update()
        )
        if order is None:
            raise PaymentConflict("Payment order no longer exists")

        if intent.status == "paid":
            if intent.telegram_payment_charge_id == telegram_payment_charge_id:
                return "paid"
            raise PaymentConflict("A different Telegram charge already paid this intent")
        if intent.status in {"refunded", "refund_pending"}:
            return intent.status
        if intent.status != "pending":
            raise PaymentConflict("Payment intent is not accepting successful payments")

        amount_matches = (
            intent.amount == intent.amount.to_integral_value()
            and total_amount == int(intent.amount)
        )
        payer_matches = (
            payer_telegram_id == intent.payer_telegram_id
            and payer_telegram_id == (
                await session.scalar(select(User.telegram_id).where(User.id == order.buyer_id))
            )
        )
        order_is_live = (
            order.status is OrderStatus.RESERVED
            and order.expires_at > current_time
            and intent.expires_at > current_time
        )
        valid = (
            currency == "XTR"
            and intent.currency == "XTR"
            and amount_matches
            and payer_matches
            and order_is_live
        )

        intent.telegram_payment_charge_id = telegram_payment_charge_id
        intent.provider_payment_charge_id = provider_payment_charge_id or None
        if valid:
            intent.status = "paid"
            intent.paid_at = current_time
            event_type = "payment_succeeded"
        else:
            intent.status = "refund_pending"
            intent.last_error_code = (
                "currency_mismatch"
                if currency != "XTR"
                else "amount_mismatch"
                if not amount_matches
                else "payer_mismatch"
                if not payer_matches
                else "order_not_live"
            )
            intent.refund_requested_at = current_time
            event_type = "payment_rejected"

        session.add(
            PaymentEvent(
                payment_intent_id=intent.id,
                provider="telegram_stars",
                provider_event_id=provider_event_id,
                event_type=event_type,
                payload_sha256=digest,
            )
        )
        await session.flush()
        return intent.status
