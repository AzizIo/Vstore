import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.auth.telegram import TelegramInitDataError, verify_telegram_init_data


BOT_TOKEN = "123456:TEST_TOKEN"


def signed_init_data(fields: dict[str, str]) -> str:
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})


def test_valid_init_data_returns_verified_telegram_user() -> None:
    fields = {
        "auth_date": "1000000",
        "query_id": "AAExampleQuery",
        "user": json.dumps(
            {"id": 42, "first_name": "Aziz", "username": "aziz_dev"},
            separators=(",", ":"),
        ),
    }
    result = verify_telegram_init_data(signed_init_data(fields), BOT_TOKEN, now=1000100)
    assert result.user.id == 42
    assert result.user.first_name == "Aziz"
    assert result.user.username == "aziz_dev"
    assert result.query_id == "AAExampleQuery"


def test_optional_user_fields_and_start_param_are_parsed() -> None:
    fields = {
        "auth_date": "1000000",
        "start_param": "campaign_1",
        "user": json.dumps(
            {"id": 7, "first_name": "A", "last_name": "B", "language_code": "ru"},
            separators=(",", ":"),
        ),
    }
    result = verify_telegram_init_data(signed_init_data(fields), BOT_TOKEN, now=1000000)
    assert result.user.last_name == "B"
    assert result.user.language_code == "ru"
    assert result.user.username is None
    assert result.start_param == "campaign_1"


@pytest.mark.parametrize(
    ("init_data", "token", "message"),
    [
        ("", BOT_TOKEN, "length"),
        ("x" * 16_385, BOT_TOKEN, "length"),
        ("auth_date=1", "", "token"),
        ("auth_date", BOT_TOKEN, "Malformed"),
        ("auth_date=1&hash=short", BOT_TOKEN, "hash"),
        ("auth_date=1&hash=" + "z" * 64, BOT_TOKEN, "encoding"),
    ],
)
def test_invalid_envelopes_are_rejected(init_data: str, token: str, message: str) -> None:
    with pytest.raises(TelegramInitDataError, match=message):
        verify_telegram_init_data(init_data, token, now=1000000)


def test_tampered_init_data_is_rejected() -> None:
    fields = {"auth_date": "1000000", "user": json.dumps({"id": 42, "first_name": "Aziz"})}
    payload = signed_init_data(fields).replace("Aziz", "Attacker")
    with pytest.raises(TelegramInitDataError, match="signature"):
        verify_telegram_init_data(payload, BOT_TOKEN, now=1000100)


def test_expired_init_data_is_rejected() -> None:
    fields = {"auth_date": "1000000", "user": json.dumps({"id": 42, "first_name": "Aziz"})}
    with pytest.raises(TelegramInitDataError, match="expired"):
        verify_telegram_init_data(signed_init_data(fields), BOT_TOKEN, now=1000301)


def test_future_auth_date_is_rejected() -> None:
    fields = {"auth_date": "1000100", "user": json.dumps({"id": 42, "first_name": "Aziz"})}
    with pytest.raises(TelegramInitDataError, match="future"):
        verify_telegram_init_data(signed_init_data(fields), BOT_TOKEN, now=1000000)


def test_duplicate_fields_are_rejected() -> None:
    fields = {"auth_date": "1000000", "user": json.dumps({"id": 42, "first_name": "Aziz"})}
    payload = signed_init_data(fields) + "&auth_date=1000000"
    with pytest.raises(TelegramInitDataError, match="Duplicate"):
        verify_telegram_init_data(payload, BOT_TOKEN, now=1000100)


@pytest.mark.parametrize("user_id", [0, -1, True, "42", None])
def test_invalid_telegram_user_ids_are_rejected(user_id: object) -> None:
    fields = {
        "auth_date": "1000000",
        "user": json.dumps({"id": user_id, "first_name": "Aziz"}),
    }
    with pytest.raises(TelegramInitDataError, match="user ID"):
        verify_telegram_init_data(signed_init_data(fields), BOT_TOKEN, now=1000100)


@pytest.mark.parametrize(
    "user_payload",
    [
        "[]",
        "null",
        '{"id":42}',
        '{"id":42,"first_name":""}',
        '{"id":42,"first_name":42}',
        "not-json",
    ],
)
def test_invalid_user_payloads_are_rejected(user_payload: str) -> None:
    fields = {"auth_date": "1000000", "user": user_payload}
    with pytest.raises(TelegramInitDataError):
        verify_telegram_init_data(signed_init_data(fields), BOT_TOKEN, now=1000100)


def test_invalid_max_age_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        verify_telegram_init_data("x", BOT_TOKEN, max_age_seconds=0)
