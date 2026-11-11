from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.db.models import User, Wallet
from app.db.session import get_db_session
from app.main import app


@pytest.fixture
def wallet_client():
    user = User(
        id=uuid4(),
        telegram_id=987654321,
        first_name="Wallet owner",
        is_blocked=False,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    session = AsyncMock()
    session.add = Mock()

    async def override_session():
        yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as client:
            yield client, user, session
    finally:
        app.dependency_overrides.clear()


def test_wallet_list_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/api/users/me/wallets")
    assert response.status_code == 401


def test_wallet_list_returns_only_authenticated_users_wallets(wallet_client):
    client, user, session = wallet_client
    rows = Mock()
    rows.all.return_value = [
        Wallet(
            id=uuid4(),
            user_id=user.id,
            address="0:" + "a" * 64,
            network="mainnet",
            is_verified=True,
            is_primary=True,
        )
    ]
    session.scalars.return_value = rows

    response = client.get("/api/users/me/wallets")

    assert response.status_code == 200
    assert response.json()[0]["address"] == "0:" + "a" * 64
    assert response.json()[0]["is_primary"] is True
    statement = session.scalars.call_args.args[0]
    assert user.id in statement.compile().params.values()


def test_manual_wallet_registration_is_disabled(wallet_client):
    client, _, session = wallet_client

    response = client.post(
        "/api/users/me/wallets",
        json={"address": "0:" + "a" * 64, "network": "mainnet"},
    )

    assert response.status_code == 405
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_remove_wallet_requires_authentication():
    with TestClient(app) as client:
        response = client.delete(f"/api/users/me/wallets/{uuid4()}")
    assert response.status_code == 401


def test_remove_wallet_rejects_wallet_not_owned_by_authenticated_user(wallet_client):
    client, _, session = wallet_client
    session.scalar.return_value = None

    response = client.delete(f"/api/users/me/wallets/{uuid4()}")

    assert response.status_code == 404
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_remove_wallet_deletes_owned_wallet(wallet_client):
    client, user, session = wallet_client
    wallet = Wallet(
        id=uuid4(),
        user_id=user.id,
        address="0:" + "a" * 64,
        network="mainnet",
        is_verified=True,
        is_primary=False,
    )
    session.scalar.return_value = wallet

    response = client.delete(f"/api/users/me/wallets/{wallet.id}")

    assert response.status_code == 204
    session.delete.assert_awaited_once_with(wallet)
    session.commit.assert_awaited_once()
    statement = session.scalar.call_args.args[0]
    assert user.id in statement.compile().params.values()
