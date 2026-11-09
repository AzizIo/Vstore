from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import User, Wallet
from app.db.session import get_db_session

router = APIRouter(prefix="/users", tags=["users"])


class UserProfileResponse(BaseModel):
    id: str
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None
    language_code: str | None


class WalletCreateRequest(BaseModel):
    address: str = Field(min_length=3, max_length=128)
    network: Literal["mainnet", "testnet"] = "mainnet"


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


@router.post(
    "/me/wallets",
    response_model=WalletResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_wallet(
    payload: WalletCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Wallet:
    address = payload.address.strip()
    if not address:
        raise HTTPException(status_code=422, detail="Wallet address cannot be empty")

    wallet = Wallet(
        user_id=user.id,
        address=address,
        network=payload.network,
        is_primary=False,
        is_verified=False,
    )
    session.add(wallet)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This wallet is already connected",
        ) from exc

    await session.refresh(wallet)
    return wallet


@router.delete("/me/wallets/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_wallet(
    wallet_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    wallet = await session.scalar(
        select(Wallet).where(Wallet.id == wallet_id, Wallet.user_id == user.id)
    )
    if wallet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")

    await session.delete(wallet)
    await session.commit()
