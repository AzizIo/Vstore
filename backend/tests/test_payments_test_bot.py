from __future__ import annotations

import pytest
from pydantic import SecretStr

from app import payments_test_bot
from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": "postgresql+asyncpg://test:test@localhost:5432/viltara_test",
        "bot_token": "654321:primary-token",
        "telegram_stars_test_enabled": True,
        "telegram_stars_test_bot_token": SecretStr("123456:dedicated-test-token"),
    }
    values.update(overrides)
    return Settings(**values)


def test_test_bot_runtime_accepts_only_dedicated_token_and_local_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(payments_test_bot, "get_settings", lambda: settings)

    assert payments_test_bot._validate_test_bot_runtime() == "123456:dedicated-test-token"


def test_test_bot_runtime_rejects_primary_bot_token_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        telegram_stars_test_bot_token=SecretStr("654321:primary-token"),
    )
    monkeypatch.setattr(payments_test_bot, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="must differ from the primary bot token"):
        payments_test_bot._validate_test_bot_runtime()


@pytest.mark.parametrize("environment", ["local", "development", "production"])
def test_test_bot_runtime_rejects_non_test_environment(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    settings = _settings(environment=environment)
    monkeypatch.setattr(payments_test_bot, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="environment=test"):
        payments_test_bot._validate_test_bot_runtime()


@pytest.mark.parametrize(
    ("database_url", "message"),
    [
        (
            "postgresql+asyncpg://test:test@localhost:5432/viltara",
            "database name must start with test_ or end with _test",
        ),
        (
            "postgresql+asyncpg://test:test@payments.example:5432/viltara_test",
            "local test PostgreSQL host",
        ),
        (
            "sqlite+aiosqlite:///./viltara_test.db",
            "dedicated PostgreSQL test database",
        ),
    ],
)
def test_test_bot_runtime_rejects_non_isolated_database(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    message: str,
) -> None:
    settings = _settings(database_url=database_url)
    monkeypatch.setattr(payments_test_bot, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match=message):
        payments_test_bot._validate_test_bot_runtime()


def test_test_bot_runtime_requires_explicit_enable_flag_and_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled = _settings(telegram_stars_test_enabled=False)
    monkeypatch.setattr(payments_test_bot, "get_settings", lambda: disabled)
    with pytest.raises(RuntimeError, match="TELEGRAM_STARS_TEST_ENABLED"):
        payments_test_bot._validate_test_bot_runtime()

    missing_token = _settings(telegram_stars_test_bot_token=None)
    monkeypatch.setattr(payments_test_bot, "get_settings", lambda: missing_token)
    with pytest.raises(RuntimeError, match="TELEGRAM_STARS_TEST_BOT_TOKEN"):
        payments_test_bot._validate_test_bot_runtime()
