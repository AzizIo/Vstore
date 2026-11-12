from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.admin.moderation import DecisionRequest
from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.models import ListingStatus, User
from app.db.session import get_db_session
from app.main import app


@pytest.fixture
def user() -> User:
    return User(
        id=uuid4(), telegram_id=987654321, username="moderator-test",
        first_name="Moderator", last_name=None, language_code="en", is_blocked=False,
    )


@pytest.fixture
def client(user: User, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(get_settings(), "admin_telegram_ids", [])
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.pop(get_db_session, None)


def test_admin_access_fails_closed_when_allowlist_empty(client: TestClient) -> None:
    response = client.get("/api/admin/access")
    assert response.status_code == 200
    assert response.json() == {"is_admin": False}


def test_non_admin_cannot_read_queue_or_audit(client: TestClient) -> None:
    assert client.get("/api/admin/moderation").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403


def test_non_admin_cannot_mutate_even_with_client_supplied_actor(client: TestClient) -> None:
    response = client.post(
        f"/api/admin/listings/{uuid4()}/decision",
        headers={"Idempotency-Key": "e2e-request-0001"},
        json={
            "action": "suspend", "reason_code": "other",
            "reason": "Needs manual review", "actor_id": str(uuid4()),
        },
    )
    assert response.status_code in {403, 422}


def test_decision_rejects_client_supplied_actor() -> None:
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate({
            "action": "suspend", "reason_code": "other",
            "reason": "Needs manual review", "actor_id": str(uuid4()),
        })


@pytest.mark.parametrize("limit", ["0", "101", "-1"])
def test_admin_queue_bounds_pagination(client: TestClient, limit: str) -> None:
    get_settings().admin_telegram_ids = [987654321]
    response = client.get(f"/api/admin/moderation?limit={limit}")
    assert response.status_code == 422
    get_settings().admin_telegram_ids = []


def test_audit_snapshot_excludes_telegram_ids_and_wallet_addresses() -> None:
    from decimal import Decimal
    from types import SimpleNamespace

    from app.admin.moderation import _snapshot
    from app.db.models import AssetVerificationStatus, PriceCurrency

    seller_id = uuid4()
    listing = SimpleNamespace(
        id=uuid4(),
        status=ListingStatus.ACTIVE,
        title="Privacy test listing",
        price_amount=Decimal("12.5"),
        price_currency=PriceCurrency.TON,
        seller_id=seller_id,
        asset=SimpleNamespace(
            verification_status=AssetVerificationStatus.VERIFIED,
            owner_id=seller_id,
            item_address="private-item-address",
            wallet_address="private-wallet-address",
        ),
        telegram_id=123456789,
    )
    snapshot = _snapshot(listing)
    assert snapshot["asset_owner_matches_seller"] is True
    assert "telegram_id" not in snapshot
    assert "wallet_address" not in snapshot
    assert "item_address" not in snapshot
