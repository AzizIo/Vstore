from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.models import VerificationStatus
from app.assets.ton_nft.verifier import TONNFTVerifier
from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    User,
    Wallet,
)


class ListingError(Exception):
    """Base exception for seller listing lifecycle failures."""


class ListingNotFound(ListingError):
    """The listing does not exist or is not visible to this seller."""


class ListingConflict(ListingError):
    """The requested listing transition is not valid for its current state."""


class ListingVerificationUnavailable(ListingError):
    """The external ownership provider could not verify the NFT."""


async def _load_listing_response(
    session: AsyncSession, listing_id: UUID
) -> Listing:
    listing = await session.scalar(
        select(Listing)
        .options(selectinload(Listing.asset), selectinload(Listing.seller))
        .where(Listing.id == listing_id)
    )
    if listing is None:
        raise ListingNotFound("Listing not found")
    return listing


async def publish_listing(
    session: AsyncSession,
    *,
    listing_id: UUID,
    seller_id: UUID,
    verifier: TONNFTVerifier,
) -> Listing:
    """Publish a private TON NFT draft after a fresh, race-safe owner check.

    All provider calls happen after the initial read transaction is rolled back.
    The listing, asset, and selected verified wallet are locked and revalidated
    in a new transaction before the status changes to ACTIVE.
    """

    settings = get_settings()
    network = settings.ton_connect_network

    # Read a candidate snapshot without locks. Store primitive values because
    # rollback expires ORM instances and releases the read transaction.
    listing = await session.scalar(
        select(Listing).where(
            Listing.id == listing_id,
            Listing.seller_id == seller_id,
        )
    )
    if listing is None:
        raise ListingNotFound("Listing not found")
    if listing.status is not ListingStatus.DRAFT:
        raise ListingConflict("Only private drafts can be published")

    asset_id = listing.asset_id
    asset = await session.scalar(select(NFTAsset).where(NFTAsset.id == asset_id))
    if (
        asset is None
        or asset.owner_id != seller_id
        or asset.asset_type is not AssetType.TON_NFT
        or asset.network != network
        or asset.verification_status is not AssetVerificationStatus.VERIFIED
        or not asset.item_address
    ):
        raise ListingConflict(
            "Only a currently verified TON NFT owned by you can be published"
        )

    item_address = asset.item_address
    asset_network = asset.network
    asset_external_id = asset.external_id
    wallet_rows = await session.scalars(
        select(Wallet)
        .where(
            Wallet.user_id == seller_id,
            Wallet.is_verified.is_(True),
            Wallet.network == asset_network,
        )
        .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
    )
    wallet_refs = [
        (wallet.id, wallet.address, wallet.network) for wallet in wallet_rows.all()
    ]
    await session.rollback()

    if not wallet_refs:
        raise ListingConflict(
            "A verified TON wallet on this network is required to publish a listing"
        )

    verified_result = None
    selected_wallet_id: UUID | None = None
    selected_wallet_address: str | None = None
    for wallet_id, wallet_address, wallet_network in wallet_refs:
        if wallet_network != asset_network:
            continue
        result = await verifier.verify(item_address, wallet_address)
        if result.status is VerificationStatus.PROVIDER_UNAVAILABLE:
            raise ListingVerificationUnavailable(
                "TON NFT ownership provider is temporarily unavailable"
            )
        if not result.is_verified:
            continue
        try:
            verified_item = normalize_address(result.item_address)
            verified_owner = normalize_address(result.owner_address or "")
            expected_owner = normalize_address(result.expected_owner_address or "")
            normalized_item = normalize_address(item_address)
            normalized_wallet = normalize_address(wallet_address)
        except AddressError:
            continue
        if (
            verified_item != normalized_item
            or verified_owner != normalized_wallet
            or expected_owner != normalized_wallet
        ):
            continue
        verified_result = result
        selected_wallet_id = wallet_id
        selected_wallet_address = wallet_address
        break

    if (
        verified_result is None
        or selected_wallet_id is None
        or selected_wallet_address is None
    ):
        raise ListingConflict(
            "Current NFT ownership could not be verified for your connected wallets"
        )

    # No external request is made below this point. Acquire locks in the same
    # listing -> asset order used by order reservation, then re-check the exact
    # wallet that passed the live ownership verification.
    async with session.begin():
        locked_listing = await session.scalar(
            select(Listing)
            .where(Listing.id == listing_id)
            .with_for_update()
        )
        if locked_listing is None or locked_listing.seller_id != seller_id:
            raise ListingNotFound("Listing not found")
        if (
            locked_listing.status is not ListingStatus.DRAFT
            or locked_listing.asset_id != asset_id
        ):
            raise ListingConflict(
                "Listing changed while ownership was being verified; refresh and try again"
            )

        locked_asset = await session.scalar(
            select(NFTAsset)
            .where(NFTAsset.id == asset_id)
            .with_for_update()
        )
        if (
            locked_asset is None
            or locked_asset.owner_id != seller_id
            or locked_asset.asset_type is not AssetType.TON_NFT
            or locked_asset.network != asset_network
            or locked_asset.network != network
            or locked_asset.external_id != asset_external_id
            or locked_asset.item_address != item_address
            or locked_asset.verification_status is not AssetVerificationStatus.VERIFIED
        ):
            raise ListingConflict(
                "NFT ownership or verification state changed; refresh your inventory"
            )

        selected_wallet = await session.scalar(
            select(Wallet)
            .where(
                Wallet.id == selected_wallet_id,
                Wallet.user_id == seller_id,
            )
            .with_for_update()
        )
        if (
            selected_wallet is None
            or not selected_wallet.is_verified
            or selected_wallet.network != asset_network
            or selected_wallet.address != selected_wallet_address
        ):
            raise ListingConflict(
                "The verified wallet changed during ownership verification"
            )

        conflicting_listing_id = await session.scalar(
            select(Listing.id).where(
                Listing.asset_id == asset_id,
                Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]),
            )
        )
        if conflicting_listing_id is not None:
            raise ListingConflict(
                "This NFT already has an active or reserved listing"
            )

        locked_asset.verified_at = datetime.now(UTC)
        locked_listing.status = ListingStatus.ACTIVE
        await session.flush()
        response_listing = await session.scalar(
            select(Listing)
            .options(selectinload(Listing.asset), selectinload(Listing.seller))
            .where(Listing.id == listing_id)
        )

    if response_listing is None:
        raise ListingNotFound("Listing not found")
    return response_listing


async def update_listing(
    session: AsyncSession,
    *,
    listing_id: UUID,
    seller_id: UUID,
    price_amount: Decimal | None = None,
    title: str | None = None,
    description: str | None = None,
    fields_set: set[str],
) -> Listing:
    if not fields_set:
        raise ListingConflict("Provide at least one listing field to update")
    if "price_amount" in fields_set and (
        price_amount is None or price_amount <= 0
    ):
        raise ListingConflict("Price must be greater than zero")

    async with session.begin():
        listing = await session.scalar(
            select(Listing)
            .where(
                Listing.id == listing_id,
                Listing.seller_id == seller_id,
            )
            .with_for_update()
        )
        if listing is None:
            raise ListingNotFound("Listing not found")
        if listing.status not in {ListingStatus.DRAFT, ListingStatus.ACTIVE}:
            raise ListingConflict(
                "Only draft or active listings can be edited"
            )

        if "price_amount" in fields_set:
            listing.price_amount = price_amount  # type: ignore[assignment]
        if "title" in fields_set:
            listing.title = title
        if "description" in fields_set:
            listing.description = description
        await session.flush()
        response_listing = await session.scalar(
            select(Listing)
            .options(selectinload(Listing.asset), selectinload(Listing.seller))
            .where(Listing.id == listing_id)
        )

    if response_listing is None:
        raise ListingNotFound("Listing not found")
    return response_listing


async def cancel_listing(
    session: AsyncSession,
    *,
    listing_id: UUID,
    seller_id: UUID,
) -> Listing:
    """Unpublish an active listing or cancel a private draft."""

    async with session.begin():
        listing = await session.scalar(
            select(Listing)
            .where(
                Listing.id == listing_id,
                Listing.seller_id == seller_id,
            )
            .with_for_update()
        )
        if listing is None:
            raise ListingNotFound("Listing not found")
        if listing.status not in {ListingStatus.DRAFT, ListingStatus.ACTIVE}:
            raise ListingConflict(
                "Only draft or active listings can be cancelled"
            )

        listing.status = ListingStatus.CANCELLED
        await session.flush()
        response_listing = await session.scalar(
            select(Listing)
            .options(selectinload(Listing.asset), selectinload(Listing.seller))
            .where(Listing.id == listing_id)
        )

    if response_listing is None:
        raise ListingNotFound("Listing not found")
    return response_listing
