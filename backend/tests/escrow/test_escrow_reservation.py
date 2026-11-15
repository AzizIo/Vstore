from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.models import ListingStatus
from app.escrow.reservation import (
    EscrowListingReservationConflict,
    reserve_listing_for_escrow,
)


def test_escrow_reservation_closes_ordinary_orders_listing() -> None:
    listing = SimpleNamespace(status=ListingStatus.ACTIVE)
    intent = SimpleNamespace(status="active")

    reserve_listing_for_escrow(listing, intent)

    assert listing.status is ListingStatus.RESERVED
    assert intent.status == "reserved"


@pytest.mark.parametrize(
    ("listing_status", "intent_status"),
    [
        (ListingStatus.RESERVED, "active"),
        (ListingStatus.SOLD, "active"),
        (ListingStatus.ACTIVE, "reserved"),
        (ListingStatus.ACTIVE, "cancelled"),
    ],
)
def test_escrow_reservation_rejects_stale_or_unavailable_rows(
    listing_status: ListingStatus,
    intent_status: str,
) -> None:
    listing = SimpleNamespace(status=listing_status)
    intent = SimpleNamespace(status=intent_status)

    with pytest.raises(EscrowListingReservationConflict):
        reserve_listing_for_escrow(listing, intent)
