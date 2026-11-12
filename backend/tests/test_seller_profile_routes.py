from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_public_seller_profile_requires_no_auth_and_404s_unknown_seller() -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/sellers/{uuid4()}/profile")
    assert response.status_code == 404
    assert response.json() == {"detail": "Seller not found"}


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
def test_public_seller_profile_rejects_unbounded_pagination(query: str) -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/sellers/{uuid4()}/profile?{query}")
    assert response.status_code == 422
