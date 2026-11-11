from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Dispatcher
from aiogram.types import Chat, Message

from app import bot_handlers
from app.bot import create_dispatcher


def test_dispatcher_registers_message_and_callback_handlers() -> None:
    dispatcher = create_dispatcher()

    assert isinstance(dispatcher, Dispatcher)
    assert bot_handlers.router in dispatcher.sub_routers
    assert {"message", "callback_query"}.issubset(
        set(dispatcher.resolve_used_update_types())
    )


@pytest.mark.asyncio
async def test_start_handler_sends_welcome_and_configured_mini_app_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url="https://example.com/miniapp"),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_start(message)  # type: ignore[arg-type]

    message.answer.assert_awaited_once()
    args = message.answer.await_args
    assert "Добро пожаловать в VILTARA SHOP" in args.args[0]
    keyboard = args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].text == "Открыть VILTARA SHOP"
    assert keyboard.inline_keyboard[0][0].url == "https://example.com/miniapp"
    assert keyboard.inline_keyboard[1][0].callback_data == "bot:help"


@pytest.mark.asyncio
async def test_start_handler_works_without_optional_mini_app_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url=None),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_start(message)  # type: ignore[arg-type]

    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].callback_data == "bot:help"


@pytest.mark.asyncio
async def test_help_callback_is_acknowledged_and_updates_the_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url=None),
    )
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=123, type="private"),
        text="Old message",
    )
    edit_text = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit_text)
    callback = SimpleNamespace(answer=AsyncMock(), message=message)

    await bot_handlers.handle_help_callback(callback)  # type: ignore[arg-type]

    callback.answer.assert_awaited_once()
    edit_text.assert_awaited_once()
    assert "резервирование, а не оплата" in edit_text.await_args.args[0]
