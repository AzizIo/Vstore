from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.api.auth import TelegramAuthRequest
from app.api.listings import ListingCreateRequest

ASSET_ID = "00000000-0000-0000-0000-000000000001"


def test_listing_request_accepts_free_listing_metadata() -> None:
    payload = ListingCreateRequest(
        asset_id=ASSET_ID,
        title="Rare collectible",
        description="A free listing.",
    )
    assert str(payload.asset_id) == ASSET_ID
    assert payload.title == "Rare collectible"
    assert payload.description == "A free listing."


@pytest.mark.parametrize(
    "legacy_price",
    [
        {"price_amount": "1.25"},
        {"price_currency": "TON"},
        {"price_amount": "1.25", "price_currency": "TON"},
    ],
)
def test_listing_request_rejects_legacy_price_fields(legacy_price: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(asset_id=ASSET_ID, **legacy_price)


def test_listing_request_rejects_overlong_description() -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(asset_id=ASSET_ID, description="x" * 4_001)


def test_listing_request_rejects_overlong_title() -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(asset_id=ASSET_ID, title="x" * 201)


def test_listing_request_rejects_invalid_asset_uuid() -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(asset_id="invalid")


@pytest.mark.parametrize("init_data", ["", "x" * 16_385])
def test_telegram_auth_request_validates_init_data_length(init_data: str) -> None:
    with pytest.raises(ValidationError):
        TelegramAuthRequest(init_data=init_data)


def test_telegram_auth_request_accepts_nonempty_payload() -> None:
    assert TelegramAuthRequest(init_data="auth_date=1").init_data == "auth_date=1"


def test_listing_request_accepts_timezone_aware_future_expiration() -> None:
    expires_at = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    payload = ListingCreateRequest(asset_id=ASSET_ID, expires_at=expires_at)
    assert payload.expires_at == expires_at


@pytest.mark.parametrize(
    "expires_at",
    [
        datetime(2030, 1, 1, 12, 0),
        datetime(2020, 1, 1, 12, 0, tzinfo=UTC),
    ],
)
def test_listing_request_rejects_naive_or_past_expiration(expires_at: datetime) -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(asset_id=ASSET_ID, expires_at=expires_at)


def test_listing_request_rejects_client_controlled_owner_fields() -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(
            asset_id=ASSET_ID,
            seller_id="attacker",
            owner_id="attacker",
        )
