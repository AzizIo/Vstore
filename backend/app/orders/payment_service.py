from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Order, OrderStatus, PriceCurrency, User
from app.db.payments import (
    PaymentEvent,
    PaymentIntent,
    PaymentIntentRequest,
    PaymentRefund,
    PaymentTransaction,
)


class PaymentConflict(Exception):
    """A payment action does not match the persisted order/payment state."""


_LOCAL_TEST_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _assert_test_stars_enabled() -> None:
    """Require an isolated Telegram test bot *and* an isolated local PostgreSQL DB.

    The entrypoint checks are intentionally repeated here: service functions can be
    called outside the test-bot/refund-worker process, so a safe bot runner alone
    must not be the only barrier protecting payment mutations.
    """

    settings = get_settings()
    if not settings.telegram_stars_test_enabled:
        raise PaymentConflict("Telegram Stars test payments are disabled")
    if settings.environment.strip().lower() not in {"local", "development", "test"}:
        raise PaymentConflict(
            "Telegram Stars test payments are unavailable outside test environments"
        )
    if settings.telegram_stars_test_bot_token is None:
        raise PaymentConflict("A dedicated Telegram Stars test bot token is required")

    test_bot_token = settings.telegram_stars_test_bot_token.get_secret_value()
    if not settings.bot_token:
        raise PaymentConflict("BOT_TOKEN must be configured to verify test-token isolation")
    if hmac.compare_digest(test_bot_token, settings.bot_token):
        raise PaymentConflict("The Telegram Stars test bot token must differ from BOT_TOKEN")

    try:
        parsed = urlsplit(settings.database_url)
        # Force parsing of the port so malformed URLs fail closed before any DB write.
        _ = parsed.port
    except ValueError as exc:
        raise PaymentConflict("Telegram Stars test database URL is invalid") from exc

    if parsed.scheme != "postgresql+asyncpg":
        raise PaymentConflict("Telegram Stars test payments require PostgreSQL")
    database_name = parsed.path.lstrip("/").split("?", maxsplit=1)[0]
    if not (database_name.startswith("test_") or database_name.endswith("_test")):
        raise PaymentConflict(
            "Telegram Stars test payments require a dedicated test-named database"
        )
    if parsed.hostname not in _LOCAL_TEST_DATABASE_HOSTS:
        raise PaymentConflict(
            "Telegram Stars test payments may connect only to a local PostgreSQL host"
        )


async def queue_stars_refund(
    session: AsyncSession,
    transaction: PaymentTransaction,
    *,
    reason_code: str,
    now: datetime | None = None,
) -> PaymentRefund:
    """Idempotently enqueue one refund workflow per refund_pending charge.

    Callers must have already persisted/locked the transaction in their surrounding
    transaction. The unique transaction key is the final concurrency guard.
    """

    _assert_test_stars_enabled()
    if transaction.status != "refund_pending":
        raise PaymentConflict("Only refund_pending charges can be queued for refund")
    current_time = now or datetime.now(UTC)
    job = await session.scalar(
        select(PaymentRefund)
        .where(PaymentRefund.payment_transaction_id == transaction.id)
        .with_for_update()
    )
    if job is None:
        job = PaymentRefund(
            payment_transaction_id=transaction.id,
            status="queued",
            reason_code=(reason_code or "refund_requested")[:64],
            next_attempt_at=current_time,
        )
        session.add(job)
        await session.flush()
    elif job.status in {"queued", "retry_wait"} and job.next_attempt_at > current_time:
        job.next_attempt_at = current_time
    return job


async def create_stars_payment_intent(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    buyer_id: uuid.UUID,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> PaymentIntent:
    """Create/replay the single immutable Stars intent for an XTR order.

    With an idempotency key, an immutable PostgreSQL receipt binds that key to
    the buyer and request payload. Reusing it for another order conflicts; the
    same request returns its original intent even after its status changes.
    The bot polling path may omit the key because the order's unique intent
    remains its natural idempotency boundary.
    """

    _assert_test_stars_enabled()
    current_time = now or datetime.now(UTC)
    if idempotency_key is not None and not 8 <= len(idempotency_key) <= 128:
        raise PaymentConflict("Idempotency-Key must contain 8 to 128 characters")

    request_sha256 = _digest(
        json.dumps(
            {
                "operation": "create_stars_payment_intent",
                "buyer_id": str(buyer_id),
                "order_id": str(order_id),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    try:
        async with session.begin():
            if idempotency_key is not None:
                prior_request = await session.scalar(
                    select(PaymentIntentRequest)
                    .where(
                        PaymentIntentRequest.buyer_id == buyer_id,
                        PaymentIntentRequest.idempotency_key == idempotency_key,
                    )
                    .with_for_update()
                )
                if prior_request is not None:
                    if (
                        prior_request.order_id != order_id
                        or prior_request.request_sha256 != request_sha256
                    ):
                        raise PaymentConflict("idempotency_payload_conflict")
                    prior_intent = await session.get(
                        PaymentIntent, prior_request.payment_intent_id
                    )
                    if prior_intent is None:
                        raise PaymentConflict("Payment intent request receipt is orphaned")
                    return prior_intent

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

            intent = await session.scalar(
                select(PaymentIntent)
                .where(PaymentIntent.order_id == order.id)
                .with_for_update()
            )
            if intent is not None:
                if (
                    intent.payer_telegram_id != buyer.telegram_id
                    or intent.amount != Decimal(order.price_amount)
                    or intent.currency != "XTR"
                ):
                    raise PaymentConflict("Existing payment intent does not match the order")
                if intent.status != "pending":
                    raise PaymentConflict(
                        "Existing Stars invoice is no longer accepting payments"
                    )
            else:
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
                            f"{intent.id}:{intent.order_id}:{intent.amount}:XTR:"
                            f"{intent.payer_telegram_id}"
                        ),
                    )
                )

            if idempotency_key is not None:
                session.add(
                    PaymentIntentRequest(
                        buyer_id=buyer_id,
                        order_id=order_id,
                        payment_intent_id=intent.id,
                        idempotency_key=idempotency_key,
                        request_sha256=request_sha256,
                    )
                )
                await session.flush()
            return intent
    except IntegrityError as exc:
        # Concurrent callers may race to bind the same key. The unique key is
        # authoritative; after the losing transaction rolls back, resolve only
        # an identical durable receipt, otherwise report a conflict.
        await session.rollback()
        if idempotency_key is not None:
            prior_request = await session.scalar(
                select(PaymentIntentRequest).where(
                    PaymentIntentRequest.buyer_id == buyer_id,
                    PaymentIntentRequest.idempotency_key == idempotency_key,
                )
            )
            if prior_request is not None:
                if (
                    prior_request.order_id != order_id
                    or prior_request.request_sha256 != request_sha256
                ):
                    raise PaymentConflict("idempotency_payload_conflict") from exc
                prior_intent = await session.get(
                    PaymentIntent, prior_request.payment_intent_id
                )
                if prior_intent is not None:
                    return prior_intent
        raise


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
    """Persist a provider charge; any extra, late or mismatched charge is refundable."""

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
        duplicate_event = await session.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == "telegram_stars",
                PaymentEvent.provider_event_id == provider_event_id,
            )
        )
        if duplicate_event is not None:
            if duplicate_event.payload_sha256 != digest:
                raise PaymentConflict("Telegram update ID was replayed with different payment data")
            transaction = (
                await session.scalar(
                    select(PaymentTransaction).where(
                        PaymentTransaction.id == duplicate_event.payment_transaction_id
                    )
                )
                if duplicate_event.payment_transaction_id is not None
                else None
            )
            return transaction.status if transaction is not None else "duplicate"

        order_id = await session.scalar(
            select(PaymentIntent.order_id).where(
                PaymentIntent.invoice_payload == invoice_payload
            )
        )
        if order_id is None:
            raise PaymentConflict("Successful payment references an unknown invoice")

        # The order row is always locked before its payment rows to match delivery preparation.
        order = await session.scalar(
            select(Order).where(Order.id == order_id).with_for_update()
        )
        if order is None:
            raise PaymentConflict("Payment order no longer exists")

        # Recheck after acquiring the order lock: concurrent delivery of the same
        # Telegram update may have committed while this transaction was waiting.
        duplicate_event = await session.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == "telegram_stars",
                PaymentEvent.provider_event_id == provider_event_id,
            )
        )
        if duplicate_event is not None:
            if duplicate_event.payload_sha256 != digest:
                raise PaymentConflict("Telegram update ID was replayed with different payment data")
            duplicate_transaction = (
                await session.scalar(
                    select(PaymentTransaction).where(
                        PaymentTransaction.id == duplicate_event.payment_transaction_id
                    )
                )
                if duplicate_event.payment_transaction_id is not None
                else None
            )
            return (
                duplicate_transaction.status
                if duplicate_transaction is not None
                else "duplicate"
            )

        intent = await session.scalar(
            select(PaymentIntent)
            .where(
                PaymentIntent.invoice_payload == invoice_payload,
                PaymentIntent.order_id == order.id,
            )
            .with_for_update()
        )
        if intent is None:
            raise PaymentConflict("Payment intent changed while processing the update")

        existing_charge = await session.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.telegram_payment_charge_id == telegram_payment_charge_id
            )
        )
        if existing_charge is not None:
            if existing_charge.payment_intent_id != intent.id:
                raise PaymentConflict("Telegram charge ID is already bound to another invoice")
            if (
                existing_charge.amount != Decimal(total_amount)
                or existing_charge.currency != currency
                or existing_charge.payer_telegram_id != payer_telegram_id
                or existing_charge.provider_payment_charge_id
                != (provider_payment_charge_id or None)
            ):
                raise PaymentConflict("Telegram charge ID was replayed with different payment data")
            session.add(
                PaymentEvent(
                    payment_intent_id=intent.id,
                    payment_transaction_id=existing_charge.id,
                    provider="telegram_stars",
                    provider_event_id=provider_event_id,
                    event_type=(
                        "payment_succeeded"
                        if existing_charge.status == "captured"
                        else "payment_rejected"
                    ),
                    payload_sha256=digest,
                )
            )
            await session.flush()
            return existing_charge.status

        amount_matches = (
            intent.amount == intent.amount.to_integral_value()
            and total_amount == int(intent.amount)
        )
        expected_payer = await session.scalar(
            select(User.telegram_id).where(User.id == order.buyer_id)
        )
        payer_matches = (
            payer_telegram_id == intent.payer_telegram_id
            and payer_telegram_id == expected_payer
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
        is_first_payment = intent.status == "pending" and valid
        transaction_status = "captured" if is_first_payment else "refund_pending"

        error_code = (
            "currency_mismatch"
            if currency != "XTR"
            else "amount_mismatch"
            if not amount_matches
            else "payer_mismatch"
            if not payer_matches
            else "duplicate_charge"
            if intent.status == "paid"
            else "order_not_live"
            if not order_is_live
            else "intent_not_pending"
        )
        transaction = PaymentTransaction(
            payment_intent_id=intent.id,
            telegram_payment_charge_id=telegram_payment_charge_id,
            provider_payment_charge_id=provider_payment_charge_id or None,
            amount=Decimal(total_amount),
            currency=currency,
            payer_telegram_id=payer_telegram_id,
            status=transaction_status,
            captured_at=current_time,
            refund_requested_at=None if is_first_payment else current_time,
            last_error_code=None if is_first_payment else error_code,
        )
        session.add(transaction)
        await session.flush()

        if not is_first_payment:
            await queue_stars_refund(
                session,
                transaction,
                reason_code=error_code,
                now=current_time,
            )
            session.add(
                PaymentEvent(
                    payment_intent_id=intent.id,
                    payment_transaction_id=transaction.id,
                    provider="telegram_stars",
                    provider_event_id=f"refund-request:{transaction.id}",
                    event_type="refund_requested",
                    payload_sha256=_digest(f"{transaction.id}:{error_code}"),
                )
            )

        if is_first_payment:
            intent.status = "paid"
            intent.paid_at = current_time
        elif intent.status == "pending":
            intent.status = "refund_pending"
            intent.refund_requested_at = current_time
            intent.last_error_code = error_code

        session.add(
            PaymentEvent(
                payment_intent_id=intent.id,
                payment_transaction_id=transaction.id,
                provider="telegram_stars",
                provider_event_id=provider_event_id,
                event_type=(
                    "payment_succeeded" if is_first_payment else "payment_rejected"
                ),
                payload_sha256=digest,
            )
        )
        await session.flush()
        return transaction.status


async def record_stars_refund_result(
    session: AsyncSession,
    *,
    transaction_id: uuid.UUID,
    provider_event_id: str,
    succeeded: bool,
    error_code: str | None = None,
    now: datetime | None = None,
) -> str:
    """Persist a definitive refund result while keeping the durable job in sync.

    Ambiguous transport outcomes must not be passed here as succeeded=False:
    the worker reconciles those against Telegram's transaction history first.
    """

    _assert_test_stars_enabled()
    current_time = now or datetime.now(UTC)
    if not provider_event_id:
        raise PaymentConflict("Refund event ID is required")

    async with session.begin():
        transaction_header = await session.execute(
            select(PaymentTransaction.payment_intent_id, PaymentIntent.order_id)
            .join(PaymentIntent, PaymentIntent.id == PaymentTransaction.payment_intent_id)
            .where(PaymentTransaction.id == transaction_id)
        )
        header = transaction_header.first()
        if header is None:
            raise PaymentConflict("Payment transaction not found")
        intent_id, order_id = header

        # Keep a consistent lock order: order -> intent -> transaction -> refund workflow.
        order = await session.scalar(
            select(Order).where(Order.id == order_id).with_for_update()
        )
        intent = await session.scalar(
            select(PaymentIntent).where(PaymentIntent.id == intent_id).with_for_update()
        )
        transaction = await session.scalar(
            select(PaymentTransaction)
            .where(PaymentTransaction.id == transaction_id)
            .with_for_update()
        )
        if order is None or intent is None or transaction is None:
            raise PaymentConflict("Payment refund target no longer exists")

        job = await session.scalar(
            select(PaymentRefund)
            .where(PaymentRefund.payment_transaction_id == transaction.id)
            .with_for_update()
        )
        if job is None:
            if transaction.status not in {"refund_pending", "refunded"}:
                raise PaymentConflict("Payment transaction is not awaiting a refund")
            job = PaymentRefund(
                payment_transaction_id=transaction.id,
                status="queued",
                reason_code=(transaction.last_error_code or "refund_result_received")[:64],
                next_attempt_at=current_time,
            )
            session.add(job)
            await session.flush()

        digest = _digest(
            f"{transaction.id}:{transaction.telegram_payment_charge_id}:"
            f"{'succeeded' if succeeded else 'failed'}:{error_code or ''}"
        )
        duplicate = await session.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == "telegram_stars",
                PaymentEvent.provider_event_id == provider_event_id,
            )
        )
        if duplicate is not None:
            if duplicate.payload_sha256 != digest:
                raise PaymentConflict("Refund event ID was replayed with different data")
            return transaction.status

        if transaction.status == "refunded":
            job.status = "succeeded"
            job.completed_at = job.completed_at or current_time
            job.lease_token = None
            job.locked_until = None
            return "refunded"
        if transaction.status != "refund_pending":
            raise PaymentConflict("Payment transaction is not awaiting a refund")

        if succeeded:
            transaction.status = "refunded"
            transaction.refunded_at = current_time
            transaction.last_error_code = None
            job.status = "succeeded"
            job.completed_at = current_time
            job.last_error_code = None
            event_type = "refund_succeeded"
        else:
            settings = get_settings()
            job.attempt_count += 1
            delay = min(
                settings.payment_refund_retry_base_seconds
                * (2 ** min(max(job.attempt_count - 1, 0), 30)),
                settings.payment_refund_retry_max_seconds,
            )
            transaction.last_error_code = (error_code or "refund_failed")[:64]
            job.status = "retry_wait"
            job.next_attempt_at = current_time + timedelta(seconds=delay)
            job.last_error_code = transaction.last_error_code
            event_type = "refund_failed"

        job.lease_token = None
        job.locked_until = None

        captured_count = await session.scalar(
            select(func.count())
            .select_from(PaymentTransaction)
            .where(
                PaymentTransaction.payment_intent_id == intent.id,
                PaymentTransaction.status == "captured",
            )
        )
        pending_count = await session.scalar(
            select(func.count())
            .select_from(PaymentTransaction)
            .where(
                PaymentTransaction.payment_intent_id == intent.id,
                PaymentTransaction.status == "refund_pending",
            )
        )
        if captured_count == 0 and pending_count == 0:
            intent.status = "refunded"
            intent.refunded_at = current_time

        session.add(
            PaymentEvent(
                payment_intent_id=intent.id,
                payment_transaction_id=transaction.id,
                provider="telegram_stars",
                provider_event_id=provider_event_id,
                event_type=event_type,
                payload_sha256=digest,
            )
        )
        await session.flush()
        return transaction.status
