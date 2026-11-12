from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import app


@pytest.fixture
def public_seller_client():
    session = AsyncMock()
    session.scalar.return_value = None

    async def override_db_session():
        yield session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def test_public_seller_profile_requires_no_auth_and_404s_unknown_seller(
    public_seller_client,
) -> None:
    client, session = public_seller_client
    response = client.get(f"/api/sellers/{uuid4()}/profile")
    assert response.status_code == 404
    assert response.json() == {"detail": "Seller not found"}
    session.scalar.assert_awaited_once()


@pytest.mark.parametrize(
    "query",
    [
        "listings_limit=0",
        "listings_limit=49",
        "reviews_limit=0",
        "reviews_limit=51",
        "listings_offset=-1",
        "reviews_offset=-1",
    ],
)
def test_public_seller_profile_rejects_unbounded_pagination(
    public_seller_client, query: str
) -> None:
    client, session = public_seller_client
    response = client.get(f"/api/sellers/{uuid4()}/profile?{query}")
    assert response.status_code == 422
    session.scalar.assert_not_awaited()
