from urllib.parse import urlsplit

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.core.config import get_settings

router = Router(name="viltara-shop-user")


def _mini_app_button(url: str | None) -> InlineKeyboardButton | None:
    """Create a primary in-Telegram Mini App button for a public HTTPS URL."""
    if not url:
        return None

    candidate = url.strip()
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        # Accessing .port validates malformed and out-of-range port values.
        _ = parsed.port
    except ValueError:
        return None

    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not hostname
        or parsed.username
        or parsed.password
        or any(character.isspace() for character in candidate)
    ):
        return None

    return InlineKeyboardButton(
        text="Открыть VILTARA SHOP",
        web_app=WebAppInfo(url=candidate),
        style="primary",
    )


def _menu_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    mini_app_button = _mini_app_button(get_settings().telegram_mini_app_url)
    if mini_app_button is not None:
        rows.append([mini_app_button])
    rows.append(
        [
            InlineKeyboardButton(
                text="ℹ️ Как пользоваться",
                callback_data="bot:help",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="← В главное меню",
                    callback_data="bot:menu",
                    style="primary",
                )
            ]
        ]
    )


START_MESSAGE = (
    "<b>VILTARA SHOP</b>\n"
    "<i>Маркетплейс TON NFT</i>\n\n"
    "Просматривайте каталог, размещайте объявления и управляйте заказами — "
    "всё в одном приложении.\n\n"
    "Выберите действие:"
)
HELP_MESSAGE = (
    "<b>Как пользоваться VILTARA SHOP</b>\n\n"
    "💎 <b>Каталог</b>\n"
    "Просматривайте объявления и сравнивайте цены.\n\n"
    "🛍 <b>Объявления</b>\n"
    "Подключите и подтвердите TON-кошелёк в приложении, затем разместите NFT, "
    "которым владеете.\n\n"
    "📦 <b>Заказы</b>\n"
    "Следите за статусом заказа и доступными действиями.\n\n"
    "⚠️ <b>Важно об оплате</b>\n"
    "Создание заказа резервирует объявление, но не означает оплату. Продавец "
    "подтверждает перевод NFT в своём TON-кошельке, а backend отдельно "
    "проверяет передачу по данным сети. Платёж, escrow и гарантия сделки "
    "не реализованы.
)


async def _send_menu(message: Message, text: str = START_MESSAGE) -> None:
    await message.answer(
        text,
        reply_markup=_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Show the marketplace entry point when a user starts the bot."""
    await _send_menu(message)


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """Explain implemented marketplace features and current limitations."""
    await message.answer(
        HELP_MESSAGE,
        reply_markup=_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("app"))
async def handle_app(message: Message) -> None:
    """Open the configured Mini App or explain why the link is unavailable."""
    mini_app_button = _mini_app_button(get_settings().telegram_mini_app_url)
    if mini_app_button is None:
        await message.answer(
            "Приложение пока недоступно: ссылка не настроена или указана неверно. "
            "Администратору нужно задать <code>TELEGRAM_MINI_APP_URL</code> — "
            "публичный HTTPS-адрес приложения. Подробности: /help.",
            parse_mode="HTML",
        )
        return

    await message.answer(
        "Откройте VILTARA SHOP по кнопке ниже.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[mini_app_button]]
        ),
    )


@router.callback_query(F.data == "bot:help")
async def handle_help_callback(callback: CallbackQuery) -> None:
    """Acknowledge the callback and edit the existing message with help."""
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                HELP_MESSAGE,
                reply_markup=_back_keyboard(),
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            # Repeated taps can try to apply the same screen twice.
            if "message is not modified" not in str(exc).lower():
                raise


@router.callback_query(F.data == "bot:menu")
async def handle_menu_callback(callback: CallbackQuery) -> None:
    """Return to the main menu by editing the existing help message."""
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                START_MESSAGE,
                reply_markup=_menu_keyboard(),
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise


@router.message(F.text)
async def handle_text_fallback(message: Message) -> None:
    """Guide unsupported text and commands toward the available bot actions."""
    await _send_menu(
        message,
        "Не удалось распознать сообщение. Бот помогает открыть приложение "
        "и показывает инструкции.\n\n"
        "Выберите действие ниже или используйте /start, /app либо /help.",
    )
