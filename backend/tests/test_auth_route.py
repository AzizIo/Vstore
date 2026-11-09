from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth.telegram import TelegramInitDataError
from app.main import app


@pytest.mark.parametrize(
    ("settings", "expected_detail"),
    [
        (
            SimpleNamespace(bot_token=None, auth_secret_key="s" * 32),
            "Telegram authentication is not configured",
        ),
        (
            SimpleNamespace(bot_token="bot-token", auth_secret_key=None),
            "API authentication secret is not configured",
        ),
        (
            SimpleNamespace(bot_token="bot-token", auth_secret_key="short"),
            "API authentication secret is not configured",
        ),
    ],
)
def test_telegram_auth_fails_closed_when_secrets_are_missing(settings, expected_detail) -> None:
    with patch("app.api.auth.get_settings", return_value=settings):
        with TestClient(app) as client:
            response = client.post("/api/auth/telegram", json={"init_data": "payload"})

    assert response.status_code == 503
    assert response.json()["detail"] == expected_detail


def test_telegram_auth_rejects_invalid_init_data_without_database_access() -> None:
    settings = SimpleNamespace(
        bot_token="bot-token",
        auth_secret_key="s" * 32,
        auth_token_ttl_seconds=3600,
    )
    with (
        patch("app.api.auth.get_settings", return_value=settings),
        patch(
            "app.api.auth.verify_telegram_init_data",
            side_effect=TelegramInitDataError("bad signature"),
        ),
        patch("app.api.auth.async_session_factory") as session_factory,
    ):
        with TestClient(app) as client:
            response = client.post("/api/auth/telegram", json={"init_data": "tampered"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired Telegram initData"
    session_factory.assert_not_called()


@pytest.mark.parametrize("init_data", ["", "x" * 16_385])
def test_telegram_auth_rejects_invalid_request_shape(init_data: str) -> None:
    with TestClient(app) as client:
        response = client.post("/api/auth/telegram", json={"init_data": init_data})
    assert response.status_code == 422
