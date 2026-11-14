from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.escrow import _verified_wallet, router
from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db_session


class MissingResourceSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> None:
        self.statements.append(statement)
        return None


def test_foreign_deal_id_is_not_disclosed() -> None:
    actor_id = uuid4()
    deal_id = uuid4()
    user = User(id=actor_id, telegram_id=987654321, first_name="test")
    session = MissingResourceSession()

    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def override_user() -> User:
        return user

    async def override_session():
        yield session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db_session] = override_session

    response = TestClient(app).get(f"/api/escrow/deals/{deal_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Escrow deal not found"
    assert len(session.statements) == 1
    statement = session.statements[0]
    compiled = statement.compile()
    sql = str(compiled)
    params = list(compiled.params.values())
    assert "escrow_deals.buyer_id" in sql
    assert "escrow_deals.seller_id" in sql
    assert actor_id in params
    assert deal_id in params


def test_foreign_listing_intent_id_is_not_disclosed() -> None:
    actor_id = uuid4()
    intent_id = uuid4()
    user = User(id=actor_id, telegram_id=987654322, first_name="test")
    session = MissingResourceSession()

    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def override_user() -> User:
        return user

    async def override_session():
        yield session

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db_session] = override_session

    response = TestClient(app).get(f"/api/escrow/listing-intents/{intent_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Escrow listing intent not found"
    compiled = session.statements[0].compile()
    assert "escrow_listing_intents.seller_id" in str(compiled)
    assert actor_id in compiled.params.values()


@pytest.mark.asyncio
async def test_wallet_reference_cannot_be_spoofed_across_accounts() -> None:
    actor_id = uuid4()
    foreign_wallet_id = uuid4()
    session = MissingResourceSession()

    with pytest.raises(HTTPException) as error:
        await _verified_wallet(
            session, user_id=actor_id, wallet_id=foreign_wallet_id
        )

    assert error.value.status_code == 404
    compiled = session.statements[0].compile()
    sql = str(compiled)
    params = compiled.params.values()
    assert "wallets.user_id" in sql
    assert "wallets.is_verified" in sql
    assert "wallets.network" in sql
    assert actor_id in params
    assert foreign_wallet_id in params
