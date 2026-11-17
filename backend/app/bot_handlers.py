import re
from urllib.parse import urlsplit, urlunsplit

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


def _public_https_url(url: str | None) -> str | None:
    """Accept only an absolute public HTTPS URL without credentials or whitespace."""
    if not isinstance(url, str) or not url.strip():
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
    return candidate


def _admin_mini_app_button(url: str | None) -> InlineKeyboardButton | None:
    """Build a fresh Telegram Mini App launch target for the admin workspace."""
    candidate = _public_https_url(url)
    if candidate is None:
        return None

    parsed = urlsplit(candidate)
    # The frontend mounts the workspace at the origin-level /admin route.
    # Reject nested paths, queries and fragments rather than creating a broken link.
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return None

    admin_url = urlunsplit((parsed.scheme, parsed.netloc, "/admin", "", ""))
    return InlineKeyboardButton(
        text="🛡 Открыть админ-панель",
        web_app=WebAppInfo(url=admin_url),
        style="primary",
    )


def _support_keyboard(username: str | None) -> InlineKeyboardMarkup | None:
    """Build a contact button only for a syntactically valid Telegram username."""
    if not isinstance(username, str):
        return None
    candidate = username.strip().removeprefix("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", candidate):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Связаться с поддержкой", url=f"https://t.me/{candidate}")]
        ]
    )


def _terms_keyboard(url: str | None) -> InlineKeyboardMarkup | None:
    candidate = _public_https_url(url)
    if candidate is None:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть полные условия", url=candidate)]
        ]
    )


def _menu_keyboard(
    telegram_user_id: int | None = None,
    *,
    is_private_chat: bool = False,
) -> InlineKeyboardMarkup:
    settings = get_settings()
    rows: list[list[InlineKeyboardButton]] = []
    mini_app_button = _mini_app_button(settings.telegram_mini_app_url)
    if mini_app_button is not None:
        rows.append([mini_app_button])

    if (
        is_private_chat
        and telegram_user_id is not None
        and telegram_user_id in getattr(settings, "admin_telegram_ids", [])
    ):
        admin_button = _admin_mini_app_button(settings.telegram_mini_app_url)
        if admin_button is not None:
            rows.append([admin_button])
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


def _callback_is_private_chat(callback: CallbackQuery) -> bool:
    """Web App buttons are exposed only from private bot chats."""
    message = getattr(callback, "message", None)
    chat = getattr(message, "chat", None)
    return getattr(chat, "type", None) == "private"


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
    "сделки в текущей версии не реализованы. Используйте /terms, /support или "
    "/paysupport для информации о правилах и обращениях."
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
    telegram_user_id = getattr(getattr(message, "from_user", None), "id", None)
    is_private_chat = getattr(getattr(message, "chat", None), "type", None) == "private"
    await message.answer(
        text,
        reply_markup=_menu_keyboard(telegram_user_id, is_private_chat=is_private_chat),
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


@router.message(Command("admin"))
async def handle_admin(message: Message) -> None:
    """Launch the admin workspace only for IDs in the server-side allowlist."""
    settings = get_settings()
    telegram_user = getattr(message, "from_user", None)
    if telegram_user is None or telegram_user.id not in getattr(settings, "admin_telegram_ids", []):
        await message.answer("⛔ Админ-панель доступна только аккаунтам из списка администраторов.")
        return

    if getattr(getattr(message, "chat", None), "type", None) != "private":
        await message.answer("Откройте личный чат с ботом и отправьте /admin.")
        return

    admin_button = _admin_mini_app_button(settings.telegram_mini_app_url)
    if admin_button is None:
        await message.answer(
            "⚙️ Админ-панель не настроена. Администратору нужно задать "
            "TELEGRAM_MINI_APP_URL как публичный HTTPS origin Mini App."
        )
        return

    await message.answer(
        "🛡 <b>Панель модерации VILTARA</b>\n"
        "Запустите её кнопкой ниже прямо в Telegram, чтобы передать свежую "
        "подтверждаемую Telegram-сессию.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[admin_button]]),
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


@router.message(Command("terms"))
async def handle_terms(message: Message) -> None:
    """Show the current service limitations and, when configured, the full terms URL."""
    settings = get_settings()
    keyboard = _terms_keyboard(getattr(settings, "telegram_terms_url", None))
    text = (
        "📄 Условия VILTARA SHOP\n\n"
        "Полные условия сервиса пока не опубликованы. До их публикации коммерческие "
        "функции остаются отключёнными: checkout, оплата, TON escrow, хранение активов "
        "и выплаты продавцам недоступны. Резервирование объявления не является оплатой "
        "или гарантией передачи NFT. Не отправляйте TON или NFT по просьбе посторонних."
    )
    if keyboard is not None:
        text += "\n\nПо ссылке доступны полные опубликованные условия."
    await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


@router.message(Command("support"))
async def handle_support(message: Message) -> None:
    """Expose only an operator-configured support account; never invent a contact."""
    settings = get_settings()
    keyboard = _support_keyboard(getattr(settings, "telegram_support_username", None))
    if keyboard is None:
        await message.answer(
            "Контакт поддержки пока не опубликован. Платёжные операции отключены — "
            "не отправляйте средства. Для навигации используйте /help.",
        )
        return
    await message.answer(
        "Поддержка VILTARA SHOP. Опишите вопрос и приложите только безопасные "
        "идентификаторы заказа/обращения. Не отправляйте seed-фразы, приватные ключи "
        "или коды доступа.",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


@router.message(Command("paysupport"))
async def handle_paysupport(message: Message) -> None:
    """Give payment-incident guidance without enabling or pretending to process checkout."""
    settings = get_settings()
    keyboard = _support_keyboard(getattr(settings, "telegram_support_username", None))
    text = (
        "🧾 Помощь с платежами VILTARA SHOP\n\n"
        "Платёжный checkout сейчас отключён; не оплачивайте заказ и не отправляйте "
        "повторный перевод. Если Telegram уже показывает списание, сохраните ID заказа, "
        "сумму, дату и Telegram payment charge ID и обратитесь в поддержку. "
        "Никогда не отправляйте данные карты, seed-фразу или приватный ключ."
    )
    if keyboard is None:
        text += "\n\nКонтакт поддержки ещё не настроен. Сохраните квитанцию и не повторяйте оплату."
    await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


@router.callback_query(F.data == "bot:help")
async def handle_help_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                HELP_MESSAGE,
                reply_markup=_menu_keyboard(
                    getattr(getattr(callback, "from_user", None), "id", None),
                    is_private_chat=_callback_is_private_chat(callback),
                ),
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
                reply_markup=_menu_keyboard(
                    getattr(getattr(callback, "from_user", None), "id", None),
                    is_private_chat=_callback_is_private_chat(callback),
                ),
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
        "Выберите раздел ниже или используйте /start, /app, /admin, /buy, /sell, "
        "/orders, /safety, /paysupport, /terms, /support или /help.",
    )
