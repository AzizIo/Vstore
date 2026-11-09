import uuid

import jwt

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


def test_access_token_rejects_short_secret() -> None:
    try:
        create_access_token(
            user_id=uuid.uuid4(),
            telegram_id=123456,
            secret_key="too-short",
            expires_in_seconds=900,
        )
    except ValueError as exc:
        assert "32 characters" in str(exc)
    else:
        raise AssertionError("Expected short JWT secret to be rejected")
