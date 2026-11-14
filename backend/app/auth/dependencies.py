from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.db.models import User
from app.db.session import async_session_factory

bearer_scheme = HTTPBearer(auto_error=False)


async def _resolve_current_user(
    credentials: HTTPAuthorizationCredentials | None,
    *,
    allow_blocked: bool,
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    secret_key = get_settings().auth_secret_key
    if not secret_key or len(secret_key) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )

    try:
        payload = jwt.decode(credentials.credentials, secret_key, algorithms=["HS256"])
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise ValueError("Invalid token subject")
        user_id = UUID(subject)
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    async with async_session_factory() as session:
        user = await session.get(User, user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.is_blocked and not allow_blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This account is restricted. Creating listings and new orders is disabled; "
                "existing order and delivery operations remain available."
            ),
        )
    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Resolve a verified session and enforce the platform account restriction."""
    return await _resolve_current_user(credentials, allow_blocked=False)


async def get_current_user_allow_blocked(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Resolve identity for read-only account data and already-existing order workflows.

    Callers using this dependency must not create a new listing/deal and must scope
    mutations to an already-existing resource owned by the authenticated user.
    """
    return await _resolve_current_user(credentials, allow_blocked=True)
