from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.dependencies import get_current_user


@pytest.mark.asyncio
async def test_current_user_requires_bearer_credentials() -> None:
    with pytest.raises(HTTPException) as error:
        await get_current_user(None)
    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.asyncio
async def test_current_user_rejects_unconfigured_auth_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.auth.dependencies.get_settings",
        lambda: SimpleNamespace(auth_secret_key="short"),
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="anything")
    with pytest.raises(HTTPException) as error:
        await get_current_user(credentials)
    assert error.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        jwt.encode({"sub": "not-a-uuid"}, "s" * 32, algorithm="HS256"),
        jwt.encode({"sub": 123}, "s" * 32, algorithm="HS256"),
        jwt.encode({"sub": "00000000-0000-0000-0000-000000000001"}, "x" * 32, algorithm="HS256"),
    ],
)
async def test_current_user_rejects_invalid_tokens(token: str, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.auth.dependencies.get_settings",
        lambda: SimpleNamespace(auth_secret_key="s" * 32),
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as error:
        await get_current_user(credentials)
    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}
