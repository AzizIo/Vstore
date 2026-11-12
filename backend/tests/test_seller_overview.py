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
        Rows([(ListingStatus.ACTIVE, 3), (ListingStatus.DRAFT, 1)]),
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
        "draft": 1, "active": 3, "reserved": 0, "sold": 0,
        "cancelled": 0, "expired": 0, "total": 4,
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
