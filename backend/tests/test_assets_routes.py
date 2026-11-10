from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.assets import _upsert_verified_asset
from app.assets.ton_nft.dependencies import get_ton_nft_verifier
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable
from app.assets.ton_nft.models import (
    NFTInventoryPage,
    NFTItemSnapshot,
    NFTMetadata,
    VerificationResult,
    VerificationStatus,
)
from app.auth.dependencies import get_current_user
from app.db.models import AssetType, AssetVerificationStatus, NFTAsset, User, Wallet
from app.db.session import get_db_session
from app.main import app

ITEM = "0:" + "11" * 32
OTHER_ITEM = "0:" + "33" * 32
OWNER = "0:" + "22" * 32
OTHER_OWNER = "0:" + "44" * 32


class FakeInventoryProvider:
    def __init__(self, page: NFTInventoryPage | None = None, error: Exception | None = None):
        self.page = page or NFTInventoryPage(
            items=(
                NFTItemSnapshot(
                    address=ITEM,
                    initialized=True,
                    index=1,
                    collection_address=None,
                    owner_address=OWNER,
                    metadata=NFTMetadata(name="Candidate name"),
                ),
            ),
            has_more=True,
            next_offset=24,
        )
        self.error = error
        self.calls: list[tuple[str, int, int]] = []

    async def get_items_by_owner(self, owner_address: str, *, limit: int, offset: int):
        self.calls.append((owner_address, limit, offset))
        if self.error is not None:
            raise self.error
        return self.page


class FakeVerifier:
    def __init__(self, provider=None, result=None):
        self.provider = provider or FakeInventoryProvider()
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def verify(self, item_address: str, expected_owner_address: str):
        self.calls.append((item_address, expected_owner_address))
        if self.result is not None:
            return self.result
        candidate = next(
            item for item in self.provider.page.items if item.address == item_address
        )
        if candidate.owner_address != expected_owner_address:
            return VerificationResult(
                VerificationStatus.OWNER_MISMATCH,
                item_address,
                owner_address=candidate.owner_address,
                expected_owner_address=expected_owner_address,
            )
        return VerificationResult(
            VerificationStatus.VERIFIED,
            item_address,
            owner_address=candidate.owner_address,
            collection_address=candidate.collection_address,
            item_index=candidate.index,
            expected_owner_address=expected_owner_address,
            metadata=candidate.metadata,
        )


@pytest.fixture
def owner() -> User:
    return User(
        id=uuid4(),
        telegram_id=123456789,
        username="seller",
        first_name="Seller",
        is_blocked=False,
    )


@pytest.fixture
def verified_wallet(owner: User) -> Wallet:
    return Wallet(
        id=uuid4(),
        user_id=owner.id,
        address=OWNER,
        network="mainnet",
        is_verified=True,
        is_primary=True,
    )


@pytest.fixture
def api_client(owner: User):
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def install_session_override(session) -> None:
    async def override_session():
        yield session

    app.dependency_overrides[get_db_session] = override_session


def make_asset(owner_id, snapshot: NFTItemSnapshot) -> NFTAsset:
    return NFTAsset(
        id=uuid4(),
        asset_type=AssetType.TON_NFT,
        external_id=snapshot.address,
        item_address=snapshot.address,
        owner_id=owner_id,
        name=snapshot.metadata.name,
        description=snapshot.metadata.description,
        image_url=snapshot.metadata.image,
        verification_status=AssetVerificationStatus.VERIFIED,
    )


def test_inventory_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/api/assets/me")
    assert response.status_code == 401


def test_inventory_requires_a_verified_wallet(api_client, owner) -> None:
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    install_session_override(session)
    try:
        response = api_client.get("/api/assets/me")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 409
    assert "verified TON wallet" in response.json()["detail"]


def test_inventory_does_not_disclose_a_foreign_wallet(api_client, owner) -> None:
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    install_session_override(session)
    try:
        response = api_client.get(f"/api/assets/me?wallet_id={uuid4()}")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 404
    assert response.json()["detail"] == "Verified wallet not found"


def test_inventory_returns_only_freshly_verified_items_and_syncs_them(
    api_client, owner, verified_wallet
) -> None:
    candidate = NFTItemSnapshot(
        address=ITEM,
        initialized=True,
        index=3,
        collection_address=None,
        owner_address=OWNER,
        metadata=NFTMetadata(name="Verified item", description="Display only"),
    )
    provider = FakeInventoryProvider(
        NFTInventoryPage(items=(candidate,), has_more=True, next_offset=24)
    )
    verifier = FakeVerifier(provider=provider)
    asset = make_asset(owner.id, candidate)
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[verified_wallet, verified_wallet, asset]),
        scalars=AsyncMock(),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier
    try:
        response = api_client.get("/api/assets/me?limit=24&offset=0")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["id"] == str(asset.id)
    assert body["items"][0]["eligible_for_listing"] is True
    assert body["items"][0]["verification_status"] == "verified"
    assert body["has_more"] is True
    assert body["next_offset"] == 24
    assert provider.calls == [(OWNER, 24, 0)]
    assert verifier.calls == [(ITEM, OWNER)]
    session.commit.assert_awaited_once()


def test_inventory_ignores_client_supplied_owner_address(api_client, verified_wallet) -> None:
    provider = FakeInventoryProvider(NFTInventoryPage(items=(), has_more=False, next_offset=0))
    verifier = FakeVerifier(provider=provider)
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[verified_wallet, verified_wallet]),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier
    try:
        response = api_client.get(f"/api/assets/me?owner_address={OTHER_OWNER}")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)

    assert response.status_code == 200
    assert provider.calls == [(OWNER, 24, 0)]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_inventory_rejects_invalid_pagination(api_client, query) -> None:
    response = api_client.get(f"/api/assets/me?{query}")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_asset_upsert_is_network_scoped_and_skips_open_listings(owner) -> None:
    snapshot = NFTItemSnapshot(
        address=ITEM,
        initialized=True,
        index=0,
        collection_address=None,
        owner_address=OWNER,
        metadata=NFTMetadata(name="NFT"),
    )
    asset = make_asset(owner.id, snapshot)
    session = SimpleNamespace(scalar=AsyncMock(return_value=asset))

    await _upsert_verified_asset(session, owner.id, "testnet", snapshot)

    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "ON CONFLICT (asset_type, network, external_id) DO UPDATE" in sql
    assert "NOT (EXISTS" in sql
    assert compiled.params["network"] == "testnet"


def test_inventory_excludes_owner_mismatch(api_client, owner, verified_wallet) -> None:
    candidate = NFTItemSnapshot(
        address=ITEM,
        initialized=True,
        index=3,
        collection_address=None,
        owner_address=OTHER_OWNER,
        metadata=NFTMetadata(name="Not owned"),
    )
    provider = FakeInventoryProvider(NFTInventoryPage((candidate,), False, 1))
    verifier = FakeVerifier(provider=provider)
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[verified_wallet, verified_wallet]),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier
    try:
        response = api_client.get("/api/assets/me")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["has_more"] is False
    session.commit.assert_awaited_once()


def test_inventory_provider_outage_is_not_reported_as_empty(api_client, verified_wallet) -> None:
    provider = FakeInventoryProvider(error=ProviderUnavailable("timeout"))
    verifier = FakeVerifier(provider=provider)
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=verified_wallet),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier
    try:
        response = api_client.get("/api/assets/me")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
    session.commit.assert_not_awaited()


def test_inventory_rejects_malformed_provider_data(api_client, verified_wallet) -> None:
    verifier = FakeVerifier(
        provider=FakeInventoryProvider(error=InvalidProviderData("malformed"))
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=verified_wallet),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier
    try:
        response = api_client.get("/api/assets/me")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)

    assert response.status_code == 502
    assert "invalid data" in response.json()["detail"]
    session.commit.assert_not_awaited()
