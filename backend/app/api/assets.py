from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.dependencies import get_ton_nft_verifier
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable
from app.assets.ton_nft.models import NFTItemSnapshot, VerificationStatus
from app.assets.ton_nft.verifier import TONNFTVerifier
from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    NFTCollection,
    User,
    Wallet,
)
from app.db.session import get_db_session

router = APIRouter(prefix="/assets", tags=["assets"])


class InventoryItemResponse(BaseModel):
    id: UUID
    asset_type: AssetType
    external_id: str
    item_address: str
    name: str | None
    description: str | None
    image_url: str | None
    verification_status: AssetVerificationStatus
    eligible_for_listing: bool


class InventoryPageResponse(BaseModel):
    items: list[InventoryItemResponse]
    wallet_id: UUID
    limit: int
    offset: int
    next_offset: int
    has_more: bool


def _item_metadata(snapshot: NFTItemSnapshot) -> dict[str, object] | None:
    if not snapshot.metadata.attributes:
        return None
    return {"attributes": list(snapshot.metadata.attributes)}


async def _upsert_collection(
    session: AsyncSession, network: str, address: str | None
) -> UUID | None:
    if address is None:
        return None
    statement = (
        pg_insert(NFTCollection)
        .values(network=network, address=address)
        .on_conflict_do_nothing(index_elements=["network", "address"])
        .returning(NFTCollection.id)
    )
    collection_id = await session.scalar(statement)
    if collection_id is not None:
        return collection_id
    return await session.scalar(
        select(NFTCollection.id).where(
            NFTCollection.network == network,
            NFTCollection.address == address,
        )
    )


async def _upsert_verified_asset(
    session: AsyncSession,
    user_id: UUID,
    network: str,
    snapshot: NFTItemSnapshot,
) -> NFTAsset | None:
    collection_id = await _upsert_collection(session, network, snapshot.collection_address)
    now = datetime.now(UTC)
    open_listing_exists = (
        select(Listing.id)
        .where(
            Listing.asset_id == NFTAsset.id,
            Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]),
        )
        .exists()
    )
    statement = (
        pg_insert(NFTAsset)
        .values(
            asset_type=AssetType.TON_NFT,
            network=network,
            external_id=snapshot.address,
            item_address=snapshot.address,
            collection_id=collection_id,
            owner_id=user_id,
            name=snapshot.metadata.name,
            description=snapshot.metadata.description,
            image_url=snapshot.metadata.image,
            metadata_json=_item_metadata(snapshot),
            verification_status=AssetVerificationStatus.VERIFIED,
            verified_at=now,
        )
        .on_conflict_do_update(
            index_elements=["asset_type", "network", "external_id"],
            set_={
                "item_address": snapshot.address,
                "collection_id": collection_id,
                "owner_id": user_id,
                "name": snapshot.metadata.name,
                "description": snapshot.metadata.description,
                "image_url": snapshot.metadata.image,
                "metadata": _item_metadata(snapshot),
                "verification_status": AssetVerificationStatus.VERIFIED.value,
                "verified_at": now,
                "updated_at": now,
            },
            where=~open_listing_exists,
        )
        .returning(NFTAsset)
    )
    return await session.scalar(statement)


@router.get("/me", response_model=InventoryPageResponse)
async def get_my_verified_inventory(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    verifier: Annotated[TONNFTVerifier, Depends(get_ton_nft_verifier)],
    wallet_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InventoryPageResponse:
    settings = get_settings()
    user_id = user.id
    wallet_conditions = (
        Wallet.user_id == user_id,
        Wallet.is_verified.is_(True),
        Wallet.network == settings.ton_connect_network,
    )
    if wallet_id is None:
        wallet = await session.scalar(
            select(Wallet)
            .where(*wallet_conditions)
            .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
            .limit(1)
        )
        if wallet is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A verified TON wallet is required to discover NFT inventory",
            )
    else:
        wallet = await session.scalar(
            select(Wallet).where(Wallet.id == wallet_id, *wallet_conditions)
        )
        if wallet is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verified wallet not found",
            )

    selected_wallet_id = wallet.id
    try:
        owner_address = normalize_address(wallet.address)
    except AddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The verified wallet address is not supported for TON NFT inventory",
        ) from exc
    if not owner_address.startswith("0:"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The verified wallet workchain is not supported for TON NFT inventory",
        )

    # Do not keep a database transaction open while calling the external indexer.
    await session.rollback()
    try:
        provider_page = await verifier.provider.get_items_by_owner(
            owner_address,
            limit=limit,
            offset=offset,
        )
    except ProviderUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TON NFT inventory provider is temporarily unavailable",
        ) from exc
    except InvalidProviderData as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TON NFT inventory provider returned invalid data",
        ) from exc

    verified_items: list[NFTItemSnapshot] = []
    seen_addresses: set[str] = set()
    for candidate in provider_page.items:
        if candidate.address in seen_addresses:
            continue
        seen_addresses.add(candidate.address)
        result = await verifier.verify(candidate.address, owner_address)
        if result.status is VerificationStatus.PROVIDER_UNAVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TON NFT ownership provider is temporarily unavailable",
            )
        if result.is_verified:
            if result.metadata != candidate.metadata:
                candidate = NFTItemSnapshot(
                    address=result.item_address,
                    initialized=True,
                    index=result.item_index or 0,
                    collection_address=result.collection_address,
                    owner_address=result.owner_address or owner_address,
                    metadata=result.metadata,
                )
            verified_items.append(candidate)

    # Lock and re-check the selected wallet before persisting a sync result.
    current_wallet = await session.scalar(
        select(Wallet)
        .where(
            Wallet.id == selected_wallet_id,
            *wallet_conditions,
        )
        .with_for_update()
    )
    if current_wallet is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verified wallet not found",
        )

    persisted: list[NFTAsset] = []
    try:
        for item in verified_items:
            asset = await _upsert_verified_asset(
                session,
                user_id,
                current_wallet.network,
                item,
            )
            if asset is not None:
                persisted.append(asset)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return InventoryPageResponse(
        items=[
            InventoryItemResponse(
                id=asset.id,
                asset_type=asset.asset_type,
                external_id=asset.external_id,
                item_address=asset.item_address or asset.external_id,
                name=asset.name,
                description=asset.description,
                image_url=asset.image_url,
                verification_status=asset.verification_status,
                eligible_for_listing=True,
            )
            for asset in persisted
        ],
        wallet_id=selected_wallet_id,
        limit=limit,
        offset=offset,
        next_offset=provider_page.next_offset,
        has_more=provider_page.has_more,
    )
