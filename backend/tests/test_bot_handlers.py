from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Chat, Message, Update

from app import bot_handlers
from app.bot import BOT_COMMANDS, create_dispatcher, register_bot_commands

APP_URL = "https://shop.example.com/miniapp"


@pytest.fixture(scope="module")
def dispatcher() -> Dispatcher:
    return create_dispatcher()


def _settings(url: str | None = APP_URL) -> SimpleNamespace:
    return SimpleNamespace(
        telegram_mini_app_url=url,
        telegram_support_username=None,
        telegram_terms_url=None,
    )


def test_dispatcher_registers_all_user_facing_handlers(
    dispatcher: Dispatcher,
) -> None:
    message_handlers = {
        handler.callback.__name__ for handler in bot_handlers.router.message.handlers
    }
    callback_handlers = {
        handler.callback.__name__
        for handler in bot_handlers.router.callback_query.handlers
    }

    assert {
        "handle_start",
        "handle_help",
        "handle_app",
        "handle_buy",
        "handle_sell",
        "handle_orders",
        "handle_safety",
        "handle_terms",
        "handle_support",
        "handle_paysupport",
        "handle_text_fallback",
    }.issubset(message_handlers)
    assert {
        "handle_help_callback",
        "handle_menu_callback",
        "handle_buy_callback",
        "handle_sell_callback",
        "handle_orders_callback",
        "handle_safety_callback",
        "handle_about_callback",
        "handle_unknown_callback",
    }.issubset(callback_handlers)
    assert bot_handlers.router in dispatcher.sub_routers
    assert {"message", "callback_query"}.issubset(
        set(dispatcher.resolve_used_update_types())
    )


@pytest.mark.asyncio
async def test_start_shows_premium_welcome_and_full_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings())
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_start(message)  # type: ignore[arg-type]

    message.answer.assert_awaited_once()
    args = message.answer.await_args
    assert "✨ <b>VILTARA SHOP</b>" in args.args[0]
    assert "TON NFT marketplace" in args.args[0]
    assert args.kwargs["parse_mode"] == "HTML"
    assert args.kwargs["disable_web_page_preview"] is True
    rows = args.kwargs["reply_markup"].inline_keyboard
    assert rows[0][0].text == "💎 Открыть VILTARA SHOP"
    assert rows[0][0].web_app.url == APP_URL
    assert rows[0][0].style == "primary"
    callbacks = {
        button.callback_data
        for row in rows
        for button in row
        if button.callback_data
    }
    assert callbacks == {
        "bot:buy",
        "bot:sell",
        "bot:orders",
        "bot:safety",
        "bot:about",
    }


@pytest.mark.asyncio
async def test_start_menu_remains_useful_without_mini_app_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings(None))
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_start(message)  # type: ignore[arg-type]

    rows = message.answer.await_args.kwargs["reply_markup"].inline_keyboard
    assert len(rows) == 3
    assert rows[0][0].callback_data == "bot:buy"
    assert rows[-1][0].callback_data == "bot:about"


@pytest.mark.asyncio
async def test_app_command_uses_primary_web_app_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings())
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_app(message)  # type: ignore[arg-type]

    message.answer.assert_awaited_once()
    assert "Ваш VILTARA SHOP" in message.answer.await_args.args[0]
    button = message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.web_app.url == APP_URL
    assert button.style == "primary"


@pytest.mark.asyncio
async def test_app_command_explains_missing_or_invalid_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: _settings("http://shop.example.com/miniapp"),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_app(message)  # type: ignore[arg-type]

    response = message.answer.await_args
    assert "Приложение пока недоступно" in response.args[0]
    assert "TELEGRAM_MINI_APP_URL" in response.args[0]
    assert response.kwargs.get("reply_markup") is None


@pytest.mark.parametrize(
    ("screen", "expected"),
    [
        ("buy", "Покупка NFT"),
        ("sell", "Продажа NFT"),
        ("orders", "Заказы и доставка"),
        ("safety", "Безопасность прежде всего"),
        ("about", "О VILTARA SHOP"),
    ],
)
@pytest.mark.asyncio
async def test_guided_screens_have_clear_copy_and_return_navigation(
    monkeypatch: pytest.MonkeyPatch,
    screen: str,
    expected: str,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings())
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers._send_screen(message, screen)  # type: ignore[arg-type]

    response = message.answer.await_args
    assert expected in response.args[0]
    assert response.kwargs["parse_mode"] == "HTML"
    rows = response.kwargs["reply_markup"].inline_keyboard
    assert rows[0][0].web_app.url == APP_URL
    assert rows[-1][0].callback_data == "bot:menu"


@pytest.mark.asyncio
async def test_buyer_and_seller_commands_show_their_guides() -> None:
    for handler, expected in (
        (bot_handlers.handle_buy, "Покупка NFT"),
        (bot_handlers.handle_sell, "Продажа NFT"),
        (bot_handlers.handle_orders, "Заказы и доставка"),
        (bot_handlers.handle_safety, "Безопасность прежде всего"),
    ):
        message = SimpleNamespace(answer=AsyncMock())
        await handler(message)  # type: ignore[arg-type]
        assert expected in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_help_screen_explains_supported_assets_and_payment_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings())
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_help(message)  # type: ignore[arg-type]

    response = message.answer.await_args
    assert "Центр помощи VILTARA SHOP" in response.args[0]
    assert "TEP-62" in response.args[0]
    assert "Telegram Gifts пока не поддерживаются" in response.args[0]
    assert "резервирование заказа — не оплата" in response.args[0]
    callbacks = {
        button.callback_data
        for row in response.kwargs["reply_markup"].inline_keyboard
        for button in row
        if button.callback_data
    }
    assert "bot:buy" in callbacks
    assert "bot:safety" in callbacks


@pytest.mark.asyncio
async def test_help_callback_is_acknowledged_and_returns_to_help_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings())
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
    assert "Центр помощи VILTARA SHOP" in edit_text.await_args.args[0]
    assert edit_text.await_args.kwargs["parse_mode"] == "HTML"
    assert edit_text.await_args.kwargs["reply_markup"].inline_keyboard[-1][0].callback_data in {
        "bot:buy",
        "bot:about",
    }


@pytest.mark.asyncio
async def test_guided_callback_edits_message_and_acknowledges_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings())
    message = Message(
        message_id=2,
        date=datetime.now(UTC),
        chat=Chat(id=123, type="private"),
        text="Main menu",
    )
    edit_text = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit_text)
    callback = SimpleNamespace(answer=AsyncMock(), message=message)

    await bot_handlers.handle_buy_callback(callback)  # type: ignore[arg-type]

    callback.answer.assert_awaited_once()
    assert "Покупка NFT" in edit_text.await_args.args[0]
    keyboard = edit_text.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[-1][0].callback_data == "bot:menu"


@pytest.mark.asyncio
async def test_menu_callback_restores_premium_start_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings())
    message = Message(
        message_id=3,
        date=datetime.now(UTC),
        chat=Chat(id=123, type="private"),
        text="Help screen",
    )
    edit_text = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit_text)
    callback = SimpleNamespace(answer=AsyncMock(), message=message)

    await bot_handlers.handle_menu_callback(callback)  # type: ignore[arg-type]

    callback.answer.assert_awaited_once()
    assert edit_text.await_args.args[0] == bot_handlers.START_MESSAGE
    assert "✨ <b>VILTARA SHOP</b>" in edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_only_duplicate_message_edit_errors_are_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = Message(
        message_id=4,
        date=datetime.now(UTC),
        chat=Chat(id=123, type="private"),
        text="Existing screen",
    )
    callback = SimpleNamespace(answer=AsyncMock(), message=message)
    duplicate = TelegramBadRequest(
        method=SimpleNamespace(),
        message="Bad Request: message is not modified",
    )
    edit_text = AsyncMock(side_effect=duplicate)
    monkeypatch.setattr(Message, "edit_text", edit_text)
    await bot_handlers.handle_buy_callback(callback)  # type: ignore[arg-type]

    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_callback_is_acknowledged_with_recovery_hint() -> None:
    callback = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_unknown_callback(callback)  # type: ignore[arg-type]

    callback.answer.assert_awaited_once_with(
        "Эта кнопка устарела. Используйте /start, чтобы открыть актуальное меню.",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_plain_text_fallback_points_to_new_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings(None))
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_text_fallback(message)  # type: ignore[arg-type]

    response = message.answer.await_args
    assert "не умею отвечать на свободные сообщения" in response.args[0]
    for command in (
        "/start", "/app", "/buy", "/sell", "/orders", "/safety",
        "/paysupport", "/terms", "/support", "/help",
    ):
        assert command in response.args[0]


@pytest.mark.asyncio
async def test_unknown_command_is_routed_to_fallback_without_exception(
    monkeypatch: pytest.MonkeyPatch,
    dispatcher: Dispatcher,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings(None))
    answer = AsyncMock()
    monkeypatch.setattr(Message, "answer", answer)
    telegram_bot = Bot(token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    message = Message(
        message_id=5,
        date=datetime.now(UTC),
        chat=Chat(id=123, type="private"),
        text="/unsupported",
    )

    try:
        await dispatcher.feed_update(
            telegram_bot,
            Update(update_id=11, message=message),
        )
    finally:
        await telegram_bot.session.close()

    answer.assert_awaited_once()
    assert "не умею отвечать" in answer.await_args.args[0]


@pytest.mark.asyncio
async def test_register_bot_commands_publishes_russian_command_menu() -> None:
    telegram_bot = SimpleNamespace(set_my_commands=AsyncMock())

    await register_bot_commands(telegram_bot)  # type: ignore[arg-type]

    telegram_bot.set_my_commands.assert_awaited_once_with(BOT_COMMANDS)
    assert [(command.command, command.description) for command in BOT_COMMANDS] == [
        ("start", "Открыть главное меню"),
        ("app", "Открыть VILTARA SHOP"),
        ("buy", "Как купить NFT"),
        ("sell", "Как продать NFT"),
        ("orders", "Заказы и доставка"),
        ("safety", "Правила безопасности"),
        ("paysupport", "Помощь с платежами"),
        ("terms", "Условия сервиса"),
        ("support", "Связаться с поддержкой"),
        ("help", "Центр помощи"),
    ]


@pytest.mark.parametrize(
    "url",
    (
        "https://@/miniapp",
        "https://example.com:not-a-port/miniapp",
        "https://example .com/miniapp",
        "https://user:password@example.com/miniapp",
        "http://shop.example.com/miniapp",
    ),
)
def test_mini_app_button_rejects_malformed_or_unsafe_urls(url: str) -> None:
    assert bot_handlers._mini_app_button(url) is None


@pytest.mark.asyncio
async def test_start_menu_accepts_valid_public_https_mini_app_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bot_handlers,
        "get_settings",
        lambda: _settings("https://shop.example.com/miniapp"),
    )
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_start(message)  # type: ignore[arg-type]

    button = message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.web_app.url == "https://shop.example.com/miniapp"
    assert button.style == "primary"


@pytest.mark.asyncio
async def test_menu_callback_ignores_only_message_not_modified_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = Message(
        message_id=6,
        date=datetime.now(UTC),
        chat=Chat(id=123, type="private"),
        text="Existing menu",
    )
    edit_error = TelegramBadRequest(
        method=SimpleNamespace(),
        message="Bad Request: message can't be edited",
    )
    edit_text = AsyncMock(side_effect=edit_error)
    monkeypatch.setattr(Message, "edit_text", edit_text)
    callback = SimpleNamespace(answer=AsyncMock(), message=message)

    with pytest.raises(TelegramBadRequest, match="can't be edited"):
        await bot_handlers.handle_menu_callback(callback)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_about_callback_opens_marketplace_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: _settings(None))
    message = Message(
        message_id=7,
        date=datetime.now(UTC),
        chat=Chat(id=123, type="private"),
        text="Main menu",
    )
    edit_text = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit_text)
    callback = SimpleNamespace(answer=AsyncMock(), message=message)

    await bot_handlers.handle_about_callback(callback)  # type: ignore[arg-type]

    callback.answer.assert_awaited_once()
    assert "P2P-маркетплейс" in edit_text.await_args.args[0]
    assert "Telegram Gifts" in edit_text.await_args.args[0]
    rows = edit_text.await_args.kwargs["reply_markup"].inline_keyboard
    assert rows[-1][0].callback_data == "bot:menu"

@pytest.mark.asyncio
async def test_terms_command_is_explicit_when_full_terms_are_not_configured() -> None:
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_terms(message)  # type: ignore[arg-type]

    response = message.answer.await_args
    assert "Полные условия сервиса пока не опубликованы" in response.args[0]
    assert "checkout" in response.args[0]
    assert "reply_markup" not in response.kwargs


@pytest.mark.asyncio
async def test_terms_command_links_only_to_valid_https_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    settings.telegram_terms_url = "https://shop.example.com/terms"
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: settings)
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_terms(message)  # type: ignore[arg-type]

    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].url == "https://shop.example.com/terms"


@pytest.mark.parametrize(
    "url",
    ("http://shop.example.com/terms", "https://user:pass@example.com/terms", "javascript:alert(1)"),
)
def test_public_terms_url_rejects_unsafe_destinations(url: str) -> None:
    assert bot_handlers._terms_keyboard(url) is None


@pytest.mark.asyncio
async def test_support_command_is_transparent_when_contact_is_not_configured() -> None:
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_support(message)  # type: ignore[arg-type]

    response = message.answer.await_args
    assert "Контакт поддержки пока не опубликован" in response.args[0]
    assert "Платёжные операции отключены" in response.args[0]
    assert "reply_markup" not in response.kwargs


@pytest.mark.asyncio
async def test_support_command_links_to_configured_telegram_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    settings.telegram_support_username = "@ViltaraHelpBot"
    monkeypatch.setattr(bot_handlers, "get_settings", lambda: settings)
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_support(message)  # type: ignore[arg-type]

    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].url == "https://t.me/ViltaraHelpBot"
    assert "Не отправляйте seed-фразы" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_paysupport_never_claims_that_checkout_or_refunds_are_enabled() -> None:
    message = SimpleNamespace(answer=AsyncMock())

    await bot_handlers.handle_paysupport(message)  # type: ignore[arg-type]

    response = message.answer.await_args
    assert "checkout сейчас отключён" in response.args[0]
    assert "не оплачивайте заказ" in response.args[0]
    assert "charge ID" in response.args[0]
    assert "Контакт поддержки ещё не настроен" in response.args[0]


def test_support_username_validation_rejects_urls_and_invalid_usernames() -> None:
    for value in ("https://t.me/attacker", "@too-short", "name with spaces", "a" * 33):
        assert bot_handlers._support_keyboard(value) is None
