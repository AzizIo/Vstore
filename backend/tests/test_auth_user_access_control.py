from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.dependencies import get_current_user
from app.db.models import User

AUTH_SECRET = "viltara-test-secret-" + ("s" * 40)


def _credentials(user_id, *, expires_at=None):
    payload = {
        "sub": str(user_id),
        "exp": expires_at or datetime.now(UTC) + timedelta(minutes=5),
    }
    token = jwt.encode(payload, AUTH_SECRET, algorithm="HS256")
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _configure_user_lookup(monkeypatch, user_record):
    monkeypatch.setattr(
        "app.auth.dependencies.get_settings",
        lambda: SimpleNamespace(auth_secret_key=AUTH_SECRET),
    )

    session = AsyncMock()
    session.get.return_value = user_record

    session_context = AsyncMock()
    session_context.__aenter__.return_value = session

    session_factory = Mock(return_value=session_context)
    monkeypatch.setattr(
        "app.auth.dependencies.async_session_factory",
        session_factory,
    )
    return session, session_factory


@pytest.mark.asyncio
async def test_current_user_loads_account_from_token_subject(monkeypatch) -> None:
    user_id = uuid4()
    user = User(
        id=user_id,
        telegram_id=987654321,
        first_name="Buyer",
        is_blocked=False,
    )
    session, session_factory = _configure_user_lookup(monkeypatch, user)

    result = await get_current_user(_credentials(user_id))

    assert result is user
    session_factory.assert_called_once_with()
    session.get.assert_awaited_once_with(User, user_id)


@pytest.mark.asyncio
async def test_current_user_rejects_account_that_no_longer_exists(monkeypatch) -> None:
    user_id = uuid4()
    session, _ = _configure_user_lookup(monkeypatch, None)

    with pytest.raises(HTTPException) as error:
        await get_current_user(_credentials(user_id))

    assert error.value.status_code == 401
    assert error.value.detail == "User no longer exists"
    session.get.assert_awaited_once_with(User, user_id)


@pytest.mark.asyncio
async def test_current_user_rejects_blocked_account(monkeypatch) -> None:
    user_id = uuid4()
    blocked_user = User(
        id=user_id,
        telegram_id=987654322,
        first_name="Blocked",
        is_blocked=True,
    )
    session, _ = _configure_user_lookup(monkeypatch, blocked_user)

    with pytest.raises(HTTPException) as error:
        await get_current_user(_credentials(user_id))

    assert error.value.status_code == 403
    assert error.value.detail == "This account is restricted"
    session.get.assert_awaited_once_with(User, user_id)


@pytest.mark.asyncio
async def test_current_user_rejects_expired_token_before_database_lookup(monkeypatch) -> None:
    user_id = uuid4()
    session, session_factory = _configure_user_lookup(monkeypatch, None)
    credentials = _credentials(
        user_id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(HTTPException) as error:
        await get_current_user(credentials)

    assert error.value.status_code == 401
    assert error.value.detail == "Invalid or expired access token"
    session_factory.assert_not_called()
    session.get.assert_not_awaited()
