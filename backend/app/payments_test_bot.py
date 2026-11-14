from __future__ import annotations

import asyncio
import hmac
import logging
from urllib.parse import urlsplit

from aiogram import Bot, Dispatcher

from app.core.config import get_settings
from app.payments_bot_handlers import router as payments_test_router

_ALLOWED_LOCAL_TEST_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres"}


def create_test_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(payments_test_router)
    return dispatcher


def _validate_test_bot_runtime() -> str:
    """Fail closed unless both the bot token and database are isolated test resources."""

    settings = get_settings()
    if not settings.telegram_stars_test_enabled:
        raise RuntimeError("TELEGRAM_STARS_TEST_ENABLED must be true to start this bot")
    if settings.environment.lower() != "test":
        raise RuntimeError("The Telegram Stars test bot may run only with environment=test")
    if settings.telegram_stars_test_bot_token is None:
        raise RuntimeError("TELEGRAM_STARS_TEST_BOT_TOKEN is required")

    test_token = settings.telegram_stars_test_bot_token.get_secret_value()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN must be configured so the test token can be checked")
    if hmac.compare_digest(test_token, settings.bot_token):
        raise RuntimeError("The Stars test bot token must differ from the primary bot token")

    try:
        parsed = urlsplit(settings.database_url)
        # Accessing port rejects malformed URLs before the application opens a DB connection.
        _ = parsed.port
    except ValueError as exc:
        raise RuntimeError("The Stars test bot database URL is invalid") from exc

    if parsed.scheme != "postgresql+asyncpg":
        raise RuntimeError("The Stars test bot requires a dedicated PostgreSQL test database")
    database_name = parsed.path.lstrip("/").split("?", maxsplit=1)[0]
    if not (
        database_name.startswith("test_") or database_name.endswith("_test")
    ):
        raise RuntimeError(
            "The Stars test bot database name must start with test_ or end with _test"
        )
    if parsed.hostname not in _ALLOWED_LOCAL_TEST_DB_HOSTS:
        raise RuntimeError("The Stars test bot may connect only to a local test PostgreSQL host")

    return test_token


async def main() -> None:
    """Run only the isolated test bot; never the production bot or database."""

    token = _validate_test_bot_runtime()
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=token)
    dispatcher = create_test_dispatcher()
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
