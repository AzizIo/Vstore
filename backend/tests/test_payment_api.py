from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import payments as payments_api
from app.auth.dependencies import get_current_user, get_current_user_allow_blocked
from app.core.config import Settings
from app.db.models import Order, OrderStatus, PriceCurrency, User
from app.db.payments import PaymentIntent
from app.db.session import get_db_session
from app.orders.payment_service import PaymentConflict


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(payments_api.router, prefix="/api")
    return app


@pytest.fixture
def buyer() -> User:
    return User(id=uuid4(), telegram_id=712345678, first_name="Test Buyer", is_blocked=False)


@pytest.fixture
def order(buyer: User) -> Order:
    now = datetime.now(UTC)
    return Order(
        id=uuid4(),
        listing_id=uuid4(),
        buyer_id=buyer.id,
        seller_id=uuid4(),
        idempotency_key=f"order-{uuid4()}",
        status=OrderStatus.RESERVED,
        price_amount=Decimal("25"),
        price_currency=PriceCurrency.XTR,
        expires_at=now + timedelta(minutes=15),
    )


@pytest.fixture
def intent(order: Order, buyer: User) -> PaymentIntent:
    return PaymentIntent(
        id=uuid4(),
        order_id=order.id,
        status="pending",
        amount=Decimal("25"),
        currency="XTR",
        payer_telegram_id=buyer.telegram_id,
        invoice_payload="opaque-test-invoice-payload",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


@pytest.fixture
def client(buyer: User):
    app = _test_app()
    session = AsyncMock()
    app.dependency_overrides[get_current_user] = lambda: buyer
    app.dependency_overrides[get_current_user_allow_blocked] = lambda: buyer
    app.dependency_overrides[get_db_session] = lambda: session
    try:
        with TestClient(app) as test_client:
            yield test_client, session
    finally:
        app.dependency_overrides.clear()


def test_create_payment_intent_requires_authentication() -> None:
    with TestClient(_test_app()) as client:
        response = client.post(
            f"/api/orders/{uuid4()}/payment-intent",
            headers={"Idempotency-Key": "payment-api-key"},
        )
    assert response.status_code == 401


def test_create_payment_intent_requires_idempotency_key(client) -> None:
    test_client, _session = client
    response = test_client.post(f"/api/orders/{uuid4()}/payment-intent")
    assert response.status_code == 422


def test_create_payment_intent_passes_buyer_and_idempotency_key(
    client, buyer: User, order: Order, intent: PaymentIntent, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, _session = client
    monkeypatch.setattr(payments_api, "_test_payment_router_enabled", lambda: True)
    create_intent = AsyncMock(return_value=intent)
    monkeypatch.setattr(payments_api, "create_stars_payment_intent", create_intent)

    class FakeBot:
        session = SimpleNamespace(close=AsyncMock())

    class FakeInvoiceAdapter:
        def __init__(self, _bot) -> None:
            pass

        async def create_invoice_link(self, *, intent: PaymentIntent) -> str:
            assert intent.id is not None
            return "https://t.me/$test-invoice"

    monkeypatch.setattr(payments_api, "create_isolated_test_bot", lambda: FakeBot())
    monkeypatch.setattr(payments_api, "TelegramStarsTestAdapter", FakeInvoiceAdapter)

    response = test_client.post(
        f"/api/orders/{order.id}/payment-intent",
        headers={"Idempotency-Key": "payment-api-replay-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payment_intent_id"] == str(intent.id)
    assert payload["payment_status"] == "pending"
    assert payload["checkout_url"] == "https://t.me/$test-invoice"
    assert "invoice_payload" not in payload
    assert "telegram_payment_charge_id" not in payload
    assert create_intent.await_args.kwargs["buyer_id"] == buyer.id
    assert create_intent.await_args.kwargs["order_id"] == order.id
    assert create_intent.await_args.kwargs["idempotency_key"] == "payment-api-replay-key"


def test_create_payment_intent_maps_idempotency_conflict_to_409(
    client, order: Order, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, _session = client
    monkeypatch.setattr(payments_api, "_test_payment_router_enabled", lambda: True)
    monkeypatch.setattr(
        payments_api,
        "create_stars_payment_intent",
        AsyncMock(side_effect=PaymentConflict("idempotency_payload_conflict")),
    )
    response = test_client.post(
        f"/api/orders/{order.id}/payment-intent",
        headers={"Idempotency-Key": "same-key-different-order"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_payload_conflict"


def test_create_payment_intent_does_not_echo_provider_exception(
    client, order: Order, intent: PaymentIntent, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, _session = client
    monkeypatch.setattr(payments_api, "_test_payment_router_enabled", lambda: True)
    monkeypatch.setattr(
        payments_api, "create_stars_payment_intent", AsyncMock(return_value=intent)
    )

    class FakeBot:
        session = SimpleNamespace(close=AsyncMock())

    class FakeInvoiceAdapter:
        def __init__(self, _bot) -> None:
            pass

        async def create_invoice_link(self, *, intent: PaymentIntent) -> str:
            raise RuntimeError("bot-token=must-not-be-echoed")

    monkeypatch.setattr(payments_api, "create_isolated_test_bot", lambda: FakeBot())
    monkeypatch.setattr(payments_api, "TelegramStarsTestAdapter", FakeInvoiceAdapter)

    response = test_client.post(
        f"/api/orders/{order.id}/payment-intent",
        headers={"Idempotency-Key": "payment-provider-failure"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "payment_provider_unavailable"
    assert "must-not-be-echoed" not in response.text


def test_payment_status_returns_not_started_for_owned_xtr_order(
    client, buyer: User, order: Order
) -> None:
    test_client, session = client
    session.scalar = AsyncMock(side_effect=[order, None])

    response = test_client.get(f"/api/orders/{order.id}/payment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["order_id"] == str(order.id)
    assert payload["payment_status"] == "not_started"
    assert payload["provider"] is None
    assert payload["currency"] == "XTR"
    assert payload["payment_intent_id"] is None


def test_payment_status_hides_order_owned_by_another_buyer(client) -> None:
    test_client, session = client
    session.scalar = AsyncMock(return_value=None)

    response = test_client.get(f"/api/orders/{uuid4()}/payment")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "order_not_found"


def test_payment_status_returns_authoritative_intent_and_refund_state(
    client, order: Order, intent: PaymentIntent
) -> None:
    test_client, session = client
    session.scalar = AsyncMock(side_effect=[order, intent])
    session.scalars = AsyncMock(
        return_value=SimpleNamespace(all=lambda: ["reconciliation_required"])
    )

    response = test_client.get(f"/api/orders/{order.id}/payment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["payment_intent_id"] == str(intent.id)
    assert payload["payment_status"] == "pending"
    assert payload["refund_status"] == "reconciliation_required"
    assert "invoice_payload" not in payload
    assert "payer_telegram_id" not in payload
    assert "provider_payment_charge_id" not in payload


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


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"telegram_stars_test_enabled": False}, False),
        ({"environment": "production"}, False),
        ({"bot_token": "123456:isolated-test-token"}, False),
        ({"database_url": "postgresql+asyncpg://u:p@db:5432/viltara"}, False),
        (
            {
                "database_url": (
                    "postgresql+asyncpg://u:p@prod-db.internal:5432/viltara_test"
                )
            },
            False,
        ),
        ({"database_url": "sqlite+aiosqlite:///./viltara_test.db"}, False),
    ],
)
def test_payment_http_surface_requires_isolated_runtime(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object], expected: bool
) -> None:
    settings = _settings(**overrides)
    monkeypatch.setattr(payments_api, "get_settings", lambda: settings)
    assert payments_api._test_payment_router_enabled(settings) is expected
