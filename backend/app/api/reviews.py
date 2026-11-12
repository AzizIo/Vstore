from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.reviews.schemas import (
    EligibilityResponse,
    ReviewCreateRequest,
    ReviewCreateResponse,
    ReviewPageResponse,
)
from app.reviews.service import (
    ReviewConflict,
    create_review,
    get_review_eligibility,
    list_seller_reviews,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/sellers/{seller_id}", response_model=ReviewPageResponse)
async def get_seller_reviews(
    seller_id: UUID,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> ReviewPageResponse:
    return await list_seller_reviews(
        session, seller_id=seller_id, limit=limit, offset=offset
    )


@router.get("/eligibility", response_model=EligibilityResponse)
async def check_review_eligibility(
    order_id: UUID,
    session: DbSession,
    user: CurrentUser,
) -> EligibilityResponse:
    return await get_review_eligibility(session, order_id=order_id, buyer_id=user.id)


@router.post("", response_model=ReviewCreateResponse, status_code=status.HTTP_201_CREATED)
async def submit_review(
    payload: ReviewCreateRequest,
    session: DbSession,
    user: CurrentUser,
) -> ReviewCreateResponse:
    try:
        return await create_review(
            session,
            order_id=payload.order_id,
            buyer_id=user.id,
            rating=payload.rating,
            comment=payload.comment,
        )
    except ReviewConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
