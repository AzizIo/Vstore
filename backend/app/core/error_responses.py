"""Russian, safe-by-default HTTP error responses for the public API.

Internal exception messages remain English and are suitable for logs/tests.
Only this boundary turns them into user-facing text. Validation payloads keep
FastAPI's detail list shape and stable loc/type fields, while omitting raw
inputs and validator context that could contain secrets.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Exact internal messages -> stable public Russian messages.
# Keep English strings here as lookup keys only; never return them to a client.
_ERROR_MESSAGES: dict[str, str] = {
    # Authentication / account access
    "Telegram authentication is not configured": (
        "Вход через Telegram временно недоступен. "
        "Попробуйте позже."
    ),
    "API authentication secret is not configured": (
        "Авторизация временно недоступна. Попробуйте "
        "позже."
    ),
    "API authentication is not configured": (
        "Авторизация временно недоступна. Попробуйте "
        "позже."
    ),
    "Invalid or expired Telegram initData": (
        "Сеанс Telegram недействителен или истёк. "
        "Откройте Mini App заново."
    ),
    "This account is restricted": "Доступ к аккаунту ограничен. Обратитесь в поддержку.",
    "Authentication required": "Для выполнения действия войдите в аккаунт.",
    "Invalid or expired access token": (
        "Сеанс истёк или недействителен. Войдите в "
        "аккаунт повторно."
    ),
    "User no longer exists": "Учётная запись не найдена. Войдите в аккаунт повторно.",
    "Administrator access required": (
        "Для выполнения этого действия нужны права "
        "администратора."
    ),

    # Wallet linking and proof
    "TON Connect proof verification is not configured": (
        "Проверка TON-кошелька временно недоступна. "
        "Попробуйте позже."
    ),
    "Wallet proof challenge storage is unavailable": (
        "Не удалось подготовить проверку TON-кошелька. "
        "Попробуйте позже."
    ),
    "Could not create a wallet proof challenge": (
        "Не удалось начать проверку TON-кошелька. "
        "Попробуйте ещё раз."
    ),
    "Invalid or expired wallet proof": (
        "Подтверждение TON-кошелька недействительно или "
        "устарело. Начните проверку заново."
    ),
    "This wallet is already linked to another account": (
        "Этот TON-кошелёк уже привязан к другому "
        "аккаунту."
    ),
    "Close active listings and pending orders before unlinking a wallet.": (
        "Перед отвязкой кошелька завершите активные объявления и ожидающие заказы."
    ),
    "The verified wallet address is not supported for TON NFT inventory": (
        "Этот адрес подтверждённого TON-кошелька не поддерживается для инвентаря NFT."
    ),
    "Wallet not found": "Кошелёк не найден.",
    "Only a verified wallet can be primary": (
        "Основным можно сделать только подтверждённый "
        "кошелёк."
    ),

    # Inventory and TON provider
    (
        "TON NFT inventory provider returned a repeated "
        "pagination cursor"
    ): (
        "Не удалось полностью загрузить инвентарь NFT. "
        "Обновите страницу и повторите попытку."
    ),
    (
        "TON NFT inventory provider is temporarily "
        "unavailable"
    ): (
        "Сервис инвентаря TON NFT временно недоступен. "
        "Попробуйте позже."
    ),
    "TON NFT inventory provider returned invalid data": (
        "Сервис TON вернул некорректные данные об "
        "инвентаре NFT. Попробуйте позже."
    ),
    (
        "TON NFT inventory provider returned an "
        "inconsistent pagination cursor"
    ): (
        "Не удалось корректно загрузить инвентарь NFT. "
        "Обновите страницу и повторите попытку."
    ),
    (
        "TON NFT inventory provider returned an empty "
        "non-final page"
    ): (
        "Не удалось полностью загрузить инвентарь NFT. "
        "Повторите синхронизацию."
    ),
    (
        "Inventory is too large for one sync; no changes "
        "were saved"
    ): (
        "В инвентаре слишком много NFT для одной "
        "синхронизации. Изменения не сохранены."
    ),
    (
        "Stored inventory is too large for one sync; no "
        "changes were saved"
    ): (
        "Сохранённый инвентарь слишком велик для одной "
        "синхронизации. Изменения не сохранены."
    ),
    (
        "TON NFT ownership provider is temporarily "
        "unavailable"
    ): (
        "Проверка владения NFT в сети TON временно "
        "недоступна. Попробуйте позже."
    ),
    (
        "TON NFT inventory provider did not advance the "
        "pagination cursor"
    ): (
        "Не удалось продолжить загрузку инвентаря NFT. "
        "Повторите синхронизацию."
    ),
    "Inventory sync lock is unavailable": (
        "Синхронизация инвентаря сейчас недоступна. "
        "Попробуйте позже."
    ),
    "Inventory sync lock expired; retry the sync": (
        "Время синхронизации истекло. Запустите её ещё "
        "раз."
    ),
    (
        "A verified wallet address is not supported for "
        "TON NFT inventory"
    ): (
        "Этот формат адреса подтверждённого TON-кошелька "
        "не поддерживается для инвентаря NFT."
    ),
    (
        "The verified wallet workchain is not supported "
        "for TON NFT inventory"
    ): (
        "Сеть или workchain этого TON-кошелька не "
        "поддерживается для инвентаря NFT."
    ),
    (
        "A verified TON wallet is required to sync NFT "
        "inventory"
    ): (
        "Чтобы синхронизировать NFT, сначала подключите и "
        "подтвердите TON-кошелёк."
    ),
    "Verified wallet not found": "Подтверждённый TON-кошелёк не найден.",
    (
        "An NFT inventory sync is already running for "
        "this account"
    ): (
        "Синхронизация инвентаря NFT уже выполняется. "
        "Дождитесь её завершения."
    ),
    (
        "Verified wallets changed during sync; retry to "
        "refresh inventory"
    ): (
        "Список подтверждённых кошельков изменился во "
        "время синхронизации. Повторите её."
    ),
    "Selected wallet changed during sync": (
        "Выбранный кошелёк изменился во время "
        "синхронизации. Обновите страницу и повторите "
        "попытку."
    ),
    (
        "A verified TON wallet is required to discover "
        "NFT inventory"
    ): (
        "Чтобы найти NFT, сначала подключите и "
        "подтвердите TON-кошелёк."
    ),

    # Listings / seller actions
    "Minimum price cannot exceed maximum price": (
        "Минимальная цена не может быть выше "
        "максимальной."
    ),
    (
        "Select a price currency before filtering or "
        "sorting by price"
    ): (
        "Выберите валюту, чтобы фильтровать или "
        "сортировать объявления по цене."
    ),
    "Listing not found": "Объявление не найдено.",
    (
        "Only verified TON NFTs currently owned by you "
        "can be listed"
    ): (
        "Можно выставить только подтверждённый TON NFT, "
        "которым вы владеете сейчас."
    ),
    "This NFT already has an active or reserved listing": (
        "Этот NFT уже выставлен на продажу или "
        "зарезервирован."
    ),
    (
        "A verified TON wallet is required to create a "
        "listing draft"
    ): (
        "Чтобы создать черновик объявления, подключите и "
        "подтвердите TON-кошелёк."
    ),
    (
        "NFT ownership could not be freshly verified; "
        "refresh your inventory"
    ): (
        "Не удалось повторно подтвердить владение NFT. "
        "Обновите инвентарь и попробуйте ещё раз."
    ),
    (
        "NFT inventory changed during verification; "
        "refresh your inventory"
    ): (
        "Инвентарь NFT изменился во время проверки. "
        "Обновите его и повторите попытку."
    ),
    "Only private drafts can be published": "Опубликовать можно только черновик объявления.",
    "This listing draft has already expired": "Срок действия черновика объявления истёк.",
    (
        "Only a currently verified TON NFT owned by you "
        "can be published"
    ): (
        "Опубликовать можно только подтверждённый TON "
        "NFT, которым вы владеете сейчас."
    ),
    (
        "A verified TON wallet on this network is "
        "required to publish a listing"
    ): (
        "Для публикации объявления нужен подтверждённый "
        "TON-кошелёк в той же сети, что и NFT."
    ),
    (
        "Current NFT ownership could not be verified for "
        "your connected wallets"
    ): (
        "Не удалось подтвердить, что NFT по-прежнему "
        "принадлежит одному из подключённых кошельков."
    ),
    (
        "The verified wallet changed during ownership "
        "verification"
    ): (
        "Подтверждённый кошелёк изменился во время "
        "проверки. Обновите страницу и повторите попытку."
    ),
    (
        "NFT ownership or verification state changed; "
        "refresh your inventory"
    ): (
        "Данные о владении NFT изменились. Обновите "
        "инвентарь и повторите попытку."
    ),
    "Provide at least one listing field to update": (
        "Укажите хотя бы одно поле для изменения "
        "объявления."
    ),
    "Price must be greater than zero": "Цена должна быть больше нуля.",
    "Expiration must include a timezone": "Укажите часовой пояс в дате окончания объявления.",
    "Expiration must be in the future": "Дата окончания объявления должна быть в будущем.",
    "Only draft or active listings can be edited": (
        "Изменять можно только черновики и активные "
        "объявления."
    ),
    "Only draft or active listings can be cancelled": (
        "Отменить можно только черновик или активное "
        "объявление."
    ),
    (
        "Listing changed while ownership was being "
        "verified; refresh and try again"
    ): (
        "Объявление изменилось во время проверки "
        "владения. Обновите страницу и попробуйте снова."
    ),

    # Orders and NFT delivery
    "Idempotency key was already used for another listing": (
        "Этот ключ запроса уже использован для другого "
        "объявления. Обновите страницу и повторите "
        "попытку."
    ),
    "Listing is not available": "Объявление сейчас недоступно.",
    "You cannot order your own listing": "Нельзя оформить заказ на собственное объявление.",
    (
        "The TON ownership provider is not configured for "
        "this asset's network"
    ): (
        "Проверка владения NFT для этой сети TON не "
        "настроена. Попробуйте позже."
    ),
    "A TON NFT ownership verifier is required": (
        "Сейчас невозможно проверить владение NFT. "
        "Попробуйте позже."
    ),
    (
        "Listing changed while ownership was being "
        "verified; try again"
    ): (
        "Объявление изменилось во время проверки "
        "владения. Обновите страницу и повторите попытку."
    ),
    (
        "The verified seller wallet changed during "
        "ownership verification"
    ): (
        "Кошелёк продавца изменился во время проверки. "
        "Обновите страницу и повторите попытку."
    ),
    (
        "NFT ownership could not be freshly verified; the "
        "listing is unavailable"
    ): (
        "Не удалось подтвердить владение NFT. Объявление "
        "временно недоступно."
    ),
    "Order not found": "Заказ не найден.",
    "Order unavailable": "Не удалось загрузить заказ. Попробуйте позже.",
    "Order cannot be cancelled after delivery preparation": (
        "Нельзя отменить заказ после подготовки передачи "
        "NFT."
    ),
    (
        "Idempotency key was already used with another "
        "seller wallet"
    ): (
        "Этот ключ запроса уже использован с другим "
        "кошельком продавца. Обновите страницу и "
        "повторите попытку."
    ),
    "Delivery has already been prepared for this order": (
        "Передача NFT для этого заказа уже подготовлена."
    ),
    "Order is not available for delivery preparation": (
        "Для этого заказа сейчас нельзя подготовить "
        "передачу NFT."
    ),
    "Reserved listing is not available": "Зарезервированное объявление больше недоступно.",
    "NFT is not eligible for delivery preparation": (
        "Этот NFT сейчас нельзя передать по данному "
        "заказу."
    ),
    "Choose a verified seller wallet on the NFT network": (
        "Выберите подтверждённый кошелёк продавца в сети "
        "этого NFT."
    ),
    (
        "Buyer must have one verified primary wallet on "
        "the NFT network"
    ): (
        "У покупателя должен быть один основной "
        "подтверждённый кошелёк в сети этого NFT."
    ),
    "A delivery wallet or NFT address is invalid": (
        "Адрес кошелька для передачи или адрес NFT указан "
        "неверно."
    ),
    "Seller and buyer delivery wallets must be different": (
        "Кошельки продавца и покупателя для передачи NFT "
        "должны различаться."
    ),
    "Invalid delivery preparation idempotency key": (
        "Ключ запроса для подготовки передачи NFT указан "
        "неверно."
    ),
    "Delivery is not available": "Передача NFT для этого заказа сейчас недоступна.",
    "Current NFT ownership could not be verified": (
        "Не удалось подтвердить текущее владение NFT. "
        "Передача не подготовлена."
    ),
    (
        "TON provider returned ownership data for a "
        "different NFT or wallet"
    ): (
        "Сервис TON вернул данные о другом NFT или "
        "кошельке. Передача не подготовлена."
    ),
    "Seller ownership of this NFT could not be verified": (
        "Не удалось подтвердить, что продавец владеет "
        "этим NFT. Передача не подготовлена."
    ),
    (
        "Order is no longer available for delivery "
        "preparation"
    ): (
        "Заказ больше не доступен для подготовки передачи "
        "NFT."
    ),
    "Delivery preparation could not be persisted": (
        "Не удалось сохранить подготовку передачи NFT. "
        "Попробуйте ещё раз."
    ),
    "Invalid candidate transaction hash": "Хеш транзакции указан неверно.",
    "Delivery has not been prepared": "Передача NFT ещё не подготовлена.",
    "A different transaction hash was already submitted": (
        "Для этого заказа уже отправлен другой хеш "
        "транзакции."
    ),
    "Delivery preparation window has expired": (
        "Время на подготовку передачи NFT истекло. "
        "Создайте новый запрос."
    ),
    "Order is not accepting a delivery submission": (
        "Этот заказ сейчас не принимает данные о переводе "
        "NFT."
    ),
    "Delivery submission could not be persisted": (
        "Не удалось сохранить данные о переводе NFT. "
        "Попробуйте ещё раз."
    ),

    # Reviews
    "Review is not available for this order": "Для этого заказа нельзя оставить отзыв.",
    "This order has already been reviewed": "Для этого заказа отзыв уже оставлен.",

    # Moderation
    (
        "Idempotency-Key was already used for a different "
        "moderation decision"
    ): (
        "Этот ключ запроса уже использован для другого "
        "решения модерации."
    ),
    "Listing status changed; refresh the queue": (
        "Статус объявления изменился. Обновите список "
        "модерации."
    ),
    "Expired listings cannot be approved or restored": (
        "Нельзя одобрить или восстановить объявление, "
        "срок действия которого истёк."
    ),
    "Current verified NFT ownership is required": (
        "Для этого действия нужно подтвердить текущее "
        "владение NFT."
    ),
    "A verified seller wallet is required": "Нужен подтверждённый TON-кошелёк продавца.",
    "Ownership provider is unavailable": (
        "Сервис проверки владения NFT временно "
        "недоступен. Попробуйте позже."
    ),
    "Fresh NFT ownership could not be verified": (
        "Не удалось подтвердить текущее владение NFT. "
        "Повторите проверку позже."
    ),
    "Listing ownership changed during verification": (
        "Владелец NFT изменился во время проверки. "
        "Обновите очередь и повторите попытку."
    ),
    (
        "Another active or reserved listing exists for "
        "this NFT"
    ): (
        "Для этого NFT уже существует другое активное или "
        "зарезервированное объявление."
    ),
    "Duplicate moderation request": "Такой запрос на модерацию уже обрабатывается.",
}

_STATUS_MESSAGES: dict[int, str] = {
    400: "Некорректный запрос. Проверьте введённые данные.",
    401: "Для выполнения действия войдите в аккаунт.",
    403: "Недостаточно прав для выполнения этого действия.",
    404: "Запрашиваемый ресурс не найден.",
    405: "Этот способ запроса не поддерживается.",
    409: (
        "Операция недоступна из-за текущего состояния "
        "данных. Обновите страницу и повторите попытку."
    ),
    413: "Размер запроса превышает допустимый предел.",
    415: "Формат запроса не поддерживается.",
    422: "Проверьте правильность заполнения полей.",
    429: "Слишком много запросов. Повторите попытку позже.",
    500: "На сервере произошла ошибка. Попробуйте позже.",
    502: "Внешний сервис вернул некорректный ответ. Попробуйте позже.",
    503: "Сервис временно недоступен. Попробуйте позже.",
    504: "Внешний сервис не ответил вовремя. Попробуйте позже.",
}

_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "Обязательное поле не заполнено.",
    "int_parsing": "Введите целое число.",
    "int_type": "Значение должно быть целым числом.",
    "float_parsing": "Введите число.",
    "float_type": "Значение должно быть числом.",
    "decimal_parsing": "Введите корректное числовое значение.",
    "bool_parsing": "Укажите корректное логическое значение.",
    "string_type": "Введите текстовое значение.",
    "string_too_short": "Слишком короткое значение.",
    "string_too_long": "Слишком длинное значение.",
    "string_pattern_mismatch": "Значение не соответствует допустимому формату.",
    "greater_than": "Значение должно быть больше допустимого минимума.",
    "greater_than_equal": "Значение меньше допустимого минимума.",
    "less_than": "Значение превышает допустимый максимум.",
    "less_than_equal": "Значение превышает допустимый максимум.",
    "uuid_parsing": "Укажите корректный идентификатор.",
    "enum": "Выберите одно из допустимых значений.",
    "literal_error": "Выберите одно из допустимых значений.",
    "json_invalid": "Не удалось прочитать JSON. Проверьте формат запроса.",
    "extra_forbidden": "Запрос содержит неизвестное поле. Проверьте названия параметров.",
    "datetime_parsing": "Укажите дату и время в корректном формате.",
    "date_parsing": "Укажите дату в корректном формате.",
    "value_error": "Указанное значение не прошло проверку.",
}

_CUSTOM_VALIDATION_MESSAGES: dict[str, str] = {
    "Value error, Expiration must include a timezone": (
        "Укажите часовой пояс в дате окончания "
        "объявления."
    ),
    "Value error, Expiration must be in the future": (
        "Дата окончания объявления должна быть в будущем."
    ),
    "Value error, Timestamp must be an unsigned integer": (
        "Временная метка должна быть неотрицательным "
        "целым числом."
    ),
    "Value error, Invalid TON transaction hash": "Хеш транзакции TON указан неверно.",
    (
        "Value error, Reason must contain at least five "
        "non-whitespace characters"
    ): (
        "Укажите причину длиной не менее пяти символов."
    ),
}


def localize_http_detail(detail: Any, status_code: int) -> Any:
    """Return only allow-listed, Russian user-facing content."""
    if isinstance(detail, str):
        dynamic_prefixes = (
            "Action requires listing status ",
            "The request could not be completed:",
        )
        if detail.startswith(dynamic_prefixes):
            return _STATUS_MESSAGES.get(status_code, _STATUS_MESSAGES[500])
        return _ERROR_MESSAGES.get(
            detail, _STATUS_MESSAGES.get(status_code, _STATUS_MESSAGES[500])
        )

    # The readiness endpoint has a deliberate machine-readable payload. Keep
    # its established shape and stable state values; discard arbitrary fields.
    if isinstance(detail, dict) and detail.get("status") == "not_ready":
        checks = detail.get("checks")
        if isinstance(checks, dict):
            allowed = {
                "database",
                "redis",
                "authentication",
                "ton_connect_proof",
                "ton_connect_proof_domains",
            }
            safe_checks: dict[str, Any] = {}
            for key, value in checks.items():
                if key not in allowed:
                    continue
                if key == "ton_connect_proof_domains":
                    if isinstance(value, list) and all(
                        isinstance(domain, str)
                        and re.fullmatch(r"[A-Za-z0-9.-]{1,253}", domain)
                        for domain in value
                    ):
                        safe_checks[key] = value
                elif isinstance(value, bool) or (
                    isinstance(value, str) and value in {"ok", "error"}
                ):
                    safe_checks[key] = value
            return {"status": "not_ready", "checks": safe_checks}

    return _STATUS_MESSAGES.get(status_code, _STATUS_MESSAGES[500])


def _validation_message(error: dict[str, Any]) -> str:
    raw_message = error.get("msg")
    if isinstance(raw_message, str):
        custom = _CUSTOM_VALIDATION_MESSAGES.get(raw_message)
        if custom is not None:
            return custom
    error_type = error.get("type")
    if isinstance(error_type, str):
        return _VALIDATION_MESSAGES.get(error_type, _VALIDATION_MESSAGES["value_error"])
    return _VALIDATION_MESSAGES["value_error"]


async def request_validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Translate Pydantic errors without echoing input values or secret context."""
    safe_errors = []
    for error in exc.errors():
        location = error.get("loc", ())
        safe_error = {
            "loc": list(location) if isinstance(location, (list, tuple)) else [],
            "msg": _validation_message(error),
            "type": error.get("type", "value_error"),
        }
        # Preserve Pydantic's optional fields for existing clients, but redact
        # their values because they may contain proofs, tokens or raw request data.
        if "input" in error:
            safe_error["input"] = None
        if "ctx" in error:
            safe_error["ctx"] = {}
        safe_errors.append(safe_error)
    return JSONResponse(
        status_code=422,
        content={"detail": safe_errors},
    )


async def http_exception_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": localize_http_detail(exc.detail, exc.status_code)},
        headers=exc.headers,
    )


async def unhandled_exception_handler(
    _request: Request, _exc: Exception
) -> JSONResponse:
    # The caller logs the traceback; never serialize it, SQL or exception text.
    return JSONResponse(
        status_code=500,
        content={"detail": _STATUS_MESSAGES[500]},
    )
