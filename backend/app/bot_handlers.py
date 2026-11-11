from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.core.config import get_settings

router = Router(name="viltara-shop-user")


def _menu_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    mini_app_url = get_settings().telegram_mini_app_url
    if mini_app_url:
        rows.append(
            [InlineKeyboardButton(text="Открыть VILTARA SHOP", url=mini_app_url)]
        )
    rows.append(
        [InlineKeyboardButton(text="Как пользоваться", callback_data="bot:help")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="В главное меню", callback_data="bot:menu")]
        ]
    )


START_MESSAGE = (
    "Добро пожаловать в VILTARA SHOP!\n\n"
    "Здесь можно просматривать каталог TON NFT и управлять объявлениями и заказами "
    "через Mini App. Выберите действие ниже."
)
HELP_MESSAGE = (
    "VILTARA SHOP — маркетплейс объявлений о TON NFT.\n\n"
    "• Каталог: просматривайте объявления и их цены.\n"
    "• Объявления: подключите и подтвердите кошелёк, затем создайте объявление "
    "из NFT, которым владеете.\n"
    "• Заказы: просматривайте свои резервации и управляйте доступными действиями.\n\n"
    "Важно: создание заказа — это резервирование, а не оплата. Встроенная оплата "
    "и автоматическая передача NFT пока не реализованы."
)


async def _send_menu(message: Message, text: str = START_MESSAGE) -> None:
    await message.answer(text, reply_markup=_menu_keyboard())


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Show the marketplace entry point when a user starts the bot."""
    await _send_menu(message)


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """Explain the implemented marketplace features and current limitations."""
    await message.answer(HELP_MESSAGE, reply_markup=_menu_keyboard())


@router.message(Command("app"))
async def handle_app(message: Message) -> None:
    """Open the configured Mini App or explain why the link is unavailable."""
    mini_app_url = get_settings().telegram_mini_app_url
    if not mini_app_url:
        await message.answer(
            "Mini App пока не настроен. Администратору нужно задать "
            "TELEGRAM_MINI_APP_URL. Попробуйте команду /help."
        )
        return

    await message.answer(
        "Откройте VILTARA SHOP по кнопке ниже.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Открыть VILTARA SHOP", url=mini_app_url)]
            ]
        ),
    )


@router.callback_query(F.data == "bot:help")
async def handle_help_callback(callback: CallbackQuery) -> None:
    """Answer callback queries and show help without leaving the chat."""
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            HELP_MESSAGE,
            reply_markup=_back_keyboard(),
        )


@router.callback_query(F.data == "bot:menu")
async def handle_menu_callback(callback: CallbackQuery) -> None:
    """Return to the bot's main menu from the inline help screen."""
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            START_MESSAGE,
            reply_markup=_menu_keyboard(),
        )


@router.message(F.text)
async def handle_text_fallback(message: Message) -> None:
    """Guide ordinary text and unsupported commands to supported bot actions."""
    await _send_menu(
        message,
        "Я пока не обрабатываю произвольные сообщения. Используйте /start, /app "
        "или /help — либо откройте Mini App кнопкой ниже.",
    )
