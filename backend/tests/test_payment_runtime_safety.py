from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.orders import payment_service


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": "postgresql+asyncpg://test:test@localhost:5432/viltara_test",
        "bot_token": "654321:primary-test-token",
        "telegram_stars_test_enabled": True,
        "telegram_stars_test_bot_token": SecretStr("123456:isolated-test-token"),
    }
    values.update(overrides)
    return Settings(**values)


def _use_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(payment_service, "get_settings", lambda: settings)


def test_payment_service_accepts_only_isolated_local_test_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_settings(monkeypatch, _settings())

    payment_service._assert_test_stars_enabled()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        (
            {"database_url": "postgresql+asyncpg://user:pass@localhost:5432/viltara"},
            "test-named database",
        ),
        (
            {
                "database_url": (
                    "postgresql+asyncpg://user:pass@prod-db.internal:5432/viltara_test"
                )
            },
            "local PostgreSQL host",
        ),
        (
            {"database_url": "sqlite+aiosqlite:///./viltara_test.db"},
            "require PostgreSQL",
        ),
        (
            {"bot_token": "123456:isolated-test-token"},
            "must differ from BOT_TOKEN",
        ),
        (
            {"bot_token": None},
            "BOT_TOKEN must be configured",
        ),
    ],
)
def test_payment_service_rejects_non_isolated_test_runtime(
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, object],
    message: str,
) -> None:
    _use_settings(monkeypatch, _settings(**override))

    with pytest.raises(payment_service.PaymentConflict, match=message):
        payment_service._assert_test_stars_enabled()
