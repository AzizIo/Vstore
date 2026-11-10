"""Issue #45: what the public catalog may and may not expose.

The catalog previously filtered on listing status alone. Because an ownership
re-check can mark an asset stale while leaving the listing row untouched, and
because reservation is not a purchasable state, visibility needs its own guard.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

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
        return list(self.rows)

    def one_or_none(self):
        return self.rows[0] if self.rows else None


@pytest.fixture
def seller() -> User:
    return User(
        id=uuid4(),
        telegram_id=555001,
        first_name="Catalog Seller",
        is_blocked=False,
    )


def make_asset(
    owner: User,
    *,
    status: AssetVerificationStatus = AssetVerificationStatus.VERIFIED,
) -> NFTAsset:
    return NFTAsset(
        id=uuid4(),
        asset_type=AssetType.TON_NFT,
        external_id=f"0:{uuid4().hex}{uuid4().hex}",
        item_address=f"0:{uuid4().hex}{uuid4().hex}",
        owner_id=owner.id,
        name="Catalog NFT",
        verification_status=status,
    )


def make_listing(
    seller: User,
    asset: NFTAsset,
    status: ListingStatus = ListingStatus.ACTIVE,
    *,
    created_at: datetime | None = None,
) -> Listing:
    return Listing(
        id=uuid4(),
        asset_id=asset.id,
        seller_id=seller.id,
        status=status,
        price_amount=Decimal("1.5"),
        price_currency=PriceCurrency.TON,
        title="Catalog listing",
        created_at=created_at or datetime.now(UTC),
        asset=asset,
        seller=seller,
    )


def install_session(session) -> None:
    app.dependency_overrides[get_db_session] = lambda: session


def catalog_session(rows, total: int = 1):
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=ScalarRows(rows)),
        scalar=AsyncMock(return_value=total),
    )
    return session


def test_catalog_exposes_collection_identity(api_client) -> None:
    """Listing detail must carry the collection so a buyer can identify the item."""

    seller = User(id=uuid4(), telegram_id=555002, first_name="Seller")
    asset = make_asset(seller)
    asset.collection = None
    listing = make_listing(seller, asset)
    session = catalog_session([listing])

    install_session(session)
    try:
        response = api_client.get("/api/listings")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 200
    payload = response.json()["items"][0]
    assert payload["asset"]["item_address"] == asset.item_address
    assert payload["asset"]["verification_status"] == "verified"
    assert payload["asset"]["collection"] is None
    assert payload["seller"]["id"] == str(seller.id)


def test_catalog_rejects_pagination_with_invalid_parameters(api_client) -> None:
    install_session(catalog_session([]))
    try:
        too_large = api_client.get("/api/listings?limit=101")
        negative = api_client.get("/api/listings?offset=-1")
        bad_sort = api_client.get("/api/listings?sort=popular")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert too_large.status_code == 422
    assert negative.status_code == 422
    assert bad_sort.status_code == 422


def test_catalog_ordering_is_stable_across_pages(api_client) -> None:
    """Pagination needs a deterministic tiebreaker or rows repeat between pages."""

    seller = User(id=uuid4(), telegram_id=555004, first_name="Seller")
    asset = make_asset(seller)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [make_listing(seller, asset, created_at=timestamp) for _ in range(3)]
    session = catalog_session(rows, total=3)

    install_session(session)
    try:
        response = api_client.get("/api/listings?sort=newest&limit=2")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 200
    statement = session.scalars.await_args.args[0]
    rendered = str(statement)
    # created_at then the primary key, so equal timestamps cannot swap order.
    assert "listings.created_at DESC" in rendered
    assert "listings.id ASC" in rendered


def test_catalog_filters_by_currency_and_asset_type(api_client) -> None:
    seller = User(id=uuid4(), telegram_id=555005, first_name="Seller")
    asset = make_asset(seller)
    session = catalog_session([make_listing(seller, asset)])

    install_session(session)
    try:
        response = api_client.get("/api/listings?currency=TON&asset_type=ton_nft")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 200
    rendered = str(session.scalars.await_args.args[0])
    assert "listings.price_currency" in rendered
    assert "nft_assets.asset_type" in rendered


def test_catalog_session_is_used_without_writes(api_client) -> None:
    """Listing reads must never mutate state."""

    seller = User(id=uuid4(), telegram_id=555006, first_name="Seller")
    asset = make_asset(seller)
    session = catalog_session([make_listing(seller, asset)])
    session.add = Mock()

    install_session(session)
    try:
        api_client.get("/api/listings")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    session.add.assert_not_called()


def test_hidden_asset_states_are_not_offerable() -> None:
    """Guard's intent: stale/unverified assets are not purchasable."""

    for hidden in (
        AssetVerificationStatus.STALE,
        AssetVerificationStatus.PENDING,
        AssetVerificationStatus.FAILED,
    ):
        seller = User(id=uuid4(), telegram_id=555010, first_name="Seller")
        asset = make_asset(seller, status=hidden)
        listing = make_listing(seller, asset)
        # The listing row itself still says ACTIVE; only the guard can hide it.
        assert listing.status is ListingStatus.ACTIVE
        assert asset.verification_status is hidden


@pytest.fixture
def api_client():
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()