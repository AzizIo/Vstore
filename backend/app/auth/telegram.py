from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


@dataclass(frozen=True, slots=True)
class TelegramWebAppUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class VerifiedTelegramInitData:
    auth_date: int
    user: TelegramWebAppUser
    query_id: str | None = None
    start_param: str | None = None


class TelegramInitDataError(ValueError):
    """Raised when Telegram Mini App initData is invalid or expired."""


def verify_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 300,
    now: int | None = None,
) -> VerifiedTelegramInitData:
    """Verify Telegram Mini App initData using Telegram's HMAC-SHA-256 scheme.

    The function deliberately accepts only a short-lived payload. Callers must
    never trust user fields parsed from initData before this verification passes.
    """
    if not init_data or len(init_data) > 16_384:
        raise TelegramInitDataError("Invalid initData length")
    if not bot_token:
        raise TelegramInitDataError("Bot token is not configured")
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise TelegramInitDataError("Malformed initData") from exc

    data: dict[str, str] = {}
    for key, value in pairs:
        if key in data:
            raise TelegramInitDataError("Duplicate initData field")
        data[key] = value

    received_hash = data.pop("hash", None)
    if received_hash is None or len(received_hash) != 64:
        raise TelegramInitDataError("Missing or invalid initData hash")
    try:
        bytes.fromhex(received_hash)
    except ValueError as exc:
        raise TelegramInitDataError("Invalid initData hash encoding") from exc

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash.lower()):
        raise TelegramInitDataError("initData signature verification failed")

    try:
        auth_date = int(data["auth_date"])
    except (KeyError, ValueError) as exc:
        raise TelegramInitDataError("Missing or invalid auth_date") from exc

    current_time = int(time.time()) if now is None else now
    age = current_time - auth_date
    if age < -30:
        raise TelegramInitDataError("initData auth_date is in the future")
    if age > max_age_seconds:
        raise TelegramInitDataError("initData has expired")

    try:
        user_payload = json.loads(data["user"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise TelegramInitDataError("Missing or invalid Telegram user payload") from exc

    if not isinstance(user_payload, dict):
        raise TelegramInitDataError("Invalid Telegram user payload")

    user_id = user_payload.get("id")
    first_name = user_payload.get("first_name")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise TelegramInitDataError("Invalid Telegram user ID")
    if not isinstance(first_name, str) or not first_name.strip():
        raise TelegramInitDataError("Invalid Telegram first name")

    def optional_string(field: str) -> str | None:
        value = user_payload.get(field)
        return value if isinstance(value, str) else None

    user = TelegramWebAppUser(
        id=user_id,
        first_name=first_name,
        last_name=optional_string("last_name"),
        username=optional_string("username"),
        language_code=optional_string("language_code"),
        photo_url=optional_string("photo_url"),
    )
    return VerifiedTelegramInitData(
        auth_date=auth_date,
        user=user,
        query_id=data.get("query_id"),
        start_param=data.get("start_param"),
    )
