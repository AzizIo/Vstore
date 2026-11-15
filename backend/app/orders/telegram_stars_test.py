from __future__ import annotations

from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import LabeledPrice

from app.core.config import get_settings
from app.db.payments import PaymentIntent
from app.orders.payment_service import _assert_test_stars_enabled


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



    async def create_invoice_link(self, *, intent: PaymentIntent) -> str:
        """Create a hosted invoice link using the isolated Telegram Test Bot API."""

        amount = int(intent.amount)
        if intent.amount != amount or amount <= 0:
            raise ValueError("Telegram Stars invoice amount must be a positive integer")
        invoice_url = await self._bot.create_invoice_link(
            title="VILTARA SHOP — тестовый платёж",
            description="Тестовый сценарий оплаты. Реальные средства не списываются.",
            payload=intent.invoice_payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Тестовый заказ", amount=amount)],
        )
        parsed = urlsplit(invoice_url)
        if parsed.scheme != "https" or parsed.hostname not in {"t.me", "www.t.me"}:
            raise RuntimeError("Telegram returned an unexpected invoice-link host")
        return invoice_url


def create_isolated_test_bot() -> Bot:
    """Create a Bot API client only after the service-level test isolation guard passes."""

    _assert_test_stars_enabled()
    settings = get_settings()
    if settings.telegram_stars_test_bot_token is None:
        raise RuntimeError("A dedicated Telegram Stars test bot token is required")
    session = AiohttpSession(
        api=TelegramAPIServer(
            base="https://api.telegram.org/bot{token}/test/{method}",
            file="https://api.telegram.org/file/bot{token}/test/{path}",
        )
    )
    return Bot(
        token=settings.telegram_stars_test_bot_token.get_secret_value(),
        session=session,
    )
