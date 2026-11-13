from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher

from app.core.config import get_settings
from app.payments_bot_handlers import router as payments_test_router


def create_test_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(payments_test_router)
    return dispatcher


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_stars_test_enabled:
        raise RuntimeError("TELEGRAM_STARS_TEST_ENABLED must be true to start this bot")
    if settings.environment.lower() not in {"local", "development", "test"}:
        raise RuntimeError("The Telegram Stars test bot cannot run outside test environments")
    if settings.telegram_stars_test_bot_token is None:
        raise RuntimeError("TELEGRAM_STARS_TEST_BOT_TOKEN is required")

    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.telegram_stars_test_bot_token.get_secret_value())
    dispatcher = create_test_dispatcher()
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
