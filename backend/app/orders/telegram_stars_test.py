from __future__ import annotations

from aiogram import Bot
from aiogram.types import LabeledPrice

from app.db.payments import PaymentIntent


class TelegramStarsTestAdapter:
    """Telegram Stars transport bound to a dedicated test bot instance."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_invoice(self, *, chat_id: int, intent: PaymentIntent) -> None:
        amount = int(intent.amount)
        if intent.amount != amount or amount <= 0:
            raise ValueError("Telegram Stars invoice amount must be a positive integer")
        await self._bot.send_invoice(
            chat_id=chat_id,
            title="VILTARA SHOP — тестовый платёж",
            description="Тестовый сценарий оплаты. Реальные средства не списываются.",
            payload=intent.invoice_payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Тестовый заказ", amount=amount)],
        )

    async def refund_payment(
        self, *, user_id: int, telegram_payment_charge_id: str
    ) -> bool:
        """Request a full Stars refund; callers must persist/reconcile the result."""
        return await self._bot.refund_star_payment(
            user_id=user_id,
            telegram_payment_charge_id=telegram_payment_charge_id,
        )
