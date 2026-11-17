import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand

from app.bot_handlers import router as user_router
from app.core.config import Settings, get_settings
from app.db.session import async_session_factory
from app.notifications.service import process_due_notifications
from app.notifications.telegram import TelegramNotificationSender

logger = logging.getLogger(__name__)

# A bounded Telegram API timeout keeps claimed notification batches within
# their database lease, even when the remote Bot API is unavailable.
TELEGRAM_API_MAX_TIMEOUT_SECONDS = 15


def telegram_api_timeout_seconds(settings: Settings) -> int:
    """Keep each Bot API request shorter than a quarter of the notification lease."""
    return max(
        1,
        min(
            TELEGRAM_API_MAX_TIMEOUT_SECONDS,
            settings.notification_claim_lease_seconds // 4,
        ),
    )


def notification_worker_batch_limit(settings: Settings) -> int:
    """Keep sequential Telegram sends comfortably inside the claim lease."""
    request_timeout = telegram_api_timeout_seconds(settings)
    lease_safe_batch_size = max(
        1,
        settings.notification_claim_lease_seconds // (2 * request_timeout),
    )
    return min(settings.notification_batch_size, lease_safe_batch_size)


BOT_COMMANDS = [
    BotCommand(command="start", description="Открыть главное меню"),
    BotCommand(command="app", description="Открыть VILTARA SHOP"),
    BotCommand(command="admin", description="Панель модерации для администраторов"),
    BotCommand(command="buy", description="Как купить NFT"),
    BotCommand(command="sell", description="Как продать NFT"),
    BotCommand(command="orders", description="Заказы и доставка"),
    BotCommand(command="safety", description="Правила безопасности"),
    BotCommand(command="paysupport", description="Помощь с платежами"),
    BotCommand(command="terms", description="Условия сервиса"),
    BotCommand(command="support", description="Связаться с поддержкой"),
    BotCommand(command="help", description="Центр помощи"),
]


def create_dispatcher() -> Dispatcher:
    """Build the dispatcher and register all user-facing bot handlers."""
    dispatcher = Dispatcher()
    dispatcher.include_router(user_router)
    return dispatcher


async def register_bot_commands(bot: Bot) -> None:
    """Publish the Russian command menu in Telegram's chat command picker."""
    await bot.set_my_commands(BOT_COMMANDS)


async def _run_notification_worker(bot: Bot) -> None:
    settings = get_settings()
    sender = TelegramNotificationSender(bot)
    while True:
        try:
            async with async_session_factory() as session:
                result = await process_due_notifications(
                    session,
                    sender,
                    limit=notification_worker_batch_limit(settings),
                )
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
            "TELEGRAM_MINI_APP_URL is not configured; /start and /app will not show "
            "a Mini App launch button."
        )
    if not settings.telegram_mini_app_direct_link:
        logger.info(
            "TELEGRAM_MINI_APP_DIRECT_LINK is not configured; order notification "
            "deep links will be omitted."
        )

    logging.basicConfig(level=logging.INFO)
    bot = Bot(
        token=settings.bot_token,
        session=AiohttpSession(timeout=telegram_api_timeout_seconds(settings)),
    )
    try:
        await register_bot_commands(bot)
    except TelegramAPIError:
        logger.exception("Не удалось обновить список команд Telegram-бота")

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
