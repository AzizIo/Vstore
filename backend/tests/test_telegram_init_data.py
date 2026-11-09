import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.auth.telegram import TelegramInitDataError, verify_telegram_init_data


BOT_TOKEN = "123456:TEST_TOKEN"


def signed_init_data(fields: dict[str, str]) -> str:
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items())
    )
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})


def test_valid_init_data_returns_verified_telegram_user() -> None:
    fields = {
        "auth_date": "1_000_000",
        "query_id": "AAExampleQuery",
        "user": json.dumps(
            {"id": 42, "first_name": "Aziz", "username": "aziz_dev"},
            separators=(",", ":"),
        ),
    }

    result = verify_telegram_init_data(
        signed_init_data(fields), BOT_TOKEN, now=1_000_100
    )

    assert result.user.id == 42
    assert result.user.first_name == "Aziz"
    assert result.user.username == "aziz_dev"
    assert result.query_id == "AAExampleQuery"


def test_tampered_init_data_is_rejected() -> None:
    fields = {
        "auth_date": "1_000_000",
        "user": json.dumps({"id": 42, "first_name": "Aziz"}),
    }
    payload = signed_init_data(fields).replace("Aziz", "Attacker")

    with pytest.raises(TelegramInitDataError, match="signature"):
        verify_telegram_init_data(payload, BOT_TOKEN, now=1_000_100)


def test_expired_init_data_is_rejected() -> None:
    fields = {
        "auth_date": "1_000_000",
        "user": json.dumps({"id": 42, "first_name": "Aziz"}),
    }

    with pytest.raises(TelegramInitDataError, match="expired"):
        verify_telegram_init_data(
            signed_init_data(fields), BOT_TOKEN, now=1_000_301
        )


def test_future_auth_date_is_rejected() -> None:
    fields = {
        "auth_date": "1_000_100",
        "user": json.dumps({"id": 42, "first_name": "Aziz"}),
    }

    with pytest.raises(TelegramInitDataError, match="future"):
        verify_telegram_init_data(
            signed_init_data(fields), BOT_TOKEN, now=1_000_000
        )


def test_duplicate_fields_are_rejected() -> None:
    fields = {
        "auth_date": "1_000_000",
        "user": json.dumps({"id": 42, "first_name": "Aziz"}),
    }
    payload = signed_init_data(fields) + "&auth_date=1000000"

    with pytest.raises(TelegramInitDataError, match="Duplicate"):
        verify_telegram_init_data(payload, BOT_TOKEN, now=1_000_100)


def test_non_positive_telegram_user_id_is_rejected() -> None:
    fields = {
        "auth_date": "1_000_000",
        "user": json.dumps({"id": 0, "first_name": "Aziz"}),
    }

    with pytest.raises(TelegramInitDataError, match="user ID"):
        verify_telegram_init_data(
            signed_init_data(fields), BOT_TOKEN, now=1_000_100
        )
