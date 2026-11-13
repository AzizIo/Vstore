from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import orders as orders_api
from app.assets.ton_nft.dependencies import get_ton_nft_verifier
from app.auth.dependencies import get_current_user
from app.db.models import (
    Order,
    OrderDeliveryAttempt,
    OrderDeliveryAttemptStatus,
    OrderStatus,
    User,
)
from app.db.session import get_db_session
from app.main import app
from app.orders.service import OrderConflict, OrderVerificationUnavailable


@pytest.fixture
def buyer() -> User:
    return User(id=uuid4(), telegram_id=7654321, first_name="Buyer", is_blocked=False)


@pytest.fixture
def api_client(buyer: User):
    app.dependency_overrides[get_current_user] = lambda: buyer
    app.dependency_overrides[get_db_session] = lambda: None
    app.dependency_overrides[get_ton_nft_verifier] = lambda: AsyncMock()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_orders_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/api/orders")
    assert response.status_code == 401


def test_orders_list_is_scoped_to_the_current_user(api_client, buyer, monkeypatch) -> None:
    list_orders = AsyncMock(return_value=[])
    monkeypatch.setattr(orders_api, "list_user_orders", list_orders)

    response = api_client.get("/api/orders?role=buyer")

    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert list_orders.await_args.kwargs["user_id"] == buyer.id
    assert list_orders.await_args.kwargs["role"] == "buyer"


def test_order_detail_hides_orders_not_visible_to_the_user(api_client, monkeypatch) -> None:
    monkeypatch.setattr(orders_api, "get_order", AsyncMock(return_value=None))

    response = api_client.get(f"/api/orders/{uuid4()}")

    assert response.status_code == 404


def test_buyer_cannot_cancel_another_users_order(api_client, monkeypatch) -> None:
    cancel = AsyncMock(side_effect=OrderConflict("Order not found"))
    monkeypatch.setattr(orders_api, "cancel_order", cancel)

    response = api_client.post(f"/api/orders/{uuid4()}/cancel")

    assert response.status_code == 404


def test_create_order_rejects_unavailable_listing(api_client, monkeypatch) -> None:
    create = AsyncMock(side_effect=OrderConflict("Listing is not available"))
    monkeypatch.setattr(orders_api, "create_order", create)

    response = api_client.post(
        "/api/orders",
        json={"listing_id": str(uuid4())},
        headers={"Idempotency-Key": "order-retry-1"},
    )

    assert response.status_code == 409


def test_create_order_requires_idempotency_key(api_client) -> None:
    response = api_client.post("/api/orders", json={"listing_id": str(uuid4())})
    assert response.status_code == 422


def test_create_order_reports_a_retryable_provider_outage(api_client, monkeypatch) -> None:
    create = AsyncMock(
        side_effect=OrderVerificationUnavailable(
            "TON NFT ownership provider is temporarily unavailable"
        )
    )
    monkeypatch.setattr(orders_api, "create_order", create)

    response = api_client.post(
        "/api/orders",
        json={"listing_id": str(uuid4())},
        headers={"Idempotency-Key": "order-provider-outage"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Проверка владения NFT в сети TON временно недоступна. Попробуйте позже."
    )


def test_create_order_passes_the_server_side_verifier(api_client, monkeypatch) -> None:
    create = AsyncMock(side_effect=OrderConflict("Listing is not available"))
    monkeypatch.setattr(orders_api, "create_order", create)

    api_client.post(
        "/api/orders",
        json={"listing_id": str(uuid4())},
        headers={"Idempotency-Key": "order-verifier-wiring"},
    )

    assert create.await_args.kwargs["verifier"] is not None

def _delivery_state_fixture():
    now = datetime.now(UTC)
    order = Order(id=uuid4(), status=OrderStatus.AWAITING_TRANSFER)
    attempt = OrderDeliveryAttempt(
        id=uuid4(),
        order_id=order.id,
        attempt_number=1,
        status=OrderDeliveryAttemptStatus.PREPARED,
        network="mainnet",
        item_address="0:" + "11" * 32,
        seller_address_snapshot="0:" + "22" * 32,
        buyer_address_snapshot="0:" + "33" * 32,
        query_id=Decimal("42"),
        prepared_at=now,
        deadline=now + timedelta(minutes=15),
    )
    return order, attempt


def test_prepare_delivery_route_returns_public_transfer_snapshot(api_client, buyer, monkeypatch):
    order, attempt = _delivery_state_fixture()
    prepare = AsyncMock(return_value=attempt.id)
    state = AsyncMock(return_value=(order, attempt))
    monkeypatch.setattr(orders_api, "prepare_delivery", prepare)
    monkeypatch.setattr(orders_api, "get_order_delivery_state", state)

    response = api_client.post(
        f"/api/orders/{order.id}/delivery/prepare",
        json={"seller_wallet_id": str(uuid4())},
        headers={"Idempotency-Key": "prepare-api-test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["order_status"] == "awaiting_transfer"
    assert payload["attempt"]["id"] == str(attempt.id)
    assert payload["attempt"]["query_id"] == "42"
    assert payload["attempt"]["buyer_address"] == attempt.buyer_address_snapshot
    assert "observer_lease_token" not in payload["attempt"]
    assert prepare.await_args.kwargs["seller_id"] == buyer.id
    assert prepare.await_args.kwargs["idempotency_key"] == "prepare-api-test"


def test_prepare_delivery_route_maps_provider_outage_to_503(api_client, monkeypatch):
    monkeypatch.setattr(
        orders_api,
        "prepare_delivery",
        AsyncMock(side_effect=OrderVerificationUnavailable("provider unavailable")),
    )

    response = api_client.post(
        f"/api/orders/{uuid4()}/delivery/prepare",
        json={"seller_wallet_id": str(uuid4())},
        headers={"Idempotency-Key": "prepare-api-outage"},
    )

    assert response.status_code == 503


def test_delivery_submission_route_persists_candidate_hint(api_client, monkeypatch):
    order, attempt = _delivery_state_fixture()
    submit = AsyncMock(return_value=attempt.id)
    state = AsyncMock(return_value=(order, attempt))
    monkeypatch.setattr(orders_api, "submit_delivery_candidate", submit)
    monkeypatch.setattr(orders_api, "get_order_delivery_state", state)

    response = api_client.post(
        f"/api/orders/{order.id}/delivery/submissions",
        json={"transaction_hash": "ab" * 32},
    )

    assert response.status_code == 200
    assert response.json()["attempt"]["status"] == "prepared"
    assert submit.await_args.kwargs["transaction_hash"] == "ab" * 32


def test_delivery_read_route_hides_non_participant(api_client, monkeypatch):
    monkeypatch.setattr(orders_api, "get_order_delivery_state", AsyncMock(return_value=None))

    response = api_client.get(f"/api/orders/{uuid4()}/delivery")

    assert response.status_code == 404


def test_delivery_submission_rejects_malformed_transaction_hash(api_client):
    response = api_client.post(
        f"/api/orders/{uuid4()}/delivery/submissions",
        json={"transaction_hash": "not-a-ton-hash"},
    )
    assert response.status_code == 422

