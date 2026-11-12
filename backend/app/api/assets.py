from __future__ import annotations

import secrets
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.dependencies import get_ton_nft_verifier
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable
from app.assets.ton_nft.models import NFTItemSnapshot, NFTMetadata, VerificationStatus
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
from app.orders.service import _invalidate_lost_ownership
from app.wallets.redis import get_redis_client

router = APIRouter(prefix="/assets", tags=["assets"])

_SYNC_LOCK_TTL_SECONDS = 900
_MAX_SYNC_ITEMS = 5000
_SYNC_PAGE_SIZE = 100
_SYNC_LOCK_PREFIX = "nft-inventory:sync:"
_RENEW_SYNC_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("EXPIRE", KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_SYNC_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""


class InventoryItemResponse(BaseModel):
    id: UUID
    asset_type: AssetType
    external_id: str
    item_address: str
    name: str | None
    description: str | None
    image_url: str | None
    collection_address: str | None
    verification_status: AssetVerificationStatus
    eligible_for_listing: bool


class InventoryPageResponse(BaseModel):
    items: list[InventoryItemResponse]
    wallet_id: UUID
    limit: int
    offset: int
    next_offset: int
    has_more: bool


class InventorySyncResponse(BaseModel):
    wallet_id: UUID
    synced_at: str
    discovered_count: int
    verified_count: int
    stale_count: int
    invalid_count: int
    unsupported_count: int
    cancelled_listing_count: int



def _merge_metadata(primary: NFTMetadata, fallback: NFTMetadata) -> NFTMetadata:
    """Prefer exact-item metadata while retaining page metadata if a field is absent."""
    return NFTMetadata(
        name=primary.name or fallback.name,
        description=primary.description or fallback.description,
        image=primary.image or fallback.image,
        attributes=primary.attributes or fallback.attributes,
    )


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


def _open_listing_exists() -> Exists:
    """Keep the conflict target out of the subquery FROM clause."""
    target_asset_id = literal_column(
        f"{NFTAsset.__tablename__}.id",
        type_=NFTAsset.id.type,
    )
    return (
        select(Listing.id)
        .select_from(Listing)
        .where(
            Listing.asset_id == target_asset_id,
            Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]),
        )
        .exists()
    )


async def _upsert_verified_asset(
    session: AsyncSession,
    user_id: UUID,
    network: str,
    snapshot: NFTItemSnapshot,
) -> NFTAsset | None:
    collection_id = await _upsert_collection(session, network, snapshot.collection_address)
    now = datetime.now(UTC)
    open_listing_exists = _open_listing_exists()
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




async def _scan_wallet_inventory(
    verifier: TONNFTVerifier,
    owner_address: str,
    *,
    redis: Redis,
    lock_key: str,
    lock_token: str,
) -> tuple[dict[str, NFTItemSnapshot], int, int, int]:
    """Fetch every provider page and re-verify every unique item before returning."""
    candidates: dict[str, NFTItemSnapshot] = {}
    seen_addresses: set[str] = set()
    invalid_count = 0
    unsupported_count = 0
    scanned_rows = 0
    offset = 0
    visited_offsets: set[int] = set()

    while True:
        if offset in visited_offsets:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="TON NFT inventory provider returned a repeated pagination cursor",
            )
        visited_offsets.add(offset)
        try:
            page = await verifier.provider.get_items_by_owner(
                owner_address, limit=_SYNC_PAGE_SIZE, offset=offset
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

        if page.next_offset != offset + len(page.items):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="TON NFT inventory provider returned an inconsistent pagination cursor",
            )
        if page.has_more and not page.items:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="TON NFT inventory provider returned an empty non-final page",
            )

        for candidate_index, candidate in enumerate(page.items):
            if candidate_index % 10 == 0:
                await _renew_sync_lock(redis, lock_key, lock_token)
            if scanned_rows >= _MAX_SYNC_ITEMS:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Inventory is too large for one sync; no changes were saved",
                )
            scanned_rows += 1
            if candidate.address in seen_addresses:
                continue
            if len(seen_addresses) >= _MAX_SYNC_ITEMS:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Inventory is too large for one sync; no changes were saved",
                )
            seen_addresses.add(candidate.address)
            result = await verifier.verify(candidate.address, owner_address)
            if result.status is VerificationStatus.PROVIDER_UNAVAILABLE:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TON NFT ownership provider is temporarily unavailable",
                )
            if result.is_verified:
                candidates[candidate.address] = NFTItemSnapshot(
                    address=result.item_address,
                    initialized=True,
                    index=result.item_index if result.item_index is not None else candidate.index,
                    collection_address=result.collection_address,
                    owner_address=result.owner_address or owner_address,
                    metadata=_merge_metadata(result.metadata, candidate.metadata),
                )
            elif result.status is VerificationStatus.UNSUPPORTED:
                unsupported_count += 1
            else:
                invalid_count += 1

        if not page.has_more:
            break
        if page.next_offset <= offset:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="TON NFT inventory provider did not advance the pagination cursor",
            )
        offset = page.next_offset

    return candidates, len(seen_addresses), invalid_count, unsupported_count


async def _renew_sync_lock(redis: Redis, key: str, token: str) -> None:
    try:
        renewed = await cast(
            Awaitable[int],
            redis.eval(
                _RENEW_SYNC_LOCK_SCRIPT,
                1,
                key,
                token,
                _SYNC_LOCK_TTL_SECONDS,
            ),
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inventory sync lock is unavailable",
        ) from exc
    if not renewed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inventory sync lock expired; retry the sync",
        )


def _wallet_address_or_error(wallet: Wallet) -> str:
    try:
        address = normalize_address(wallet.address)
    except AddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A verified wallet address is not supported for TON NFT inventory",
        ) from exc
    if not address.startswith("0:"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The verified wallet workchain is not supported for TON NFT inventory",
        )
    return address


@router.post("/me/sync", response_model=InventorySyncResponse)
async def sync_my_verified_inventory(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    verifier: Annotated[TONNFTVerifier, Depends(get_ton_nft_verifier)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    wallet_id: UUID | None = None,
) -> InventorySyncResponse:
    """Full sync; provider failure never turns an incomplete scan into a successful one."""
    settings = get_settings()
    network = settings.ton_connect_network
    user_id = user.id
    wallet_conditions = (
        Wallet.user_id == user_id,
        Wallet.is_verified.is_(True),
        Wallet.network == network,
    )

    try:
        wallets = list(
            (
                await session.scalars(
                    select(Wallet).where(*wallet_conditions).order_by(
                        Wallet.is_primary.desc(), Wallet.created_at.desc()
                    )
                )
            ).all()
        )
    except Exception:
        await session.rollback()
        raise
    if not wallets:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A verified TON wallet is required to sync NFT inventory",
        )

    selected_wallet = next(
        (wallet for wallet in wallets if wallet.id == wallet_id), None
    ) if wallet_id is not None else wallets[0]
    if selected_wallet is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verified wallet not found",
        )

    wallet_snapshot = tuple((wallet.id, wallet.address) for wallet in wallets)
    selected_wallet_id = selected_wallet.id
    selected_owner_address = _wallet_address_or_error(selected_wallet)
    other_wallet_addresses = {
        _wallet_address_or_error(wallet)
        for wallet in wallets
        if wallet.id != selected_wallet_id
    }

    existing_assets = list(
        (
            await session.scalars(
                select(NFTAsset).where(
                    NFTAsset.owner_id == user_id,
                    NFTAsset.network == network,
                    NFTAsset.asset_type == AssetType.TON_NFT,
                    NFTAsset.verification_status == AssetVerificationStatus.VERIFIED,
                )
            )
        ).all()
    )
    # Store primitives before ending the read transaction and calling the provider.
    existing_snapshot = [
        (asset.id, asset.item_address or asset.external_id)
        for asset in existing_assets
    ]
    await session.rollback()

    lock_key = f"{_SYNC_LOCK_PREFIX}{user_id}:{network}"
    lock_token = secrets.token_urlsafe(32)
    try:
        acquired = await redis.set(
            lock_key, lock_token, ex=_SYNC_LOCK_TTL_SECONDS, nx=True
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inventory sync lock is unavailable",
        ) from exc
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An NFT inventory sync is already running for this account",
        )

    try:
        (
            discovered,
            discovered_count,
            invalid_count,
            unsupported_count,
        ) = await _scan_wallet_inventory(
            verifier,
            selected_owner_address,
            redis=redis,
            lock_key=lock_key,
            lock_token=lock_token,
        )
        # Existing assets can belong to another verified wallet. Never mark them
        # transferred away until every wallet owned by this account was checked.
        verified_elsewhere: dict[str, NFTItemSnapshot] = {}
        stale_candidates: list[tuple[UUID, str, bool]] = []
        existing_id_by_address = {
            address: asset_id for asset_id, address in existing_snapshot
        }
        recheck_addresses = sorted(
            {
                address
                for _, address in existing_snapshot
                if address not in discovered
            }
        )
        if len(recheck_addresses) > _MAX_SYNC_ITEMS:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Stored inventory is too large for one sync; no changes were saved",
            )
        for recheck_index, item_address in enumerate(recheck_addresses):
            if recheck_index % 10 == 0:
                await _renew_sync_lock(redis, lock_key, lock_token)
            if item_address in discovered:
                continue
            result_for_selected = await verifier.verify(
                item_address, selected_owner_address
            )
            if result_for_selected.status is VerificationStatus.PROVIDER_UNAVAILABLE:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TON NFT ownership provider is temporarily unavailable",
                )
            if result_for_selected.is_verified:
                discovered[item_address] = NFTItemSnapshot(
                    address=result_for_selected.item_address,
                    initialized=True,
                    index=result_for_selected.item_index or 0,
                    collection_address=result_for_selected.collection_address,
                    owner_address=result_for_selected.owner_address or selected_owner_address,
                    metadata=result_for_selected.metadata,
                )
                continue

            verified_by_other_wallet = False
            conclusive_mismatch = (
                result_for_selected.status is VerificationStatus.OWNER_MISMATCH
            )
            for other_address in sorted(other_wallet_addresses):
                other_result = await verifier.verify(item_address, other_address)
                if other_result.status is VerificationStatus.PROVIDER_UNAVAILABLE:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="TON NFT ownership provider is temporarily unavailable",
                    )
                if other_result.is_verified:
                    verified_by_other_wallet = True
                    verified_elsewhere[item_address] = NFTItemSnapshot(
                        address=other_result.item_address,
                        initialized=True,
                        index=other_result.item_index or 0,
                        collection_address=other_result.collection_address,
                        owner_address=other_result.owner_address or other_address,
                        metadata=other_result.metadata,
                    )
                    break
                conclusive_mismatch = conclusive_mismatch and (
                    other_result.status is VerificationStatus.OWNER_MISMATCH
                )
            if not verified_by_other_wallet:
                stale_candidates.append(
                    (
                        existing_id_by_address[item_address],
                        item_address,
                        conclusive_mismatch,
                    )
                )

        # Recheck that the exact set of verified wallets did not change while the
        # external scan ran. This prevents stale decisions based on an old wallet set.
        await _renew_sync_lock(redis, lock_key, lock_token)
        current_wallets = list(
            (
                await session.scalars(
                    select(Wallet)
                    .where(*wallet_conditions)
                    .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
                    .with_for_update()
                )
            ).all()
        )
        if tuple((wallet.id, wallet.address) for wallet in current_wallets) != wallet_snapshot:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Verified wallets changed during sync; retry to refresh inventory",
            )
        current_selected = next(
            (wallet for wallet in current_wallets if wallet.id == selected_wallet_id), None
        )
        if current_selected is None:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Selected wallet changed during sync",
            )

        now = datetime.now(UTC)
        stale_count = 0
        cancelled_listing_count = 0
        try:
            snapshots_to_upsert = {**verified_elsewhere, **discovered}
            for upsert_index, snapshot in enumerate(snapshots_to_upsert.values()):
                if upsert_index % 25 == 0:
                    await _renew_sync_lock(redis, lock_key, lock_token)
                await _upsert_verified_asset(session, user_id, network, snapshot)

            for stale_index, (
                asset_id,
                _item_address,
                conclusive_loss,
            ) in enumerate(stale_candidates):
                if stale_index % 25 == 0:
                    await _renew_sync_lock(redis, lock_key, lock_token)
                open_listings = list(
                    (
                        await session.scalars(
                            select(Listing)
                            .where(
                                Listing.asset_id == asset_id,
                                Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]),
                            )
                            .order_by(Listing.id)
                            .with_for_update()
                        )
                    ).all()
                )
                # Match the order service lock order: listings before asset.
                asset = await session.scalar(
                    select(NFTAsset).where(NFTAsset.id == asset_id).with_for_update()
                )
                if asset is None or asset.owner_id != user_id or asset.network != network:
                    continue
                changed = asset.verification_status is not AssetVerificationStatus.STALE
                asset.verification_status = AssetVerificationStatus.STALE
                stale_count += int(changed)
                if conclusive_loss:
                    for listing in open_listings:
                        await _invalidate_lost_ownership(
                            session,
                            listing=listing,
                            asset=asset,
                            current_time=now,
                        )
                        cancelled_listing_count += 1
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        return InventorySyncResponse(
            wallet_id=selected_wallet_id,
            synced_at=now.isoformat(),
            discovered_count=discovered_count,
            verified_count=len(discovered) + len(verified_elsewhere),
            stale_count=stale_count,
            invalid_count=invalid_count,
            unsupported_count=unsupported_count,
            cancelled_listing_count=cancelled_listing_count,
        )
    finally:
        try:
            await redis.eval(
                _RELEASE_SYNC_LOCK_SCRIPT,
                1,
                lock_key,
                lock_token,
            )
        except RedisError:
            # The lease expires automatically; do not hide the sync result.
            pass


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
                    metadata=_merge_metadata(result.metadata, candidate.metadata),
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

    collection_by_asset = {
        item.address: item.collection_address for item in verified_items
    }
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
                collection_address=collection_by_asset.get(
                    asset.item_address or asset.external_id
                ),
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
