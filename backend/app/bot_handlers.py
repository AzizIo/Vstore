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
        text="💎 Открыть VILTARA SHOP",
        web_app=WebAppInfo(url=candidate),
        style="primary",
    )


def _menu_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    mini_app_button = _mini_app_button(get_settings().telegram_mini_app_url)
    if mini_app_button is not None:
        rows.append([mini_app_button])
    rows.extend(
        [
            [
                InlineKeyboardButton(text="🛍 Как купить", callback_data="bot:buy"),
                InlineKeyboardButton(text="🏷 Как продавать", callback_data="bot:sell"),
            ],
            [
                InlineKeyboardButton(
                    text="📦 Заказы и доставка",
                    callback_data="bot:orders",
                ),
                InlineKeyboardButton(text="🛡 Безопасность", callback_data="bot:safety"),
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ О маркетплейсе",
                    callback_data="bot:about",
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    mini_app_button = _mini_app_button(get_settings().telegram_mini_app_url)
    if mini_app_button is not None:
        rows.append([mini_app_button])
    rows.append(
        [
            InlineKeyboardButton(
                text="← В главное меню",
                callback_data="bot:menu",
                style="primary",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


START_MESSAGE = (
    "✨ <b>VILTARA SHOP</b>\n"
    "<i>TON NFT marketplace · Просто. Прозрачно. Безопасно.</i>\n\n"
    "Добро пожаловать в пространство цифровых коллекций. Здесь можно "
    "изучать каталог, размещать NFT и следить за ходом сделок.\n\n"
    "Выберите, с чего начнём:"
)

HELP_MESSAGE = (
    "🧭 <b>Центр помощи VILTARA SHOP</b>\n\n"
    "Здесь собраны короткие инструкции для покупателей и продавцов. "
    "Выберите нужный раздел в меню ниже.\n\n"
    "💎 <b>Поддерживаемые активы:</b> TON NFT стандарта TEP-62. "
    "Telegram Gifts пока не поддерживаются.\n\n"
    "Важно: резервирование заказа — не оплата. Платёж, escrow и гарантия "
    "сделки в текущей версии не реализованы."
)

SCREENS = {
    "buy": (
        "🛍 <b>Покупка NFT</b>\n\n"
        "<b>Как это работает:</b>\n"
        "1. Откройте маркетплейс и выберите NFT в каталоге.\n"
        "2. Проверьте описание, сеть и цену продавца.\n"
        "3. Создайте резерв заказа и откройте его детали.\n"
        "4. Следите за этапом передачи NFT в разделе заказов.\n\n"
        "🔎 <b>Что важно знать</b>\n"
        "Резерв фиксирует объявление и цену, но не списывает деньги. "
        "Продавец передаёт NFT из собственного TON-кошелька. Сервис "
        "отдельно проверяет передачу по данным блокчейна.\n\n"
        "💡 Не отправляйте деньги или NFT напрямую незнакомцам по просьбе "
        "пользователя, который представляется поддержкой."
    ),
    "sell": (
        "🏷 <b>Продажа NFT</b>\n\n"
        "<b>Путь продавца:</b>\n"
        "1. Откройте приложение и подключите TON-кошелёк.\n"
        "2. Подтвердите владение через TON Connect Proof.\n"
        "3. Синхронизируйте инвентарь и выберите свой NFT.\n"
        "4. Укажите цену и отправьте объявление на модерацию.\n"
        "5. После резерва заказа откройте его и подтвердите точную "
        "передачу NFT в своём кошельке.\n\n"
        "⏳ Объявление станет публичным только после одобрения модератором.\n\n"
        "🔐 Никогда не передавайте seed-фразу или приватный ключ. "
        "Подписание транзакции происходит только в вашем кошельке."
    ),
    "orders": (
        "📦 <b>Заказы и доставка</b>\n\n"
        "Все актуальные действия и статусы доступны в приложении, "
        "в разделе заказов.\n\n"
        "• <b>Зарезервирован</b> — объявление закреплено за заказом; "
        "оплата не произведена.\n"
        "• <b>Подготовка передачи</b> — продавцу доступно подтверждение "
        "перевода из собственного кошелька.\n"
        "• <b>Проверка транзакции</b> — дождитесь независимой проверки "
        "сервисом, не отправляйте NFT повторно.\n"
        "• <b>Передача подтверждена</b> — backend проверил перевод "
        "по данным сети.\n"
        "• <b>Ручная проверка</b> — статус ещё не подтверждён; "
        "не повторяйте перевод до выяснения.\n\n"
        "Если статус изменился, ориентируйтесь на данные заказа в приложении, "
        "а не на скриншоты или сообщения третьих лиц."
    ),
    "safety": (
        "🛡 <b>Безопасность прежде всего</b>\n\n"
        "VILTARA SHOP не запрашивает и не хранит seed-фразы, приватные ключи "
        "или коды доступа.\n\n"
        "✅ Подключайте кошелёк только через официальный интерфейс TON Connect.\n"
        "✅ Проверяйте сеть, адрес и детали перевода в своём кошельке.\n"
        "✅ Доверяйте статусу доставки в приложении после серверной проверки.\n"
        "❌ Не передавайте NFT «для проверки» посторонним.\n"
        "❌ Не считайте скриншот, хеш или сообщение доказательством доставки.\n"
        "❌ Не вводите seed-фразу на сайтах и в чатах.\n\n"
        "⚠️ Сейчас платёж, escrow, возвраты и гарантия сделки не подключены. "
        "Резервирование не означает оплату."
    ),
    "about": (
        "💎 <b>О VILTARA SHOP</b>\n\n"
        "VILTARA SHOP — P2P-маркетплейс для цифровых коллекционных "
        "TON NFT стандарта TEP-62.\n\n"
        "Покупатели изучают каталог и резервируют объявления. Продавцы "
        "подтверждают владение активом и передают NFT напрямую из своего "
        "кошелька. Передача отдельно проверяется backend-сервисом.\n\n"
        "Telegram Gifts, платёжный checkout, escrow, хранение активов "
        "и выплаты продавцам пока не поддерживаются.\n\n"
        "<i>Прозрачные статусы. Никакого хранения ваших ключей.</i>"
    ),
}


async def _send_menu(message: Message, text: str = START_MESSAGE) -> None:
    await message.answer(
        text,
        reply_markup=_menu_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _send_screen(message: Message, screen: str) -> None:
    await message.answer(
        SCREENS[screen],
        reply_markup=_back_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _edit_screen(callback: CallbackQuery, screen: str) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                SCREENS[screen],
                reply_markup=_back_keyboard(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Show the premium marketplace entry point."""
    await _send_menu(message)


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """Show the help center and available guided flows."""
    await _send_menu(message, HELP_MESSAGE)


@router.message(Command("app"))
async def handle_app(message: Message) -> None:
    """Open the configured Mini App or explain why the link is unavailable."""
    mini_app_button = _mini_app_button(get_settings().telegram_mini_app_url)
    if mini_app_button is None:
        await message.answer(
            "⚙️ Приложение пока недоступно: ссылка не настроена или указана неверно. "
            "Администратору нужно задать <code>TELEGRAM_MINI_APP_URL</code> — "
            "публичный HTTPS-адрес приложения. Подробности: /help.",
            parse_mode="HTML",
        )
        return

    await message.answer(
        "💎 <b>Ваш VILTARA SHOP уже здесь.</b>\n"
        "Нажмите кнопку, чтобы перейти в маркетплейс.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[mini_app_button]]),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("buy"))
async def handle_buy(message: Message) -> None:
    await _send_screen(message, "buy")


@router.message(Command("sell"))
async def handle_sell(message: Message) -> None:
    await _send_screen(message, "sell")


@router.message(Command("orders"))
async def handle_orders(message: Message) -> None:
    await _send_screen(message, "orders")


@router.message(Command("safety"))
async def handle_safety(message: Message) -> None:
    await _send_screen(message, "safety")


@router.callback_query(F.data == "bot:help")
async def handle_help_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                HELP_MESSAGE,
                reply_markup=_menu_keyboard(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise


@router.callback_query(F.data == "bot:menu")
async def handle_menu_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                START_MESSAGE,
                reply_markup=_menu_keyboard(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise


@router.callback_query(F.data == "bot:buy")
async def handle_buy_callback(callback: CallbackQuery) -> None:
    await _edit_screen(callback, "buy")


@router.callback_query(F.data == "bot:sell")
async def handle_sell_callback(callback: CallbackQuery) -> None:
    await _edit_screen(callback, "sell")


@router.callback_query(F.data == "bot:orders")
async def handle_orders_callback(callback: CallbackQuery) -> None:
    await _edit_screen(callback, "orders")


@router.callback_query(F.data == "bot:safety")
async def handle_safety_callback(callback: CallbackQuery) -> None:
    await _edit_screen(callback, "safety")


@router.callback_query(F.data == "bot:about")
async def handle_about_callback(callback: CallbackQuery) -> None:
    await _edit_screen(callback, "about")


@router.callback_query()
async def handle_unknown_callback(callback: CallbackQuery) -> None:
    """Acknowledge stale or unsupported buttons instead of leaving a spinner."""
    await callback.answer(
        "Эта кнопка устарела. Используйте /start, чтобы открыть актуальное меню.",
        show_alert=True,
    )


@router.message(F.text)
async def handle_text_fallback(message: Message) -> None:
    """Guide unsupported text toward the bot's available actions."""
    await _send_menu(
        message,
        "💬 Пока я не умею отвечать на свободные сообщения, но могу помочь "
        "с навигацией по VILTARA SHOP.\n\n"
        "Выберите раздел ниже или используйте /start, /app, /buy, /sell, "
        "/orders, /safety или /help.",
    )
