from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assets.ton_nft.dependencies import get_ton_nft_verifier
from app.assets.ton_nft.models import VerificationStatus
from app.assets.ton_nft.verifier import TONNFTVerifier
from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    PriceCurrency,
    User,
    Wallet,
)
from app.db.session import get_db_session
from app.listings.service import (
    ListingConflict,
    ListingNotFound,
    ListingVerificationUnavailable,
    cancel_listing,
    publish_listing,
    update_listing,
)

router = APIRouter(prefix="/listings", tags=["listings"])


class ListingCollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    address: str
    network: str
    name: str | None
    marketplace_name: str | None


class ListingAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_type: AssetType
    external_id: str
    item_address: str | None
    name: str | None
    description: str | None
    image_url: str | None
    verification_status: AssetVerificationStatus
    collection: ListingCollectionResponse | None = None


class ListingSellerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str | None
    first_name: str


class ListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: ListingStatus
    price_amount: Decimal
    price_currency: PriceCurrency
    title: str | None
    description: str | None
    created_at: datetime
    expires_at: datetime | None = None
    asset: ListingAssetResponse
    seller: ListingSellerResponse


class ListingPageResponse(BaseModel):
    items: list[ListingResponse]
    total: int
    limit: int
    offset: int


class ListingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    price_amount: Decimal = Field(gt=0, max_digits=24, decimal_places=9)
    price_currency: PriceCurrency
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_expiration(self) -> ListingCreateRequest:
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("Expiration must include a timezone")
            if self.expires_at <= datetime.now(UTC):
                raise ValueError("Expiration must be in the future")
        return self


class ListingUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_amount: Decimal | None = Field(
        default=None, gt=0, max_digits=24, decimal_places=9
    )
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_update_fields(self) -> ListingUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        if "price_amount" in self.model_fields_set and self.price_amount is None:
            raise ValueError("Price cannot be null")
        if self.expires_at is not None and "expires_at" in self.model_fields_set:
            if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("Expiration must include a timezone")
            if self.expires_at <= datetime.now(UTC):
                raise ValueError("Expiration must be in the future")
        return self


def _listing_query() -> Select[Listing]:
    return select(Listing).options(
        selectinload(Listing.asset).selectinload(NFTAsset.collection),
        selectinload(Listing.seller),
    )


def _purchasable_conditions() -> list:
    """Conditions a listing must satisfy before it is offered to a new buyer.

    A listing status alone is not enough: the asset behind it may have been
    marked stale by an ownership re-check, and the seller association may have
    changed. Reserved listings are excluded because another buyer already holds
    the reservation.
    """

    return [
        Listing.status == ListingStatus.ACTIVE,
        or_(Listing.expires_at.is_(None), Listing.expires_at > func.now()),
        NFTAsset.verification_status == AssetVerificationStatus.VERIFIED,
        NFTAsset.owner_id == Listing.seller_id,
    ]


@router.get("", response_model=ListingPageResponse)
async def get_listings(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
    asset_type: AssetType | None = None,
    currency: PriceCurrency | None = None,
    min_price: Annotated[Decimal | None, Query(gt=0, max_digits=24, decimal_places=9)] = None,
    max_price: Annotated[Decimal | None, Query(gt=0, max_digits=24, decimal_places=9)] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort: Annotated[str, Query(pattern="^(newest|price_asc|price_desc)$")] = "newest",
) -> ListingPageResponse:
    if (min_price is not None or max_price is not None or sort != "newest") and currency is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select a price currency before filtering or sorting by price",
        )
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Minimum price cannot exceed maximum price",
        )

    conditions = _purchasable_conditions()
    if asset_type is not None:
        conditions.append(NFTAsset.asset_type == asset_type)
    if currency is not None:
        conditions.append(Listing.price_currency == currency)
    if min_price is not None:
        conditions.append(Listing.price_amount >= min_price)
    if max_price is not None:
        conditions.append(Listing.price_amount <= max_price)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Listing.title.ilike(pattern), NFTAsset.name.ilike(pattern)))

    base = select(Listing).join(NFTAsset).where(*conditions)
    count_statement = select(func.count()).select_from(base.subquery())
    total = await session.scalar(count_statement) or 0

    statement = _listing_query().join(NFTAsset).where(*conditions)
    # Every ordering ends with the primary key so pagination is stable when
    # timestamps or prices collide; without it, limit/offset can repeat or skip
    # rows across pages.
    if sort == "price_asc":
        statement = statement.order_by(
            Listing.price_amount.asc(), Listing.created_at.desc(), Listing.id.asc()
        )
    elif sort == "price_desc":
        statement = statement.order_by(
            Listing.price_amount.desc(), Listing.created_at.desc(), Listing.id.asc()
        )
    else:
        statement = statement.order_by(Listing.created_at.desc(), Listing.id.asc())

    result = await session.scalars(statement.limit(limit).offset(offset))
    return ListingPageResponse(
        items=[ListingResponse.model_validate(item) for item in result.unique().all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/me", response_model=list[ListingResponse])
async def get_my_listings(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ListingResponse]:
    statement = _listing_query().where(Listing.seller_id == user.id).order_by(
        Listing.created_at.desc()
    )
    result = await session.scalars(statement)
    return [ListingResponse.model_validate(item) for item in result.unique().all()]


@router.get("/{listing_id}", response_model=ListingResponse)
async def get_listing(
    listing_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Listing:
    statement = _listing_query().join(NFTAsset).where(
        Listing.id == listing_id,
        *_purchasable_conditions(),
    )
    result = await session.scalars(statement)
    listing = result.unique().one_or_none()
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found")
    return listing


@router.post("", response_model=ListingResponse, status_code=status.HTTP_201_CREATED)
async def create_listing_draft(
    payload: ListingCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    verifier: Annotated[TONNFTVerifier, Depends(get_ton_nft_verifier)],
) -> Listing:
    """Create an unpublished draft only after a fresh owner verification."""

    settings = get_settings()
    user_id = user.id
    asset = await session.scalar(
        select(NFTAsset).where(
            NFTAsset.id == payload.asset_id,
            NFTAsset.owner_id == user_id,
            NFTAsset.network == settings.ton_connect_network,
        )
    )
    if (
        asset is None
        or asset.asset_type is not AssetType.TON_NFT
        or asset.verification_status is not AssetVerificationStatus.VERIFIED
        or not asset.item_address
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only verified TON NFTs currently owned by you can be listed",
        )

    conflicting_listing_id = await session.scalar(
        select(Listing.id).where(
            Listing.asset_id == asset.id,
            Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]),
        )
    )
    if conflicting_listing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This NFT already has an active or reserved listing",
        )

    verified_wallets = await session.scalars(
        select(Wallet).where(
            Wallet.user_id == user_id,
            Wallet.is_verified.is_(True),
            Wallet.network == settings.ton_connect_network,
        )
    )
    wallet_refs = [(wallet.id, wallet.address) for wallet in verified_wallets.all()]
    if not wallet_refs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A verified TON wallet is required to create a listing draft",
        )

    verified_result = None
    verified_wallet_id = None
    owner_mismatch = False
    item_address = asset.item_address
    asset_id = asset.id
    await session.rollback()
    for candidate_wallet_id, wallet_address in wallet_refs:
        result = await verifier.verify(item_address, wallet_address)
        if result.status is VerificationStatus.PROVIDER_UNAVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TON NFT ownership provider is temporarily unavailable",
            )
        if result.is_verified:
            verified_result = result
            verified_wallet_id = candidate_wallet_id
            break
        owner_mismatch = (
            owner_mismatch or result.status is VerificationStatus.OWNER_MISMATCH
        )

    if verified_result is None:
        if owner_mismatch:
            current_wallets = await session.scalars(
                select(Wallet)
                .where(
                    Wallet.id.in_([wallet_id for wallet_id, _ in wallet_refs]),
                    Wallet.user_id == user_id,
                    Wallet.is_verified.is_(True),
                    Wallet.network == settings.ton_connect_network,
                )
                .with_for_update()
            )
            if list(current_wallets.all()):
                stale_asset = await session.scalar(
                    select(NFTAsset)
                    .where(
                        NFTAsset.id == asset_id,
                        NFTAsset.owner_id == user_id,
                        NFTAsset.item_address == item_address,
                    )
                    .with_for_update()
                )
                if stale_asset is not None:
                    stale_asset.owner_id = None
                    stale_asset.verification_status = AssetVerificationStatus.STALE
                    await session.commit()
                else:
                    await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="NFT ownership could not be freshly verified; refresh your inventory",
        )

    current_wallets = await session.scalars(
        select(Wallet)
        .where(
            Wallet.id == verified_wallet_id,
            Wallet.user_id == user_id,
            Wallet.is_verified.is_(True),
            Wallet.network == settings.ton_connect_network,
        )
        .with_for_update()
    )
    current_wallet_rows = list(current_wallets.all())
    current_wallet = current_wallet_rows[0] if current_wallet_rows else None
    if (
        current_wallet is None
        or current_wallet.address != verified_result.expected_owner_address
    ):
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A verified TON wallet is required to create a listing draft",
        )

    locked_asset = await session.scalar(
        select(NFTAsset)
        .where(
            NFTAsset.id == asset_id,
            NFTAsset.owner_id == user_id,
            NFTAsset.network == settings.ton_connect_network,
            NFTAsset.asset_type == AssetType.TON_NFT,
            NFTAsset.item_address == item_address,
            NFTAsset.verification_status == AssetVerificationStatus.VERIFIED,
        )
        .with_for_update()
    )
    if locked_asset is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="NFT inventory changed during verification; refresh your inventory",
        )

    conflicting_listing_id = await session.scalar(
        select(Listing.id).where(
            Listing.asset_id == locked_asset.id,
            Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]),
        )
    )
    if conflicting_listing_id is not None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This NFT already has an active or reserved listing",
        )

    locked_asset.item_address = verified_result.item_address
    locked_asset.owner_id = user_id
    locked_asset.verification_status = AssetVerificationStatus.VERIFIED
    locked_asset.verified_at = datetime.now(UTC)
    locked_asset.name = verified_result.metadata.name
    locked_asset.description = verified_result.metadata.description
    locked_asset.image_url = verified_result.metadata.image
    locked_asset.metadata_json = (
        {"attributes": list(verified_result.metadata.attributes)}
        if verified_result.metadata.attributes
        else None
    )

    listing = Listing(
        asset_id=locked_asset.id,
        seller_id=user_id,
        status=ListingStatus.DRAFT,
        price_amount=payload.price_amount,
        price_currency=payload.price_currency,
        title=payload.title,
        description=payload.description,
        expires_at=payload.expires_at,
    )
    session.add(listing)
    await session.commit()
    listing_result = await session.scalars(
        _listing_query().where(Listing.id == listing.id)
    )
    return listing_result.unique().one()


@router.post("/{listing_id}/publish", response_model=ListingResponse)
async def publish_my_listing(
    listing_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    verifier: Annotated[TONNFTVerifier, Depends(get_ton_nft_verifier)],
) -> Listing:
    try:
        return await publish_listing(
            session,
            listing_id=listing_id,
            seller_id=user.id,
            verifier=verifier,
        )
    except ListingNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ListingVerificationUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except (ListingConflict, IntegrityError) as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{listing_id}", response_model=ListingResponse)
async def edit_my_listing(
    listing_id: UUID,
    payload: ListingUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Listing:
    try:
        return await update_listing(
            session,
            listing_id=listing_id,
            seller_id=user.id,
            price_amount=payload.price_amount,
            title=payload.title,
            description=payload.description,
            expires_at=payload.expires_at,
            fields_set=set(payload.model_fields_set),
        )
    except ListingNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ListingConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{listing_id}/cancel", response_model=ListingResponse)
async def cancel_my_listing(
    listing_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Listing:
    try:
        return await cancel_listing(
            session,
            listing_id=listing_id,
            seller_id=user.id,
        )
    except ListingNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ListingConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
