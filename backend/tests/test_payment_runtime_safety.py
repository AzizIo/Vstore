from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app import payments_bot_handlers
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



@pytest.mark.asyncio
async def test_successful_payment_handler_journals_telegram_update_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeMessage:
        from_user = SimpleNamespace(id=700001)
        successful_payment = SimpleNamespace(
            invoice_payload="opaque-invoice-payload",
            total_amount=25,
            currency="XTR",
            telegram_payment_charge_id="telegram-charge-123",
            provider_payment_charge_id="provider-charge-456",
        )

        async def answer(self, _message: str) -> None:
            return None

    captured: dict[str, object] = {}

    async def record_success(_session: object, **kwargs: object) -> str:
        captured.update(kwargs)
        return "captured"

    monkeypatch.setattr(
        payments_bot_handlers, "async_session_factory", FakeSessionContext
    )
    monkeypatch.setattr(
        payments_bot_handlers, "record_stars_success", record_success
    )

    await payments_bot_handlers.persist_successful_payment(
        FakeMessage(), SimpleNamespace(update_id=987654321)
    )

    assert captured["provider_event_id"] == "update:987654321"
    assert captured["telegram_payment_charge_id"] == "telegram-charge-123"


@pytest.mark.asyncio
async def test_refund_queue_rejects_mutations_when_test_runtime_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(telegram_stars_test_enabled=False)
    _use_settings(monkeypatch, settings)

    with pytest.raises(
        payment_service.PaymentConflict, match="test payments are disabled"
    ):
        await payment_service.queue_stars_refund(
            None,  # Runtime guard must execute before a database operation.
            SimpleNamespace(id="charge-id", status="refund_pending"),
            reason_code="test",
        )
