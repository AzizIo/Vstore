from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.methods import SendMessage
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
from app.notifications.telegram import TelegramNotificationSender


CHAT_ID = 123456789
MESSAGE_TEXT = "Order reservation created"


def _telegram_method() -> SendMessage:
    return SendMessage(chat_id=CHAT_ID, text=MESSAGE_TEXT)


@pytest.mark.asyncio
async def test_sender_returns_successful_telegram_response_and_forwards_parameters() -> None:
    response = object()
    bot = SimpleNamespace(send_message=AsyncMock(return_value=response))
    sender = TelegramNotificationSender(bot)  # type: ignore[arg-type]

    result = await sender.send_message(
        chat_id=CHAT_ID,
        text=MESSAGE_TEXT,
        disable_web_page_preview=False,
    )

    assert result is response
    bot.send_message.assert_awaited_once_with(
        chat_id=CHAT_ID,
        text=MESSAGE_TEXT,
        disable_web_page_preview=False,
    )


@pytest.mark.asyncio
async def test_retry_after_becomes_transient_error_with_retry_delay() -> None:
    method = _telegram_method()
    error = TelegramRetryAfter(
        method=method,
        message="Too many requests",
        retry_after=37,
    )
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=error))
    sender = TelegramNotificationSender(bot)  # type: ignore[arg-type]

    with pytest.raises(TransientNotificationError, match="Too many requests") as raised:
        await sender.send_message(chat_id=CHAT_ID, text=MESSAGE_TEXT)

    assert raised.value.retry_after_seconds == 37
    bot.send_message.assert_awaited_once_with(
        chat_id=CHAT_ID,
        text=MESSAGE_TEXT,
        disable_web_page_preview=True,
    )


@pytest.mark.parametrize(
    ("telegram_error", "expected_error"),
    [
        (TelegramNetworkError, TransientNotificationError),
        (TelegramServerError, TransientNotificationError),
        (TelegramForbiddenError, PermanentNotificationError),
        (TelegramBadRequest, PermanentNotificationError),
        (TelegramNotFound, PermanentNotificationError),
        (TelegramUnauthorizedError, PermanentNotificationError),
    ],
)
@pytest.mark.asyncio
async def test_sender_classifies_telegram_errors_and_preserves_context(
    telegram_error: type[Exception],
    expected_error: type[Exception],
) -> None:
    error = telegram_error(method=_telegram_method(), message="Telegram test failure")
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=error))
    sender = TelegramNotificationSender(bot)  # type: ignore[arg-type]

    with pytest.raises(expected_error, match="Telegram test failure") as raised:
        await sender.send_message(chat_id=CHAT_ID, text=MESSAGE_TEXT)

    assert raised.value.__cause__ is error
    bot.send_message.assert_awaited_once_with(
        chat_id=CHAT_ID,
        text=MESSAGE_TEXT,
        disable_web_page_preview=True,
    )
