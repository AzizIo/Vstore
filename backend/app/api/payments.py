from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, get_current_user_allow_blocked
from app.core.config import get_settings
from app.db.models import Order, PriceCurrency, User
from app.db.payments import PaymentIntent, PaymentRefund, PaymentTransaction
from app.db.session import get_db_session
from app.orders.payment_schemas import PaymentIntentCreateResponse, PaymentStatusResponse
from app.orders.payment_service import PaymentConflict, create_stars_payment_intent
from app.orders.telegram_stars_test import TelegramStarsTestAdapter, create_isolated_test_bot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["payments"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
PaymentUser = Annotated[User, Depends(get_current_user)]
PaymentReadUser = Annotated[User, Depends(get_current_user_allow_blocked)]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
]

_LOCAL_TEST_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres"}


def _test_payment_router_enabled(settings=None) -> bool:
    """Only expose the HTTP payment surface in a deliberately isolated test runtime."""

    settings = settings or get_settings()
    if not settings.telegram_stars_test_enabled:
        return False
    if settings.environment.strip().lower() not in {"local", "development", "test"}:
        return False
    if settings.telegram_stars_test_bot_token is None or not settings.bot_token:
        return False
    if settings.telegram_stars_test_bot_token.get_secret_value() == settings.bot_token:
        return False
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(settings.database_url)
        _ = parsed.port
    except ValueError:
        return False
    database_name = parsed.path.lstrip("/").split("?", maxsplit=1)[0]
    return (
        parsed.scheme == "postgresql+asyncpg"
        and (database_name.startswith("test_") or database_name.endswith("_test"))
        and parsed.hostname in _LOCAL_TEST_DATABASE_HOSTS
    )


def _payment_conflict(exc: PaymentConflict) -> HTTPException:
    message = str(exc)
    if message == "Order not found":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "order_not_found"})
    if message == "idempotency_payload_conflict":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "idempotency_payload_conflict"},
        )
    if any(
        marker in message.lower()
        for marker in (
            "test payments are disabled",
            "outside test environments",
            "test bot token",
            "bot_token",
            "requires postgres",
            "test-named database",
            "local postgres",
            "database url is invalid",
        )
    ):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "test_payment_runtime_unavailable"},
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "payment_not_available"},
    )


def _public_payment_status(intent: PaymentIntent, *, now: datetime) -> str:
    if intent.status == "pending" and intent.expires_at <= now:
        return "expired"
    return intent.status


def _public_refund_status(statuses: list[str], *, intent_status: str) -> str:
    if "manual_review" in statuses:
        return "manual_review"
    if "reconciliation_required" in statuses:
        return "reconciliation_required"
    if "processing" in statuses:
        return "processing"
    if "queued" in statuses or "retry_wait" in statuses:
        return "pending"
    if statuses and all(value == "succeeded" for value in statuses):
        return "succeeded"
    if intent_status == "refund_pending":
        return "pending"
    return "none"


@router.post(
    "/{order_id}/payment-intent",
    response_model=PaymentIntentCreateResponse,
    status_code=status.HTTP_200_OK,
)
async def create_payment_intent_route(
    order_id: UUID,
    session: DbSession,
    user: PaymentUser,
    idempotency_key: IdempotencyKey,
) -> PaymentIntentCreateResponse:
    """Create/replay a hosted Telegram Stars invoice for the authenticated buyer."""

    if not _test_payment_router_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "test_payment_runtime_unavailable"},
        )

    try:
        intent = await create_stars_payment_intent(
            session,
            order_id=order_id,
            buyer_id=user.id,
            idempotency_key=idempotency_key,
        )
    except PaymentConflict as exc:
        raise _payment_conflict(exc) from exc

    now = datetime.now(UTC)
    payment_status = _public_payment_status(intent, now=now)
    checkout_url: str | None = None
    if payment_status == "pending":
        bot = None
        try:
            bot = create_isolated_test_bot()
            checkout_url = await TelegramStarsTestAdapter(bot).create_invoice_link(
                intent=intent
            )
        except Exception as exc:
            # Never log exception text or request URLs because provider libraries can
            # include bearer-like bot tokens in their diagnostics.
            logger.error(
                "Stars test invoice-link creation failed; order_id=%s error_type=%s",
                order_id,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "payment_provider_unavailable"},
            ) from None
        finally:
            if bot is not None:
                await bot.session.close()

    return PaymentIntentCreateResponse(
        order_id=intent.order_id,
        payment_intent_id=intent.id,
        payment_status=payment_status,
        provider="telegram_stars",
        amount=intent.amount,
        currency="XTR",
        expires_at=intent.expires_at,
        checkout_url=checkout_url,
        last_error_code=intent.last_error_code,
    )


@router.get(
    "/{order_id}/payment",
    response_model=PaymentStatusResponse,
)
async def get_payment_status_route(
    order_id: UUID,
    session: DbSession,
    user: PaymentReadUser,
) -> PaymentStatusResponse:
    """Read server-authoritative payment and refund status for the order buyer."""

    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.buyer_id == user.id)
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "order_not_found"},
        )

    intent = await session.scalar(
        select(PaymentIntent).where(PaymentIntent.order_id == order.id)
    )
    currency = order.price_currency.value
    if intent is None:
        return PaymentStatusResponse(
            order_id=order.id,
            payment_intent_id=None,
            payment_status=(
                "not_started" if order.price_currency is PriceCurrency.XTR else "unsupported"
            ),
            provider=None,
            amount=order.price_amount,
            currency=currency,
            expires_at=order.expires_at,
            refund_status="none",
        )

    now = datetime.now(UTC)
    refund_statuses = list(
        (
            await session.scalars(
                select(PaymentRefund.status)
                .join(
                    PaymentTransaction,
                    PaymentRefund.payment_transaction_id == PaymentTransaction.id,
                )
                .where(PaymentTransaction.payment_intent_id == intent.id)
                .order_by(PaymentRefund.created_at, PaymentRefund.id)
            )
        ).all()
    )
    public_refund_status = _public_refund_status(
        refund_statuses, intent_status=intent.status
    )
    return PaymentStatusResponse(
        order_id=order.id,
        payment_intent_id=intent.id,
        payment_status=_public_payment_status(intent, now=now),
        provider="telegram_stars",
        amount=intent.amount,
        currency=intent.currency,
        expires_at=intent.expires_at,
        paid_at=intent.paid_at,
        refunded_at=intent.refunded_at,
        refund_status=public_refund_status,
        last_error_code=intent.last_error_code,
    )
