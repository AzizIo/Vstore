from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.admin.user_management import AdminUserAccessDecisionRequest
from app.assets.ton_nft.dependencies import get_ton_nft_verifier
from app.auth.dependencies import get_current_user, get_current_user_allow_blocked
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db_session
from app.main import app


@pytest.fixture
def ordinary_user() -> User:
    return User(
        id=uuid4(),
        telegram_id=987650001,
        first_name="Ordinary",
        last_name="User",
        username="ordinary_user",
        is_blocked=False,
    )


@pytest.fixture
def client(ordinary_user: User, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(get_settings(), "admin_telegram_ids", [])
    app.dependency_overrides[get_current_user] = lambda: ordinary_user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_non_admin_cannot_read_any_new_admin_surface(client: TestClient) -> None:
    user_id = str(uuid4())
    assert client.get("/api/admin/overview").status_code == 403
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/users/" + user_id).status_code == 403
    assert client.get("/api/admin/users/" + user_id + "/listings").status_code == 403
    assert client.get("/api/admin/users/" + user_id + "/orders").status_code == 403
    assert client.get("/api/admin/users/" + user_id + "/audit").status_code == 403
    assert client.get("/api/admin/orders").status_code == 403
    assert client.get("/api/admin/audit-log").status_code == 403


def test_non_admin_cannot_block_or_unblock_a_user(client: TestClient) -> None:
    user_id = str(uuid4())
    headers = {"Idempotency-Key": "user-access-001"}
    payload = {"reason": "Policy review required"}
    block_response = client.post(
        f"/api/admin/users/{user_id}/block", headers=headers, json=payload
    )
    unblock_response = client.post(
        f"/api/admin/users/{user_id}/unblock", headers=headers, json=payload
    )
    assert block_response.status_code == 403
    assert unblock_response.status_code == 403


def test_access_decision_requires_reason_and_rejects_client_actor() -> None:
    with pytest.raises(ValidationError):
        AdminUserAccessDecisionRequest.model_validate({"reason": "no"})
    with pytest.raises(ValidationError):
        AdminUserAccessDecisionRequest.model_validate({
            "reason": "Review confirmed by the team",
            "actor_id": str(uuid4()),
            "is_admin": True,
        })


@pytest.mark.parametrize("limit", ["0", "101", "-1"])
def test_admin_user_pagination_bounds(client: TestClient, limit: str) -> None:
    get_settings().admin_telegram_ids = [987650001]
    response = client.get(f"/api/admin/users?limit={limit}")
    assert response.status_code == 422
    get_settings().admin_telegram_ids = []


@pytest.mark.parametrize("query", ["", "bad username", "@", "a" * 66, "user-name-with-dashes"])
def test_admin_user_search_validation(client: TestClient, query: str) -> None:
    get_settings().admin_telegram_ids = [987650001]
    response = client.get("/api/admin/users", params={"q": query})
    assert response.status_code == 422
    get_settings().admin_telegram_ids = []


def test_admin_orders_has_no_write_or_payment_status_routes() -> None:
    routes = {
        (method, route.path)
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods
        if route.path.startswith("/api/admin/orders")
    }
    assert routes == {("GET", "/api/admin/orders")}



def test_blocked_user_cannot_create_a_new_order_but_can_read_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_user = User(
        id=uuid4(),
        telegram_id=987650002,
        first_name="Restricted",
        username="restricted_user",
        is_blocked=True,
    )
    monkeypatch.setattr(get_settings(), "admin_telegram_ids", [])
    app.dependency_overrides[get_current_user_allow_blocked] = lambda: blocked_user
    app.dependency_overrides[get_current_user] = lambda: blocked_user

    async def unused_session():
        yield None

    app.dependency_overrides[get_db_session] = unused_session
    app.dependency_overrides[get_ton_nft_verifier] = lambda: object()
    try:
        with TestClient(app) as client:
            profile = client.get("/api/users/me")
            assert profile.status_code == 200
            assert profile.json()["is_blocked"] is True

            response = client.post(
                "/api/orders",
                headers={"Idempotency-Key": "blocked-create-order-001"},
                json={"listing_id": str(uuid4())},
            )
            assert response.status_code == 403
            assert "creating new orders is disabled" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
