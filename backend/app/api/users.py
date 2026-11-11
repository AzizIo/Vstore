from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import Listing, ListingStatus, Order, OrderStatus, User, Wallet
from app.db.session import get_db_session

router = APIRouter(prefix="/users", tags=["users"])


class UserProfileResponse(BaseModel):
    id: str
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None
    language_code: str | None


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    address: str
    network: str
    is_verified: bool
    is_primary: bool


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    user: Annotated[User, Depends(get_current_user)],
) -> UserProfileResponse:
    return UserProfileResponse(
        id=str(user.id),
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,
    )


@router.get("/me/wallets", response_model=list[WalletResponse])
async def get_my_wallets(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[Wallet]:
    result = await session.scalars(
        select(Wallet)
        .where(Wallet.user_id == user.id)
        .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
    )
    return list(result.all())


@router.delete("/me/wallets/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_wallet(
    wallet_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    # Serialize wallet removal with other wallet lifecycle operations. The
    # marketplace currently associates NFT assets with users, not individual
    # wallet rows, so unlinking is intentionally blocked while this user has
    # any live listing or pending order instead of guessing which wallet backs it.
    await session.scalar(select(User.id).where(User.id == user.id).with_for_update())
    wallet = await session.scalar(
        select(Wallet)
        .where(Wallet.id == wallet_id, Wallet.user_id == user.id)
        .with_for_update()
    )
    if wallet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")

    active_listing_id = await session.scalar(
        select(Listing.id)
        .where(
            Listing.seller_id == user.id,
            Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]),
        )
        .limit(1)
    )
    pending_order_id = await session.scalar(
        select(Order.id)
        .where(
            or_(Order.buyer_id == user.id, Order.seller_id == user.id),
            Order.status == OrderStatus.PENDING_PAYMENT,
        )
        .limit(1)
    )
    if active_listing_id is not None or pending_order_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Close active listings and pending orders before unlinking a wallet.",
        )

    await session.delete(wallet)
    await session.commit()
