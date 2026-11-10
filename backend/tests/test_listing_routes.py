from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import listings as listings_api
from app.assets.ton_nft.dependencies import get_ton_nft_verifier
from app.assets.ton_nft.models import (
    NFTMetadata,
    VerificationResult,
    VerificationStatus,
)
from app.auth.dependencies import get_current_user
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    User,
    Wallet,
)
from app.db.session import get_db_session
from app.listings.service import ListingConflict, ListingNotFound, ListingVerificationUnavailable
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

    def one(self):
        return self.rows[0]


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
        external_id="0:" + "11" * 32,
        item_address="0:" + "11" * 32,
        owner_id=owner_id,
        name="Rare Gift",
        verification_status=AssetVerificationStatus.VERIFIED,
    )


def make_verified_wallet(owner_id):
    return Wallet(
        id=uuid4(),
        user_id=owner_id,
        address="0:" + "22" * 32,
        network="mainnet",
        is_verified=True,
        is_primary=True,
    )


class StubVerifier:
    def __init__(self, result=None):
        self.result = result or VerificationResult(
            VerificationStatus.VERIFIED,
            "0:" + "11" * 32,
            owner_address="0:" + "22" * 32,
            expected_owner_address="0:" + "22" * 32,
            metadata=NFTMetadata(name="Fresh NFT"),
        )
        self.calls = []

    async def verify(self, item_address, expected_owner_address):
        self.calls.append((item_address, expected_owner_address))
        return self.result


def make_listing(seller: User, asset: NFTAsset, status=ListingStatus.ACTIVE):
    return Listing(
        id=uuid4(),
        asset_id=asset.id,
        seller_id=seller.id,
        status=status,
        title="Rare Gift",
        created_at=datetime.now(UTC),
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
            },
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 409
    assert "verified TON NFTs" in response.json()["detail"]
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_create_listing_creates_draft_for_verified_owned_asset(api_client, seller) -> None:
    asset = make_verified_asset(seller.id)
    wallet = make_verified_wallet(seller.id)
    created_listing = make_listing(seller, asset, ListingStatus.DRAFT)
    verifier = StubVerifier()
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[asset, None, asset, None]),
        add=Mock(),
        commit=AsyncMock(),
        scalars=AsyncMock(
            side_effect=[
                ScalarRows([wallet]),
                ScalarRows([wallet]),
                ScalarRows([created_listing]),
            ]
        ),
        rollback=AsyncMock(),
    )
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier
    try:
        response = api_client.post(
            "/api/listings",
            json={
                "asset_id": str(asset.id),
                "title": "Rare Gift",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)

    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    assert response.json()["asset"]["id"] == str(asset.id)
    assert response.json()["asset"]["name"] == "Fresh NFT"
    assert verifier.calls == [(asset.item_address, wallet.address)]
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


def test_create_listing_rejects_conflicting_open_listing(api_client, seller) -> None:
    asset = make_verified_asset(seller.id)
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[asset, uuid4()]))
    install_session_override(session)
    try:
        response = api_client.post(
            "/api/listings",
            json={
                "asset_id": str(asset.id),
            },
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 409
    assert "active or reserved" in response.json()["detail"]


def test_create_listing_rejects_stale_owner_and_marks_asset_stale(
    api_client, seller
) -> None:
    asset = make_verified_asset(seller.id)
    wallet = make_verified_wallet(seller.id)
    verifier = StubVerifier(
        VerificationResult(
            VerificationStatus.OWNER_MISMATCH,
            asset.item_address or "",
            owner_address="0:" + "33" * 32,
            expected_owner_address=wallet.address,
        )
    )
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[asset, None, asset]),
        scalars=AsyncMock(return_value=ScalarRows([wallet])),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier
    try:
        response = api_client.post(
            "/api/listings",
            json={
                "asset_id": str(asset.id),
            },
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)

    assert response.status_code == 409
    assert "freshly verified" in response.json()["detail"]
    assert asset.owner_id is None
    assert asset.verification_status is AssetVerificationStatus.STALE
    session.commit.assert_awaited_once()


def test_create_listing_returns_503_when_owner_provider_fails(
    api_client, seller
) -> None:
    asset = make_verified_asset(seller.id)
    wallet = make_verified_wallet(seller.id)
    verifier = StubVerifier(
        VerificationResult(
            VerificationStatus.PROVIDER_UNAVAILABLE,
            asset.item_address or "",
            expected_owner_address=wallet.address,
        )
    )
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[asset, None]),
        scalars=AsyncMock(return_value=ScalarRows([wallet])),
        commit=AsyncMock(),
        add=Mock(),
        rollback=AsyncMock(),
    )
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier
    try:
        response = api_client.post(
            "/api/listings",
            json={
                "asset_id": str(asset.id),
            },
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)

    assert response.status_code == 503
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"asset_id": "not-a-uuid"},
        {"asset_id": str(uuid4()), "price_amount": "1.25"},
        {"asset_id": str(uuid4()), "price_currency": "TON"},
    ],
)
def test_create_listing_rejects_invalid_payloads(api_client, payload) -> None:
    response = api_client.post("/api/listings", json=payload)
    assert response.status_code == 422


def test_publish_listing_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.post(f"/api/listings/{uuid4()}/publish")
    assert response.status_code == 401


def test_edit_listing_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.patch(
            f"/api/listings/{uuid4()}",
            json={"title": "Changed title"},
        )
    assert response.status_code == 401


def test_cancel_listing_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.post(f"/api/listings/{uuid4()}/cancel")
    assert response.status_code == 401


def test_publish_listing_uses_authenticated_seller_and_verified_provider(
    api_client, seller, monkeypatch
) -> None:
    asset = make_verified_asset(seller.id)
    draft = make_listing(seller, asset, ListingStatus.ACTIVE)
    verifier = StubVerifier()
    session = SimpleNamespace(rollback=AsyncMock())
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier
    publish = AsyncMock(return_value=draft)
    monkeypatch.setattr(listings_api, "publish_listing", publish)
    try:
        response = api_client.post(f"/api/listings/{draft.id}/publish")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert publish.await_args.kwargs["seller_id"] == seller.id
    assert publish.await_args.kwargs["verifier"] is verifier


def test_publish_listing_maps_provider_outage_to_503(
    api_client, seller, monkeypatch
) -> None:
    session = SimpleNamespace(rollback=AsyncMock())
    install_session_override(session)
    monkeypatch.setattr(
        listings_api,
        "publish_listing",
        AsyncMock(side_effect=ListingVerificationUnavailable("provider offline")),
    )
    try:
        response = api_client.post(f"/api/listings/{uuid4()}/publish")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 503
    assert response.json()["detail"] == "provider offline"


def test_edit_listing_accepts_only_free_listing_metadata(
    api_client, seller, monkeypatch
) -> None:
    asset = make_verified_asset(seller.id)
    listing = make_listing(seller, asset, ListingStatus.DRAFT)
    session = SimpleNamespace()
    install_session_override(session)
    update = AsyncMock(return_value=listing)
    monkeypatch.setattr(listings_api, "update_listing", update)
    try:
        response = api_client.patch(
            f"/api/listings/{listing.id}",
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 200
    assert update.await_args.kwargs["seller_id"] == seller.id
    assert update.await_args.kwargs["fields_set"] == {
        "title", "description"
    }
    assert update.await_args.kwargs["title"] == "Updated"
    assert update.await_args.kwargs["description"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "active"},
        {"seller_id": str(uuid4())},
        {"owner_id": str(uuid4())},
        {"price_amount": "1.25"},
        {"price_currency": "TON"},
        {},

    ],
)
def test_edit_listing_rejects_unpermitted_or_empty_payloads(api_client, payload) -> None:
    response = api_client.patch(f"/api/listings/{uuid4()}", json=payload)
    assert response.status_code == 422


def test_cancel_listing_hides_another_sellers_listing(
    api_client, monkeypatch
) -> None:
    session = SimpleNamespace()
    install_session_override(session)
    monkeypatch.setattr(
        listings_api,
        "cancel_listing",
        AsyncMock(side_effect=ListingNotFound("Listing not found")),
    )
    try:
        response = api_client.post(f"/api/listings/{uuid4()}/cancel")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 404


def test_cancel_listing_rejects_reserved_listing(api_client, monkeypatch) -> None:
    session = SimpleNamespace()
    install_session_override(session)
    monkeypatch.setattr(
        listings_api,
        "cancel_listing",
        AsyncMock(side_effect=ListingConflict("Only draft or active listings can be cancelled")),
    )
    try:
        response = api_client.post(f"/api/listings/{uuid4()}/cancel")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 409

