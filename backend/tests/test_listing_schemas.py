import pytest
from pydantic import ValidationError

from app.api.auth import TelegramAuthRequest
from app.api.listings import ListingCreateRequest
from app.db.models import PriceCurrency


ASSET_ID = "00000000-0000-0000-0000-000000000001"


def test_listing_request_accepts_positive_price() -> None:
    payload = ListingCreateRequest(
        asset_id=ASSET_ID,
        price_amount="1.250000001",
        price_currency=PriceCurrency.TON,
        title="Rare collectible",
    )
    assert str(payload.price_amount) == "1.250000001"


@pytest.mark.parametrize("price", ["0", "-1", "0.0000000001"])
def test_listing_request_rejects_invalid_price(price: str) -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(asset_id=ASSET_ID, price_amount=price, price_currency=PriceCurrency.TON)


@pytest.mark.parametrize("price", ["1e30", "1234567890123456.1234567890"])
def test_listing_request_rejects_precision_overflow(price: str) -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(asset_id=ASSET_ID, price_amount=price, price_currency=PriceCurrency.TON)


def test_listing_request_rejects_overlong_description() -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(
            asset_id=ASSET_ID,
            price_amount="1",
            price_currency=PriceCurrency.TON,
            description="x" * 4_001,
        )


def test_listing_request_rejects_overlong_title() -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(
            asset_id=ASSET_ID,
            price_amount="1",
            price_currency=PriceCurrency.TON,
            title="x" * 201,
        )


def test_listing_request_rejects_invalid_asset_uuid() -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(asset_id="invalid", price_amount="1", price_currency=PriceCurrency.TON)


@pytest.mark.parametrize("init_data", ["", "x" * 16_385])
def test_telegram_auth_request_validates_init_data_length(init_data: str) -> None:
    with pytest.raises(ValidationError):
        TelegramAuthRequest(init_data=init_data)


def test_telegram_auth_request_accepts_nonempty_payload() -> None:
    assert TelegramAuthRequest(init_data="auth_date=1").init_data == "auth_date=1"
