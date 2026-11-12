from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update

from app import bot_handlers
from app.bot import create_dispatcher


@pytest.fixture(scope="module")
def dispatcher() -> Dispatcher:
    return create_dispatcher()


def test_dispatcher_registers_message_and_callback_handlers(
    dispatcher: Dispatcher,
) -> None:

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
        lambda: SimpleNamespace(telegram_mini_app_url="https://dealtime-com-badly-twice.trycloudflare.com"),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_start(message)  # type: ignore[arg-type]

    message.answer.assert_awaited_once()
    args = message.answer.await_args
    assert "Добро пожаловать в VILTARA SHOP" in args.args[0]
    keyboard = args.kwargs["reply_markup"]
    button = keyboard.inline_keyboard[0][0]
    assert button.text == "Открыть VILTARA SHOP"
    assert button.url is None
    assert button.web_app is not None
    assert button.web_app.url == "https://dealtime-com-badly-twice.trycloudflare.com"
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
async def test_app_command_uses_web_app_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mini_app_url = "https://dealtime-com-badly-twice.trycloudflare.com"
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url=mini_app_url),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_app(message)  # type: ignore[arg-type]

    message.answer.assert_awaited_once()
    keyboard = message.answer.await_args.kwargs["reply_markup"]
    button = keyboard.inline_keyboard[0][0]
    assert button.url is None
    assert button.web_app is not None
    assert button.web_app.url == mini_app_url


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
    help_text = edit_text.await_args.args[0]
    assert "резервирование, а не оплата" in help_text
    assert "Продавец подтверждает перевод NFT в своём TON-кошельке" in help_text
    assert "backend отдельно проверяет передачу по данным сети" in help_text
    assert "Платёж, escrow и гарантия сделки не реализованы" in help_text
    keyboard = edit_text.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data == "bot:menu"


@pytest.mark.asyncio
async def test_help_command_explains_supported_features_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url="https://dealtime-com-badly-twice.trycloudflare.com"),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_help(message)  # type: ignore[arg-type]

    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "маркетплейс объявлений о TON NFT" in text
    assert "Каталог" in text
    assert "Объявления" in text
    assert "Заказы" in text
    assert "резервирование, а не оплата" in text
    assert "Продавец подтверждает перевод NFT в своём TON-кошельке" in text
    assert "backend отдельно проверяет передачу по данным сети" in text
    assert "Платёж, escrow и гарантия сделки не реализованы" in text
    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].url is None
    assert keyboard.inline_keyboard[0][0].web_app is not None
    assert keyboard.inline_keyboard[0][0].web_app.url == "https://dealtime-com-badly-twice.trycloudflare.com"


@pytest.mark.asyncio
async def test_app_command_explains_missing_mini_app_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url=None),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_app(message)  # type: ignore[arg-type]

    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "Mini App пока не настроен" in text
    assert "TELEGRAM_MINI_APP_URL" in text
    assert "/help" in text
    assert "reply_markup" not in message.answer.await_args.kwargs


@pytest.mark.asyncio
async def test_menu_callback_acknowledges_query_and_restores_main_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url="https://dealtime-com-badly-twice.trycloudflare.com"),
    )
    message = Message(
        message_id=2,
        date=datetime.now(UTC),
        chat=Chat(id=123, type="private"),
        text="Help screen",
    )
    edit_text = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit_text)
    callback = SimpleNamespace(answer=AsyncMock(), message=message)

    await bot_handlers.handle_menu_callback(callback)  # type: ignore[arg-type]

    callback.answer.assert_awaited_once()
    edit_text.assert_awaited_once()
    assert edit_text.await_args.args[0] == bot_handlers.START_MESSAGE
    keyboard = edit_text.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].url is None
    assert keyboard.inline_keyboard[0][0].web_app is not None
    assert keyboard.inline_keyboard[0][0].web_app.url == "https://dealtime-com-badly-twice.trycloudflare.com"
    assert keyboard.inline_keyboard[1][0].callback_data == "bot:help"


@pytest.mark.asyncio
async def test_plain_text_fallback_guides_user_to_supported_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url=None),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_text_fallback(message)  # type: ignore[arg-type]

    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "не обрабатываю произвольные сообщения" in text
    assert "/start" in text
    assert "/app" in text
    assert "/help" in text
    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data == "bot:help"


@pytest.mark.asyncio
async def test_unknown_command_is_routed_to_fallback_without_exception(
    monkeypatch: pytest.MonkeyPatch,
    dispatcher: Dispatcher,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url=None),
    )
    answer = AsyncMock()
    monkeypatch.setattr(Message, "answer", answer)
    bot = Bot(token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    message = Message(
        message_id=3,
        date=datetime.now(UTC),
        chat=Chat(id=123, type="private"),
        text="/unsupported",
    )

    try:
        await dispatcher.feed_update(
            bot,
            Update(update_id=10, message=message),
        )
    finally:
        await bot.session.close()

    answer.assert_awaited_once()
    assert "не обрабатываю произвольные сообщения" in answer.await_args.args[0]


def test_dispatcher_registers_each_public_handler(
    dispatcher: Dispatcher,
) -> None:
    message_handlers = {
        handler.callback.__name__ for handler in bot_handlers.router.message.handlers
    }
    callback_handlers = {
        handler.callback.__name__ for handler in bot_handlers.router.callback_query.handlers
    }

    assert {
        "handle_start",
        "handle_help",
        "handle_app",
        "handle_text_fallback",
    }.issubset(message_handlers)
    assert {"handle_help_callback", "handle_menu_callback"}.issubset(
        callback_handlers
    )
    assert bot_handlers.router in dispatcher.sub_routers
    assert {"message", "callback_query"}.issubset(
        set(dispatcher.resolve_used_update_types())
    )



@pytest.mark.asyncio
async def test_start_menu_accepts_public_https_mini_app_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_mini_app_url="https://shop.example.com/miniapp"
        ),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_start(message)  # type: ignore[arg-type]

    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert len(keyboard.inline_keyboard) == 2
    button = keyboard.inline_keyboard[0][0]
    assert button.web_app is not None
    assert button.web_app.url == "https://shop.example.com/miniapp"
    assert keyboard.inline_keyboard[1][0].callback_data == "bot:help"


@pytest.mark.asyncio
async def test_app_command_explains_invalid_mini_app_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_mini_app_url="http://shop.example.com/miniapp"
        ),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_app(message)  # type: ignore[arg-type]

    response_text = message.answer.await_args.args[0]
    assert "ссылка указана неверно" in response_text
    assert "публичный HTTPS-адрес" in response_text
    assert "reply_markup" not in message.answer.await_args.kwargs
