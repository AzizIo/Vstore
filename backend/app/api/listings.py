from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
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

router = APIRouter(prefix="/listings", tags=["listings"])


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
    created_at: object
    asset: ListingAssetResponse
    seller: ListingSellerResponse


class ListingPageResponse(BaseModel):
    items: list[ListingResponse]
    total: int
    limit: int
    offset: int


class ListingCreateRequest(BaseModel):
    asset_id: UUID
    price_amount: Decimal = Field(gt=0, max_digits=24, decimal_places=9)
    price_currency: PriceCurrency
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)


def _listing_query():
    return select(Listing).options(
        selectinload(Listing.asset),
        selectinload(Listing.seller),
    )


@router.get("", response_model=ListingPageResponse)
async def get_listings(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
    asset_type: AssetType | None = None,
    currency: PriceCurrency | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort: Annotated[str, Query(pattern="^(newest|price_asc|price_desc)$")] = "newest",
) -> ListingPageResponse:
    conditions = [Listing.status == ListingStatus.ACTIVE]
    if asset_type is not None:
        conditions.append(NFTAsset.asset_type == asset_type)
    if currency is not None:
        conditions.append(Listing.price_currency == currency)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Listing.title.ilike(pattern), NFTAsset.name.ilike(pattern)))

    base = select(Listing).join(NFTAsset).where(*conditions)
    count_statement = select(func.count()).select_from(base.subquery())
    total = await session.scalar(count_statement) or 0

    statement = _listing_query().join(NFTAsset).where(*conditions)
    if sort == "price_asc":
        statement = statement.order_by(Listing.price_amount.asc(), Listing.created_at.desc())
    elif sort == "price_desc":
        statement = statement.order_by(Listing.price_amount.desc(), Listing.created_at.desc())
    else:
        statement = statement.order_by(Listing.created_at.desc())

    result = await session.scalars(statement.limit(limit).offset(offset))
    return ListingPageResponse(
        items=list(result.unique().all()),
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
    return list(result.unique().all())


@router.get("/{listing_id}", response_model=ListingResponse)
async def get_listing(
    listing_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Listing:
    statement = _listing_query().where(
        Listing.id == listing_id,
        Listing.status == ListingStatus.ACTIVE,
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
) -> Listing:
    """Create a private draft from an asset already verified and assigned to this user.

    Publishing is intentionally not exposed until a live ownership re-checker is implemented.
    """
    asset = await session.scalar(
        select(NFTAsset).where(
            NFTAsset.id == payload.asset_id,
            NFTAsset.owner_id == user.id,
            NFTAsset.verification_status == AssetVerificationStatus.VERIFIED,
        )
    )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only verified assets currently owned by you can be listed",
        )

    listing = Listing(
        asset_id=asset.id,
        seller_id=user.id,
        status=ListingStatus.DRAFT,
        price_amount=payload.price_amount,
        price_currency=payload.price_currency,
        title=payload.title,
        description=payload.description,
    )
    session.add(listing)
    await session.commit()
    await session.refresh(listing)
    await session.refresh(asset)
    listing.asset = asset
    listing.seller = user
    return listing
