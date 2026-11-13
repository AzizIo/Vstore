from __future__ import annotations

import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy import select

from app.db.models import User
from app.db.session import async_session_factory
from app.orders.payment_service import (
    PaymentConflict,
    create_stars_payment_intent,
    record_stars_success,
    validate_stars_pre_checkout,
)
from app.orders.telegram_stars_test import TelegramStarsTestAdapter

logger = logging.getLogger(__name__)
router = Router(name="viltara-stars-test")


@router.message(Command("pay"))
async def create_test_invoice(message: Message) -> None:
    """Issue an invoice only from the isolated Stars test bot."""

    if message.from_user is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Формат команды: /pay ORDER_UUID")
        return
    try:
        order_id = UUID(parts[1].strip())
    except ValueError:
        await message.answer("Некорректный ID заказа.")
        return

    async with async_session_factory() as session:
        buyer_id = await session.scalar(
            select(User.id).where(User.telegram_id == message.from_user.id)
        )
    if buyer_id is None:
        await message.answer("Ваш Telegram-аккаунт не привязан к покупателю VILTARA SHOP.")
        return

    try:
        async with async_session_factory() as session:
            intent = await create_stars_payment_intent(
                session, order_id=order_id, buyer_id=buyer_id
            )
        await TelegramStarsTestAdapter(message.bot).send_invoice(
            chat_id=message.chat.id,
            intent=intent,
        )
    except (PaymentConflict, ValueError) as exc:
        await message.answer(str(exc))
    except TelegramAPIError:
        logger.exception("Failed to send Stars test invoice")
        await message.answer(
            "Не удалось создать тестовый invoice. Попробуйте позже; повторная команда "
            "использует тот же сохранённый intent."
        )


@router.pre_checkout_query()
async def validate_pre_checkout(query: PreCheckoutQuery) -> None:
    """Answer every pre-checkout query promptly using persisted order data."""

    try:
        async with async_session_factory() as session:
            accepted = await validate_stars_pre_checkout(
                session,
                invoice_payload=query.invoice_payload,
                payer_telegram_id=query.from_user.id,
                total_amount=query.total_amount,
                currency=query.currency,
            )
    except PaymentConflict:
        logger.exception("Stars test pre-checkout validation is disabled or misconfigured")
        accepted = False
    except Exception:
        logger.exception("Stars test pre-checkout validation failed")
        accepted = False

    await query.answer(
        ok=accepted,
        error_message=None if accepted else "Заказ истёк или данные оплаты не совпадают.",
    )


@router.message(F.successful_payment)
async def persist_successful_payment(message: Message) -> None:
    """Persist Telegram's successful_payment evidence; client messages are ignored."""

    if message.from_user is None or message.successful_payment is None:
        return
    payment = message.successful_payment
    charge_id = payment.telegram_payment_charge_id
    try:
        async with async_session_factory() as session:
            result = await record_stars_success(
                session,
                invoice_payload=payment.invoice_payload,
                payer_telegram_id=message.from_user.id,
                total_amount=payment.total_amount,
                currency=payment.currency,
                telegram_payment_charge_id=charge_id,
                provider_payment_charge_id=payment.provider_payment_charge_id or None,
                provider_event_id=charge_id,
            )
    except PaymentConflict:
        logger.exception("Stars successful_payment could not be reconciled")
        await message.answer(
            "Платёж получен Telegram, но не прошёл проверку заказа. "
            "Не отправляйте оплату повторно — обратитесь в /paysupport."
        )
        return
    except Exception:
        logger.exception("Failed to persist Stars successful_payment")
        await message.answer(
            "Не удалось подтвердить состояние платежа. Не оплачивайте заказ повторно; "
            "обратитесь в /paysupport."
        )
        return

    if result == "captured":
        await message.answer(
            "Тестовый платёж подтверждён. Это не означает, что NFT уже передан: "
            "передача проверяется отдельно."
        )
    else:
        await message.answer(
            "Платёж требует возврата или дополнительной проверки. Не отправляйте оплату "
            "повторно; обратитесь в /paysupport."
        )


@router.message(Command("paysupport"))
async def payment_support(message: Message) -> None:
    await message.answer(
        "Тестовый платёж VILTARA SHOP. Укажите ID заказа и приложите Telegram "
        "payment charge ID. Не отправляйте seed-фразы или приватные ключи."
    )


@router.message(Command("terms"))
async def payment_terms(message: Message) -> None:
    await message.answer(
        "Тестовый режим Telegram Stars. Реальные продажи и публичный checkout отключены. "
        "Тестовая оплата не является escrow, не гарантирует возврат и не подтверждает "
        "передачу NFT."
    )


@router.message(Command("support"))
async def general_support(message: Message) -> None:
    await message.answer(
        "Поддержка тестового платежа: используйте /paysupport и укажите ID заказа. "
        "Не отправляйте секреты кошелька."
    )
