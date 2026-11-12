from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import reviews as reviews_api
from app.auth.dependencies import get_current_user
from app.db.models import SellerReview, User
from app.db.session import get_db_session
from app.main import app
from app.reviews.schemas import (
    EligibilityResponse,
    ReviewCreateResponse,
    ReviewPageResponse,
)


@pytest.fixture
def buyer() -> User:
    return User(id=uuid4(), telegram_id=765400001, first_name="Buyer", is_blocked=False)


@pytest.fixture
def api_client(buyer: User):
    app.dependency_overrides[get_current_user] = lambda: buyer
    app.dependency_overrides[get_db_session] = lambda: None
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_public_reviews_response_exposes_only_safe_fields(api_client, monkeypatch):
    seller_id = uuid4()
    page = ReviewPageResponse(
        seller_id=seller_id,
        average_rating=4.5,
        review_count=2,
        rating_distribution={"1": 0, "2": 0, "3": 0, "4": 1, "5": 1},
        items=[
            {
                "id": uuid4(),
                "rating": 5,
                "comment": "Verified transfer.",
                "created_at": datetime.now(UTC),
            }
        ],
        limit=20,
        offset=0,
        has_more=False,
    )
    monkeypatch.setattr(reviews_api, "list_seller_reviews", AsyncMock(return_value=page))

    response = api_client.get(f"/api/reviews/sellers/{seller_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_count"] == 2
    assert payload["items"][0]["rating"] == 5
    assert "buyer_id" not in payload["items"][0]
    assert "telegram_id" not in payload["items"][0]
    assert "username" not in payload["items"][0]


def test_eligibility_is_opaque_for_an_unavailable_order(api_client, monkeypatch):
    monkeypatch.setattr(
        reviews_api,
        "get_review_eligibility",
        AsyncMock(return_value=EligibilityResponse(
            order_id=uuid4(), eligible=False, already_reviewed=False
        )),
    )

    response = api_client.get(f"/api/reviews/eligibility?order_id={uuid4()}")

    assert response.status_code == 200
    assert response.json()["eligible"] is False
    assert "reason" not in response.json()


def test_create_review_derives_seller_from_order(api_client, monkeypatch):
    order_id = uuid4()
    result = ReviewCreateResponse(
        id=uuid4(), order_id=order_id, rating=5, comment="Great", created_at=datetime.now(UTC)
    )
    create = AsyncMock(return_value=result)
    monkeypatch.setattr(reviews_api, "create_review", create)

    response = api_client.post(
        "/api/reviews",
        json={"order_id": str(order_id), "rating": 5, "comment": "  Great  "},
    )

    assert response.status_code == 201
    assert response.json()["order_id"] == str(order_id)
    assert "seller_id" not in response.json()
    current_user = api_client.app.dependency_overrides[get_current_user]()
    assert create.await_args.kwargs["buyer_id"] == current_user.id


def test_create_response_validates_persisted_review_model():
    review = SellerReview(
        id=uuid4(),
        order_id=uuid4(),
        buyer_id=uuid4(),
        seller_id=uuid4(),
        rating=5,
        comment="Verified transfer",
        created_at=datetime.now(UTC),
    )

    result = ReviewCreateResponse.model_validate(review)

    assert result.order_id == review.order_id
    assert result.rating == 5


def test_create_review_rejects_invalid_rating(api_client):
    response = api_client.post(
        "/api/reviews",
        json={"order_id": str(uuid4()), "rating": 6, "comment": "Nope"},
    )
    assert response.status_code == 422
