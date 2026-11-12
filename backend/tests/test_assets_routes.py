from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
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
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    ListingStatus,
    NFTAsset,
    Order,
    OrderEvent,
    OrderStatus,
    PriceCurrency,
    TelegramNotificationOutbox,
    User,
    Wallet,
)
from app.db.session import get_db_session
from app.main import app
from app.wallets.redis import get_redis_client

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


class FakeSyncRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, _numkeys: int, key: str, token: str, *args) -> int:
        if self.values.get(key) != token:
            return 0
        if "EXPIRE" in script:
            return 1
        del self.values[key]
        return 1


class PaginatedInventoryProvider:
    def __init__(self, pages: dict[int, NFTInventoryPage], error: Exception | None = None):
        self.pages = pages
        self.error = error
        self.calls: list[tuple[str, int, int]] = []

    async def get_items_by_owner(self, owner_address: str, *, limit: int, offset: int):
        self.calls.append((owner_address, limit, offset))
        if self.error is not None:
            raise self.error
        return self.pages[offset]


class SecondPageUnavailableProvider(PaginatedInventoryProvider):
    async def get_items_by_owner(self, owner_address: str, *, limit: int, offset: int):
        self.calls.append((owner_address, limit, offset))
        if offset > 0:
            raise ProviderUnavailable("DNS lookup failed")
        return self.pages[offset]


class SyncVerifier:
    def __init__(
        self,
        provider: PaginatedInventoryProvider,
        explicit_results: dict[tuple[str, str], VerificationResult] | None = None,
    ) -> None:
        self.provider = provider
        self.items = {
            item.address: item
            for page in provider.pages.values()
            for item in page.items
        }
        self.explicit_results = explicit_results or {}
        self.calls: list[tuple[str, str]] = []

    async def verify(self, item_address: str, expected_owner_address: str):
        self.calls.append((item_address, expected_owner_address))
        explicit = self.explicit_results.get((item_address, expected_owner_address))
        if explicit is not None:
            return explicit
        candidate = self.items[item_address]
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


def _rows(values):
    return SimpleNamespace(all=lambda: values)


def _install_sync_overrides(session, verifier, redis) -> None:
    install_session_override(session)
    app.dependency_overrides[get_ton_nft_verifier] = lambda: verifier

    async def override_redis():
        yield redis

    app.dependency_overrides[get_redis_client] = override_redis


def _inventory_item(address: str, owner: str = OWNER) -> NFTItemSnapshot:
    return NFTItemSnapshot(
        address=address,
        initialized=True,
        index=0,
        collection_address=None,
        owner_address=owner,
        metadata=NFTMetadata(name="Verified collectible"),
    )


def test_inventory_sync_scans_all_pages_and_deduplicates_addresses(
    api_client, owner, verified_wallet
) -> None:
    third_item = "0:" + "55" * 32
    first = _inventory_item(ITEM)
    second = _inventory_item(OTHER_ITEM)
    third = _inventory_item(third_item)
    provider = PaginatedInventoryProvider({
        0: NFTInventoryPage(items=(first, second), has_more=True, next_offset=2),
        2: NFTInventoryPage(items=(first, third), has_more=False, next_offset=4),
    })
    verifier = SyncVerifier(provider)
    redis = FakeSyncRedis()
    persisted = make_asset(owner.id, first)
    persisted.network = "mainnet"
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[
            _rows([verified_wallet]),
            _rows([]),
            _rows([verified_wallet]),
        ]),
        scalar=AsyncMock(return_value=persisted),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    _install_sync_overrides(session, verifier, redis)
    try:
        response = api_client.post("/api/assets/me/sync")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["discovered_count"] == 3
    assert body["verified_count"] == 3
    assert body["stale_count"] == 0
    assert body["synced_at"]
    assert [call[2] for call in provider.calls] == [0, 2]
    assert len(verifier.calls) == 3
    session.commit.assert_awaited_once()
    assert redis.values == {}


def test_inventory_sync_provider_outage_does_not_mutate_assets(
    api_client, verified_wallet, owner
) -> None:
    provider = PaginatedInventoryProvider({}, error=ProviderUnavailable("timeout"))
    verifier = SyncVerifier(provider)
    redis = FakeSyncRedis()
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_rows([verified_wallet]), _rows([])]),
        scalar=AsyncMock(),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    _install_sync_overrides(session, verifier, redis)
    try:
        response = api_client.post("/api/assets/me/sync")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 503
    session.commit.assert_not_awaited()
    assert redis.values == {}


def test_inventory_sync_marks_confirmed_transferred_away_asset_stale_and_closes_listing(
    api_client, owner, verified_wallet
) -> None:
    provider = PaginatedInventoryProvider({
        0: NFTInventoryPage(items=(), has_more=False, next_offset=0)
    })
    mismatch = VerificationResult(
        VerificationStatus.OWNER_MISMATCH,
        ITEM,
        owner_address=OTHER_OWNER,
        expected_owner_address=OWNER,
    )
    verifier = SyncVerifier(provider, {(ITEM, OWNER): mismatch})
    redis = FakeSyncRedis()
    asset = NFTAsset(
        id=uuid4(),
        asset_type=AssetType.TON_NFT,
        network="mainnet",
        external_id=ITEM,
        item_address=ITEM,
        owner_id=owner.id,
        name="Old name",
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    listing = SimpleNamespace(
        id=uuid4(),
        asset_id=asset.id,
        status=ListingStatus.ACTIVE,
    )
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[
            _rows([verified_wallet]),
            _rows([asset]),
            _rows([verified_wallet]),
            _rows([listing]),
            _rows([]),
        ]),
        scalar=AsyncMock(return_value=asset),
        rollback=AsyncMock(),
        commit=AsyncMock(),
        flush=AsyncMock(),
        add=Mock(),
    )
    _install_sync_overrides(session, verifier, redis)
    try:
        response = api_client.post("/api/assets/me/sync")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200, response.text
    assert response.json()["stale_count"] == 1
    assert response.json()["cancelled_listing_count"] == 1
    assert asset.verification_status is AssetVerificationStatus.STALE
    assert listing.status is ListingStatus.EXPIRED
    session.commit.assert_awaited_once()


def test_inventory_sync_lock_prevents_concurrent_sync(api_client, owner, verified_wallet) -> None:
    provider = PaginatedInventoryProvider({
        0: NFTInventoryPage(items=(), has_more=False, next_offset=0)
    })
    verifier = SyncVerifier(provider)
    redis = FakeSyncRedis()
    redis.values[f"nft-inventory:sync:{owner.id}:mainnet"] = "another-request"
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_rows([verified_wallet]), _rows([])]),
        scalar=AsyncMock(),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    _install_sync_overrides(session, verifier, redis)
    try:
        response = api_client.post("/api/assets/me/sync")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 409
    assert provider.calls == []
    session.commit.assert_not_awaited()


def test_inventory_sync_is_idempotent_for_the_same_owned_item(
    api_client, owner, verified_wallet
) -> None:
    candidate = _inventory_item(ITEM)
    provider = PaginatedInventoryProvider({
        0: NFTInventoryPage(items=(candidate,), has_more=False, next_offset=1)
    })
    verifier = SyncVerifier(provider)
    redis = FakeSyncRedis()
    persisted = make_asset(owner.id, candidate)
    persisted.network = "mainnet"

    first_session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[
            _rows([verified_wallet]),
            _rows([]),
            _rows([verified_wallet]),
        ]),
        scalar=AsyncMock(return_value=persisted),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    _install_sync_overrides(first_session, verifier, redis)
    try:
        first = api_client.post("/api/assets/me/sync")
        assert first.status_code == 200, first.text

        second_session = SimpleNamespace(
            scalars=AsyncMock(side_effect=[
                _rows([verified_wallet]),
                _rows([persisted]),
                _rows([verified_wallet]),
            ]),
            scalar=AsyncMock(return_value=persisted),
            rollback=AsyncMock(),
            commit=AsyncMock(),
        )
        install_session_override(second_session)
        second = api_client.post("/api/assets/me/sync")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert second.status_code == 200, second.text
    assert first.json()["verified_count"] == 1
    assert second.json()["verified_count"] == 1
    assert second.json()["stale_count"] == 0
    assert len(verifier.calls) == 2
    second_session.commit.assert_awaited_once()

def test_inventory_sync_preserves_asset_verified_in_another_user_wallet(
    api_client, owner, verified_wallet
) -> None:
    secondary_wallet = Wallet(
        id=uuid4(),
        user_id=owner.id,
        address=OTHER_OWNER,
        network="mainnet",
        is_verified=True,
        is_primary=False,
    )
    snapshot = _inventory_item(ITEM, owner=OTHER_OWNER)
    asset = make_asset(owner.id, snapshot)
    asset.network = "mainnet"
    provider = PaginatedInventoryProvider({
        0: NFTInventoryPage(items=(), has_more=False, next_offset=0)
    })
    mismatch = VerificationResult(
        VerificationStatus.OWNER_MISMATCH,
        ITEM,
        owner_address=OTHER_OWNER,
        expected_owner_address=OWNER,
    )
    verified_by_secondary = VerificationResult(
        VerificationStatus.VERIFIED,
        ITEM,
        owner_address=OTHER_OWNER,
        expected_owner_address=OTHER_OWNER,
        metadata=snapshot.metadata,
    )
    verifier = SyncVerifier(
        provider,
        {
            (ITEM, OWNER): mismatch,
            (ITEM, OTHER_OWNER): verified_by_secondary,
        },
    )
    redis = FakeSyncRedis()
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[
            _rows([verified_wallet, secondary_wallet]),
            _rows([asset]),
            _rows([verified_wallet, secondary_wallet]),
        ]),
        scalar=AsyncMock(return_value=asset),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    _install_sync_overrides(session, verifier, redis)
    try:
        response = api_client.post("/api/assets/me/sync")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verified_count"] == 1
    assert body["stale_count"] == 0
    assert body["cancelled_listing_count"] == 0
    assert asset.verification_status is AssetVerificationStatus.VERIFIED
    assert verifier.calls == [(ITEM, OWNER), (ITEM, OTHER_OWNER)]
    session.commit.assert_awaited_once()

def test_inventory_sync_cancels_reserved_order_when_transfer_away_is_confirmed(
    api_client, owner, verified_wallet
) -> None:
    """A transferred NFT must not become available after a buyer reserved it."""
    provider = PaginatedInventoryProvider({
        0: NFTInventoryPage(items=(), has_more=False, next_offset=0)
    })
    mismatch = VerificationResult(
        VerificationStatus.OWNER_MISMATCH,
        ITEM,
        owner_address=OTHER_OWNER,
        expected_owner_address=OWNER,
    )
    verifier = SyncVerifier(provider, {(ITEM, OWNER): mismatch})
    redis = FakeSyncRedis()
    asset = NFTAsset(
        id=uuid4(),
        asset_type=AssetType.TON_NFT,
        network="mainnet",
        external_id=ITEM,
        item_address=ITEM,
        owner_id=owner.id,
        name="Reserved NFT",
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    listing = SimpleNamespace(
        id=uuid4(),
        asset_id=asset.id,
        status=ListingStatus.RESERVED,
    )
    buyer = User(
        id=uuid4(),
        telegram_id=987654321,
        username="buyer",
        first_name="Buyer",
        is_blocked=False,
    )
    order = Order(
        id=uuid4(),
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=owner.id,
        idempotency_key="reserved-order-test",
        status=OrderStatus.RESERVED,
        price_amount=Decimal("2.5"),
        price_currency=PriceCurrency.TON,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[
            _rows([verified_wallet]),
            _rows([asset]),
            _rows([verified_wallet]),
            _rows([listing]),
            _rows([order]),
            _rows([buyer, owner]),
        ]),
        scalar=AsyncMock(return_value=asset),
        rollback=AsyncMock(),
        commit=AsyncMock(),
        flush=AsyncMock(),
        add=Mock(),
    )
    _install_sync_overrides(session, verifier, redis)
    try:
        response = api_client.post("/api/assets/me/sync")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200, response.text
    assert response.json()["stale_count"] == 1
    assert response.json()["cancelled_listing_count"] == 1
    assert asset.verification_status is AssetVerificationStatus.STALE
    assert listing.status is ListingStatus.EXPIRED
    assert order.status is OrderStatus.CANCELLED
    added = [call.args[0] for call in session.add.call_args_list]
    assert any(isinstance(item, OrderEvent) for item in added)
    outbox = [item for item in added if isinstance(item, TelegramNotificationOutbox)]
    assert {item.recipient_user_id for item in outbox} == {buyer.id, owner.id}
    assert {item.recipient_role for item in outbox} == {"buyer", "seller"}
    session.commit.assert_awaited_once()

def test_inventory_sync_dns_outage_after_a_verified_page_commits_nothing(
    api_client, owner, verified_wallet
) -> None:
    candidate = _inventory_item(ITEM)
    provider = SecondPageUnavailableProvider({
        0: NFTInventoryPage(items=(candidate,), has_more=True, next_offset=1),
    })
    verifier = SyncVerifier(provider)
    redis = FakeSyncRedis()
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[
            _rows([verified_wallet]),
            _rows([]),
        ]),
        scalar=AsyncMock(),
        rollback=AsyncMock(),
        commit=AsyncMock(),
        flush=AsyncMock(),
        add=Mock(),
    )
    _install_sync_overrides(session, verifier, redis)
    try:
        response = api_client.post("/api/assets/me/sync")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
    assert [call[2] for call in provider.calls] == [0, 1]
    assert verifier.calls == [(ITEM, OWNER)]
    session.commit.assert_not_awaited()
    session.add.assert_not_called()
    assert redis.values == {}


def test_inventory_sync_provider_outage_during_stale_recheck_keeps_existing_state(
    api_client, owner, verified_wallet
) -> None:
    """A successful empty scan is not enough to mark old assets as transferred."""
    provider = PaginatedInventoryProvider({
        0: NFTInventoryPage(items=(), has_more=False, next_offset=0)
    })
    unavailable = VerificationResult(
        VerificationStatus.PROVIDER_UNAVAILABLE,
        ITEM,
        expected_owner_address=OWNER,
    )
    verifier = SyncVerifier(provider, {(ITEM, OWNER): unavailable})
    redis = FakeSyncRedis()
    asset = NFTAsset(
        id=uuid4(),
        asset_type=AssetType.TON_NFT,
        network="mainnet",
        external_id=ITEM,
        item_address=ITEM,
        owner_id=owner.id,
        name="Existing NFT",
        verification_status=AssetVerificationStatus.VERIFIED,
    )
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=[
            _rows([verified_wallet]),
            _rows([asset]),
        ]),
        scalar=AsyncMock(),
        rollback=AsyncMock(),
        commit=AsyncMock(),
        flush=AsyncMock(),
        add=Mock(),
    )
    _install_sync_overrides(session, verifier, redis)
    try:
        response = api_client.post("/api/assets/me/sync")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ton_nft_verifier, None)
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 503
    assert asset.verification_status is AssetVerificationStatus.VERIFIED
    session.commit.assert_not_awaited()
    assert redis.values == {}
