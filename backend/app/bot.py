import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher

from app.bot_handlers import router as user_router
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.notifications.service import process_due_notifications
from app.notifications.telegram import TelegramNotificationSender

logger = logging.getLogger(__name__)


def create_dispatcher() -> Dispatcher:
    """Build the dispatcher and register all user-facing bot handlers."""
    dispatcher = Dispatcher()
    dispatcher.include_router(user_router)
    return dispatcher


async def _run_notification_worker(bot: Bot) -> None:
    settings = get_settings()
    sender = TelegramNotificationSender(bot)
    while True:
        try:
            async with async_session_factory() as session:
                result = await process_due_notifications(session, sender)
            if result.claimed == 0:
                await asyncio.sleep(settings.notification_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram notification worker failed; the next poll will retry")
            await asyncio.sleep(settings.notification_poll_seconds)


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required to start the Telegram bot.")
    if not settings.telegram_mini_app_url:
        logger.warning(
            "TELEGRAM_MINI_APP_URL is not configured; order notifications will not include "
            "Mini App deep links."
        )

    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=settings.bot_token)
    dispatcher = create_dispatcher()
    notification_task = asyncio.create_task(_run_notification_worker(bot))

    try:
        await dispatcher.start_polling(bot)
    finally:
        notification_task.cancel()
        with suppress(asyncio.CancelledError):
            await notification_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
