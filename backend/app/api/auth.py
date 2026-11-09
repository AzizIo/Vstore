from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.auth.schemas import (
    AuthenticatedUser,
    TelegramAuthRequest,
    TelegramAuthResponse,
)
from app.auth.telegram import TelegramInitDataError, verify_telegram_init_data
from app.auth.tokens import create_access_token
from app.core.config import get_settings
from app.db.models import User
from app.db.session import async_session_factory

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/telegram", response_model=TelegramAuthResponse)
async def authenticate_telegram(
    payload: TelegramAuthRequest,
) -> TelegramAuthResponse:
    settings = get_settings()
    if not settings.bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram authentication is not configured",
        )
    if not settings.auth_secret_key or len(settings.auth_secret_key) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication secret is not configured",
        )

    try:
        verified = verify_telegram_init_data(payload.init_data, settings.bot_token)
    except TelegramInitDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Telegram initData",
        ) from exc

    telegram_user = verified.user
    statement = (
        insert(User)
        .values(
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            language_code=telegram_user.language_code,
        )
        .on_conflict_do_update(
            index_elements=[User.telegram_id],
            set_={
                "username": telegram_user.username,
                "first_name": telegram_user.first_name,
                "last_name": telegram_user.last_name,
                "language_code": telegram_user.language_code,
                "updated_at": func.now(),
            },
        )
        .returning(User)
    )

    async with async_session_factory() as session:
        async with session.begin():
            user = (await session.execute(statement)).scalar_one()
            if user.is_blocked:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This account is restricted",
                )

    token = create_access_token(
        user_id=user.id,
        telegram_id=user.telegram_id,
        secret_key=settings.auth_secret_key,
        expires_in_seconds=settings.auth_token_ttl_seconds,
    )
    return TelegramAuthResponse(
        access_token=token,
        expires_in=settings.auth_token_ttl_seconds,
        user=AuthenticatedUser(
            id=str(user.id),
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        ),
    )
