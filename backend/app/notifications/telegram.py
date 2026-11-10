from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)

from app.notifications.service import (
    PermanentNotificationError,
    TransientNotificationError,
)


class TelegramNotificationSender:
    """Translate aiogram API failures into retryable/permanent delivery outcomes."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_message(
        self, *, chat_id: int, text: str, disable_web_page_preview: bool = True
    ) -> object:
        try:
            return await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                disable_web_page_preview=disable_web_page_preview,
            )
        except TelegramRetryAfter as exc:
            raise TransientNotificationError(
                str(exc), retry_after_seconds=exc.retry_after
            ) from exc
        except (
            TelegramForbiddenError,
            TelegramBadRequest,
            TelegramNotFound,
            TelegramUnauthorizedError,
        ) as exc:
            raise PermanentNotificationError(str(exc)) from exc
        except (TelegramNetworkError, TelegramServerError) as exc:
            raise TransientNotificationError(str(exc)) from exc
