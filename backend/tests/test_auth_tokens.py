from datetime import UTC, datetime, timedelta
import uuid

import jwt
import pytest

from app.auth.tokens import create_access_token


def test_access_token_contains_subject_and_telegram_identity() -> None:
    user_id = uuid.uuid4()
    secret = "a" * 64
    token = create_access_token(
        user_id=user_id,
        telegram_id=123456,
        secret_key=secret,
        expires_in_seconds=900,
    )
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    assert payload["sub"] == str(user_id)
    assert payload["telegram_id"] == 123456
    assert "iat" in payload
    assert "exp" in payload


@pytest.mark.parametrize("secret", ["", "short", "a" * 31])
def test_access_token_rejects_short_secret(secret: str) -> None:
    with pytest.raises(ValueError, match="32 characters"):
        create_access_token(
            user_id=uuid.uuid4(),
            telegram_id=123456,
            secret_key=secret,
            expires_in_seconds=900,
        )


@pytest.mark.parametrize("ttl", [0, -1, -900])
def test_access_token_rejects_non_positive_lifetime(ttl: int) -> None:
    with pytest.raises(ValueError, match="lifetime"):
        create_access_token(
            user_id=uuid.uuid4(),
            telegram_id=123456,
            secret_key="s" * 32,
            expires_in_seconds=ttl,
        )


def test_access_token_is_signed_and_cannot_be_decoded_with_another_secret() -> None:
    token = create_access_token(
        user_id=uuid.uuid4(),
        telegram_id=123456,
        secret_key="s" * 32,
        expires_in_seconds=900,
    )
    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(token, "x" * 32, algorithms=["HS256"])


def test_access_token_expiry_is_after_issue_time() -> None:
    token = create_access_token(
        user_id=uuid.uuid4(),
        telegram_id=123456,
        secret_key="s" * 32,
        expires_in_seconds=60,
    )
    payload = jwt.decode(token, "s" * 32, algorithms=["HS256"])
    assert datetime.fromtimestamp(payload["exp"], UTC) - datetime.fromtimestamp(
        payload["iat"], UTC
    ) == timedelta(seconds=60)
