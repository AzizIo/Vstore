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
        with TestClient(app) as client:
            response = client.get(f"/api/listings?sort={sort}")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 24, "offset": 0}
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def test_listing_catalog_rejects_unknown_sort() -> None:
    with TestClient(app) as client:
        response = client.get("/api/listings?sort=random")
    assert response.status_code == 422


def test_listing_detail_rejects_malformed_uuid() -> None:
    with TestClient(app) as client:
        response = client.get("/api/listings/not-a-uuid")
    assert response.status_code == 422
