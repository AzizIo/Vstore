from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    PriceCurrency,
    User,
)
from app.db.session import get_db_session
from app.main import app


class ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def unique(self):
        return self

    def all(self):
        return self.rows

    def one_or_none(self):
        return self.rows[0] if self.rows else None


@pytest.fixture
def seller() -> User:
    return User(
        id=uuid4(),
        telegram_id=987654321,
        username="seller",
        first_name="Seller",
        is_blocked=False,
    )


@pytest.fixture
def api_client(seller: User):
    app.dependency_overrides[get_current_user] = lambda: seller
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def install_session_override(session) -> None:
    async def override_session():
        yield session

    app.dependency_overrides[get_db_session] = override_session


def make_verified_asset(owner_id):
    return NFTAsset(
        id=uuid4(),
        asset_type=AssetType.TON_NFT,
        external_id="ton-item-123",
        owner_id=owner_id,
        name="Rare Gift",
        verification_status=AssetVerificationStatus.VERIFIED,
    )


def make_listing(seller: User, asset: NFTAsset, status=ListingStatus.ACTIVE):
    return Listing(
        id=uuid4(),
        asset_id=asset.id,
        seller_id=seller.id,
        status=status,
        price_amount=Decimal("2.500000000"),
        price_currency=PriceCurrency.TON,
        title="Rare Gift",
        asset=asset,
        seller=seller,
    )


def test_my_listings_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/api/listings/me")
    assert response.status_code == 401


def test_my_listings_returns_authenticated_sellers_items(api_client, seller) -> None:
    asset = make_verified_asset(seller.id)
    listing = make_listing(seller, asset, ListingStatus.DRAFT)
    session = SimpleNamespace(scalars=AsyncMock(return_value=ScalarRows([listing])))
    install_session_override(session)
    try:
        response = api_client.get("/api/listings/me")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == str(listing.id)
    assert response.json()[0]["status"] == "draft"
    assert response.json()[0]["seller"]["id"] == str(seller.id)


def test_listing_detail_returns_only_active_listing(api_client) -> None:
    session = SimpleNamespace(scalars=AsyncMock(return_value=ScalarRows([])))
    install_session_override(session)
    try:
        response = api_client.get(f"/api/listings/{uuid4()}")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 404
    assert response.json()["detail"] == "Listing not found"


def test_create_listing_rejects_asset_not_verified_or_not_owned(api_client, seller) -> None:
    session = SimpleNamespace(scalar=AsyncMock(return_value=None), add=Mock(), commit=AsyncMock())
    install_session_override(session)
    try:
        response = api_client.post(
            "/api/listings",
            json={
                "asset_id": str(uuid4()),
                "price_amount": "1.5",
                "price_currency": "TON",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 409
    assert "verified assets" in response.json()["detail"]
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_create_listing_creates_draft_for_verified_owned_asset(api_client, seller) -> None:
    asset = make_verified_asset(seller.id)
    created_listing = make_listing(seller, asset, ListingStatus.DRAFT)
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=asset),
        add=Mock(),
        commit=AsyncMock(),
        scalars=AsyncMock(return_value=ScalarRows([created_listing])),
    )
    install_session_override(session)
    try:
        response = api_client.post(
            "/api/listings",
            json={
                "asset_id": str(asset.id),
                "price_amount": "2.5",
                "price_currency": "TON",
                "title": "Rare Gift",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    assert response.json()["asset"]["id"] == str(asset.id)
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "payload",
    [
        {"asset_id": "not-a-uuid", "price_amount": "1", "price_currency": "TON"},
        {"asset_id": str(uuid4()), "price_amount": "0", "price_currency": "TON"},
        {"asset_id": str(uuid4()), "price_amount": "1", "price_currency": "USD"},
    ],
)
def test_create_listing_rejects_invalid_payloads(api_client, payload) -> None:
    response = api_client.post("/api/listings", json=payload)
    assert response.status_code == 422
