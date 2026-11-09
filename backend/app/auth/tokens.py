from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt


def create_access_token(
    *,
    user_id: UUID,
    telegram_id: int,
    secret_key: str,
    expires_in_seconds: int,
) -> str:
    if len(secret_key) < 32:
        raise ValueError("AUTH_SECRET_KEY must contain at least 32 characters")
    if expires_in_seconds <= 0:
        raise ValueError("Token lifetime must be positive")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "telegram_id": telegram_id,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in_seconds),
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")
