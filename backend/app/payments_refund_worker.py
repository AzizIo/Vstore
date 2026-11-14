from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.orders.refund_worker import run_refund_worker_pass

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_stars_refund_worker_enabled:
        raise RuntimeError("TELEGRAM_STARS_REFUND_WORKER_ENABLED must be true")
    if not settings.telegram_stars_test_enabled:
        raise RuntimeError("TELEGRAM_STARS_TEST_ENABLED must be true")
    if settings.environment.lower() not in {"local", "development", "test"}:
        raise RuntimeError("The Telegram Stars refund worker cannot run outside test environments")
    if settings.telegram_stars_test_bot_token is None:
        raise RuntimeError("TELEGRAM_STARS_TEST_BOT_TOKEN is required")

    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.telegram_stars_test_bot_token.get_secret_value())
    try:
        while True:
            try:
                result = await run_refund_worker_pass(
                    async_session_factory,
                    bot,
                )
                if result.claimed:
                    logger.info(
                        "Stars refund worker: claimed=%s refunded=%s deferred=%s "
                        "manual_review=%s lease_lost=%s",
                        result.claimed,
                        result.refunded,
                        result.deferred,
                        result.manual_review,
                        result.lease_lost,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Stars refund worker pass failed; retrying next poll")
            await asyncio.sleep(get_settings().telegram_stars_refund_poll_seconds)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
