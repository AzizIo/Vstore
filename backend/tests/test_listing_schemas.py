import pytest
from pydantic import ValidationError

from app.api.listings import ListingCreateRequest
from app.db.models import PriceCurrency


def test_listing_request_accepts_positive_price() -> None:
    payload = ListingCreateRequest(
        asset_id="00000000-0000-0000-0000-000000000001",
        price_amount="1.250000001",
        price_currency=PriceCurrency.TON,
        title="Rare collectible",
    )

    assert str(payload.price_amount) == "1.250000001"


@pytest.mark.parametrize("price", ["0", "-1", "0.0000000001"])
def test_listing_request_rejects_invalid_price(price: str) -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(
            asset_id="00000000-0000-0000-0000-000000000001",
            price_amount=price,
            price_currency=PriceCurrency.TON,
        )


def test_listing_request_rejects_overlong_description() -> None:
    with pytest.raises(ValidationError):
        ListingCreateRequest(
            asset_id="00000000-0000-0000-0000-000000000001",
            price_amount="1",
            price_currency=PriceCurrency.TON,
            description="x" * 4_001,
        )
