"""Shared listing reservation guard for the isolated escrow path."""

from __future__ import annotations

from app.db.models import Listing, ListingStatus
from app.escrow.models import EscrowListingIntent


class EscrowListingReservationConflict(RuntimeError):
    """The marketplace listing is no longer available for an escrow reservation."""


def reserve_listing_for_escrow(
    listing: Listing,
    intent: EscrowListingIntent,
) -> None:
    """Reserve both projections while the caller holds the listing row lock.

    Ordinary Orders uses the same Listing row and row lock. Updating only the
    escrow intent would leave Listing.status='active' and permit a parallel
    marketplace order for the same NFT.
    """
    if listing.status is not ListingStatus.ACTIVE:
        raise EscrowListingReservationConflict("Marketplace listing is not active")
    if intent.status not in {"intent_only", "active"}:
        raise EscrowListingReservationConflict("Escrow listing intent is not available")
    listing.status = ListingStatus.RESERVED
    intent.status = "reserved"
