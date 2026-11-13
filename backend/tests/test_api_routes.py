from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.main import app


@pytest.fixture
def client() -> TestClient:
    user = User(
        id=uuid4(),
        telegram_id=123456789,
        username="seller",
        first_name="Seller",
        last_name=None,
        language_code="ru",
        is_blocked=False,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_root_endpoint_returns_service_metadata() -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["name"]


def test_liveness_does_not_require_database_or_redis() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_user_profile_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/api/users/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Для выполнения действия войдите в аккаунт."


def test_user_profile_returns_only_current_user(client: TestClient) -> None:
    response = client.get("/api/users/me")
    assert response.status_code == 200
    assert response.json()["telegram_id"] == 123456789
    assert response.json()["username"] == "seller"
    assert response.json()["first_name"] == "Seller"
    assert "is_blocked" not in response.json()


@pytest.mark.parametrize("limit", ["0", "101", "-1"])
def test_listing_catalog_rejects_invalid_limit(limit: str) -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/listings?limit={limit}")
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert all(
        "msg" in error and "loc" in error and "type" in error
        for error in response.json()["detail"]
    )


def test_listing_catalog_rejects_negative_offset() -> None:
    with TestClient(app) as client:
        response = client.get("/api/listings?offset=-1")
    assert response.status_code == 422


@pytest.mark.parametrize("sort", ["newest", "price_asc", "price_desc"])
def test_listing_catalog_accepts_supported_sort_values(sort: str) -> None:
    class ScalarRows:
        def unique(self):
            return self

        def all(self):
            return []

    session = AsyncMock()
    session.scalar.return_value = 0
    session.scalars.return_value = ScalarRows()

    async def override_session():
        yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        query = f"sort={sort}"
        if sort in {"price_asc", "price_desc"}:
            query += "&currency=TON"
        with TestClient(app) as client:
            response = client.get(f"/api/listings?{query}")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 24, "offset": 0}
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def test_listing_catalog_rejects_price_sort_without_currency() -> None:
    with TestClient(app) as client:
        response = client.get("/api/listings?sort=price_asc")
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Выберите валюту, чтобы фильтровать или сортировать объявления по цене."
    )


def test_listing_catalog_rejects_unknown_sort_with_russian_validation_message() -> None:
    with TestClient(app) as client:
        response = client.get("/api/listings?sort=random-value")
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["msg"] == "Значение не соответствует допустимому формату."
    assert error["loc"] == ["query", "sort"]
    assert error["input"] is None
    assert "random-value" not in response.text


def test_listing_detail_rejects_malformed_uuid() -> None:
    with TestClient(app) as client:
        response = client.get("/api/listings/not-a-uuid")
    assert response.status_code == 422


def test_unknown_route_returns_localized_not_found() -> None:
    with TestClient(app) as client:
        response = client.get("/_route_that_does_not_exist")
    assert response.status_code == 404
    assert response.json()["detail"] == "Запрашиваемый ресурс не найден."


def test_validation_errors_never_echo_submitted_secrets() -> None:
    secret = "DO_NOT_ECHO_THIS_AUTH_SECRET"
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/telegram",
            json={"init_data": {"private_token": secret}},
        )

    assert response.status_code == 422
    assert secret not in response.text
    error = response.json()["detail"][0]
    assert error["msg"] == "Введите текстовое значение."
    assert error["loc"] == ["body", "init_data"]
    assert set(error) == {"loc", "msg", "type", "input"}
