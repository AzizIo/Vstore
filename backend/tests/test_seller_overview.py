from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.db.models import ListingStatus, OrderStatus, PriceCurrency, User
from app.db.session import get_db_session
from app.main import app


class Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


def test_seller_overview_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/api/users/me/overview")
    assert response.status_code == 401


def test_seller_overview_returns_private_counts_and_currency_safe_snapshots() -> None:
    user = User(
        id=uuid4(),
        telegram_id=123456789,
        username="seller",
        first_name="Seller",
        is_blocked=False,
    )
    session = AsyncMock()
    session.execute.side_effect = [
        Rows(
            [
                (ListingStatus.ACTIVE, 3),
                (ListingStatus.DRAFT, 1),
                (ListingStatus.PENDING_REVIEW, 2),
                (ListingStatus.SUSPENDED, 2),
            ]
        ),
        Rows([(OrderStatus.RESERVED, 2), (OrderStatus.COMPLETED, 1)]),
        Rows([(OrderStatus.COMPLETED, 1)]),
        Rows([(PriceCurrency.TON, Decimal("12.500000000")), (PriceCurrency.XTR, Decimal("40"))]),
        Rows([(PriceCurrency.TON, Decimal("3.25"))]),
        Rows([]),
        Rows([]),
    ]

    async def override_session():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get("/api/users/me/overview")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["listings"] == {
        "draft": 1, "pending_review": 2, "active": 3, "reserved": 0, "sold": 0,
        "cancelled": 0, "expired": 0, "suspended": 2, "total": 8,
    }
    assert payload["orders_as_seller"]["reserved"] == 2
    assert payload["orders_as_seller"]["completed"] == 1
    assert payload["orders_as_seller"]["total"] == 3
    assert payload["orders_as_buyer"]["completed"] == 1
    assert payload["reserved_order_snapshot_values"] == {
        "TON": "12.500000000",
        "XTR": "40",
    }
    assert payload["completed_order_snapshot_values"] == {"TON": "3.25"}
    assert payload["recent_activity"] == []

    assert session.execute.await_count == 7
    for call in session.execute.await_args_list:
        statement = call.args[0]
        compiled_values = statement.compile().params.values()
        assert user.id in compiled_values


def test_seller_overview_merges_activity_streams_by_recency_and_caps_results() -> None:
    user = User(
        id=uuid4(),
        telegram_id=123456789,
        username="seller",
        first_name="Seller",
        is_blocked=False,
    )
    now = datetime(2026, 11, 12, tzinfo=UTC)
    listings = [
        (
            SimpleNamespace(
                id=uuid4(),
                title=f"Listing {index}",
                status=ListingStatus.ACTIVE,
                created_at=now - timedelta(days=30 - index),
                updated_at=now - timedelta(days=30 - index),
                price_amount=Decimal("1"),
                price_currency=PriceCurrency.TON,
            ),
            f"Asset {index}",
        )
        for index in range(10)
    ]
    orders = [
        (
            SimpleNamespace(
                id=uuid4(),
                buyer_id=user.id,
                seller_id=uuid4(),
                listing_id=uuid4(),
                status=OrderStatus.COMPLETED,
                updated_at=now - timedelta(minutes=10 - index),
                price_amount=Decimal("2"),
                price_currency=PriceCurrency.TON,
            ),
            f"Order listing {index}",
            f"Order asset {index}",
        )
        for index in range(10)
    ]
    session = AsyncMock()
    session.execute.side_effect = [
        Rows([]),
        Rows([]),
        Rows([]),
        Rows([]),
        Rows([]),
        Rows(listings),
        Rows(orders),
    ]

    async def override_session():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get("/api/users/me/overview")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    activity = response.json()["recent_activity"]
    assert len(activity) == 10
    assert all(item["kind"] == "order" for item in activity)
    assert all(item["role"] == "buyer" for item in activity)
    assert activity[0]["id"] == str(orders[-1][0].id)
