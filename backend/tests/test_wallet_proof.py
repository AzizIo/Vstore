import base64
import hashlib
import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey
from pytoniq.contract.wallets.wallet import WALLET_V4_R2_CODE
from pytoniq_core.boc.address import Address
from pytoniq_core.tlb.account import StateInit
from pytoniq_core.tlb.custom.wallet import WalletV4Data
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError

from app.api import wallets as wallets_api
from app.auth.dependencies import get_current_user
from app.core.config import Settings
from app.db.models import User, Wallet
from app.db.session import get_db_session
from app.main import app
from app.wallets import proof as wallet_proof
from app.wallets.proof import CHALLENGE_TTL_SECONDS
from app.wallets.redis import get_redis_client

DOMAIN = "app.example.com"
CHAIN_ID = "-239"
NOW = int(time.time())
SIGNING_KEY = SigningKey(bytes(range(32)))
PUBLIC_KEY = bytes(SIGNING_KEY.verify_key)
WALLET_STATE_INIT = StateInit(
    code=WALLET_V4_R2_CODE,
    data=WalletV4Data(seqno=0, wallet_id=698983191, public_key=PUBLIC_KEY).serialize(),
).serialize()
WALLET_STATE_INIT_BOC = base64.b64encode(WALLET_STATE_INIT.to_boc()).decode("ascii")
WALLET_ADDRESS = Address((0, WALLET_STATE_INIT.hash)).to_str(is_user_friendly=False)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expiries[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def eval(self, _script: str, _numkeys: int, key: str, expected_value: str) -> int:
        if self.values.get(key) != expected_value:
            return 0
        del self.values[key]
        self.expiries.pop(key, None)
        return 1


class WalletAddressUniqueViolation(Exception):
    constraint_name = "uq_wallets_network_address"


@pytest.fixture
def wallet_client(monkeypatch: pytest.MonkeyPatch):
    user = User(
        id=uuid4(),
        telegram_id=123456789,
        first_name="Wallet owner",
        is_blocked=False,
    )
    session = AsyncMock()
    session.add = Mock()
    session.scalar.return_value = None
    redis = FakeRedis()
    settings = Settings(
        ton_connect_allowed_domains=[DOMAIN],
        ton_connect_network="mainnet",
    )
    monkeypatch.setattr(wallets_api, "get_settings", lambda: settings)
    app.dependency_overrides[get_current_user] = lambda: user

    async def override_session() -> AsyncIterator[AsyncMock]:
        yield session

    async def override_redis() -> AsyncIterator[Redis]:
        yield redis  # type: ignore[misc]

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_redis_client] = override_redis
    try:
        with TestClient(app) as client:
            yield client, user, session, redis
    finally:
        app.dependency_overrides.clear()


def _proof_digest(
    *,
    address: str,
    timestamp: int,
    domain: str,
    payload: str,
) -> bytes:
    workchain, address_hash = address.split(":")
    domain_bytes = domain.encode("utf-8")
    message = (
        b"ton-proof-item-v2/"
        + int(workchain).to_bytes(4, "big", signed=True)
        + bytes.fromhex(address_hash)
        + len(domain_bytes).to_bytes(4, "little")
        + domain_bytes
        + timestamp.to_bytes(8, "little")
        + payload.encode("utf-8")
    )
    return hashlib.sha256(
        b"\xff\xffton-connect" + hashlib.sha256(message).digest()
    ).digest()


def _signed_request(
    payload: str,
    *,
    timestamp: int = NOW,
    domain: str = DOMAIN,
    address: str = WALLET_ADDRESS,
    network: str = CHAIN_ID,
    signature: bytes | None = None,
    state_init: str = WALLET_STATE_INIT_BOC,
) -> dict[str, Any]:
    domain_bytes = domain.encode("utf-8")
    digest = _proof_digest(
        address=address,
        timestamp=timestamp,
        domain=domain,
        payload=payload,
    )
    signed = SIGNING_KEY.sign(digest).signature if signature is None else signature
    return {
        "address": address,
        "network": network,
        "public_key": PUBLIC_KEY.hex(),
        "proof": {
            "timestamp": timestamp,
            "domain": {"lengthBytes": len(domain_bytes), "value": domain},
            "signature": base64.b64encode(signed).decode("ascii"),
            "payload": payload,
            "state_init": state_init,
        },
    }


def _create_challenge(client: TestClient) -> str:
    response = client.post("/api/wallets/proof/challenge")
    assert response.status_code == 200
    return response.json()["payload"]


def test_proof_challenge_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.post("/api/wallets/proof/challenge")
    assert response.status_code == 401


def test_challenge_is_random_user_bound_and_has_short_redis_ttl(
    wallet_client,
) -> None:
    client, user, _, redis = wallet_client
    response = client.post("/api/wallets/proof/challenge")

    assert response.status_code == 200
    payload = response.json()["payload"]
    key = wallets_api._challenge_key(payload)
    assert len(payload) >= 32
    assert redis.values[key] == str(user.id)
    assert redis.expiries[key] == CHALLENGE_TTL_SECONDS
    assert response.json()["expires_at"]


def test_valid_ton_proof_verifies_and_links_wallet(wallet_client) -> None:
    client, user, session, redis = wallet_client
    challenge = _create_challenge(client)

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge),
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(session.add.call_args.args[0].id),
        "address": WALLET_ADDRESS,
        "network": "mainnet",
        "is_verified": True,
        "is_primary": False,
    }
    wallet = session.add.call_args.args[0]
    assert wallet.user_id == user.id
    assert wallet.is_verified is True
    assert wallets_api._challenge_key(challenge) not in redis.values


def test_invalid_signature_is_rejected_without_consuming_challenge(wallet_client) -> None:
    client, _, _, redis = wallet_client
    challenge = _create_challenge(client)
    invalid_signature = bytes([0]) * 64

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge, signature=invalid_signature),
    )

    assert response.status_code == 401
    assert wallets_api._challenge_key(challenge) in redis.values


def test_altered_address_does_not_match_wallet_state_init(wallet_client) -> None:
    client, _, session, _ = wallet_client
    challenge = _create_challenge(client)
    changed_address = "0:" + ("00" * 32)

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge, address=changed_address),
    )

    assert response.status_code == 401
    session.commit.assert_not_awaited()


def test_wrong_domain_is_rejected(wallet_client) -> None:
    client, _, session, _ = wallet_client
    challenge = _create_challenge(client)

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge, domain="attacker.example.com"),
    )

    assert response.status_code == 401
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("timestamp", [NOW - 301, NOW + 301])
def test_expired_or_future_proof_timestamp_is_rejected(
    wallet_client,
    timestamp: int,
) -> None:
    client, _, session, _ = wallet_client
    challenge = _create_challenge(client)

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge, timestamp=timestamp),
    )

    assert response.status_code == 401
    session.commit.assert_not_awaited()


def test_missing_or_unrecognized_nonce_is_rejected(wallet_client) -> None:
    client, _, session, _ = wallet_client

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request("not-issued-by-server"),
    )

    assert response.status_code == 401
    session.commit.assert_not_awaited()


def test_expired_challenge_is_rejected(wallet_client) -> None:
    client, _, session, redis = wallet_client
    challenge = _create_challenge(client)
    key = wallets_api._challenge_key(challenge)
    redis.values.pop(key, None)
    redis.expiries.pop(key, None)

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge),
    )

    assert response.status_code == 401
    session.commit.assert_not_awaited()


def test_replayed_nonce_is_rejected(wallet_client) -> None:
    client, _, _, _ = wallet_client
    challenge = _create_challenge(client)
    proof = _signed_request(challenge)

    first_response = client.post("/api/wallets/proof/verify", json=proof)
    replay_response = client.post("/api/wallets/proof/verify", json=proof)

    assert first_response.status_code == 200
    assert replay_response.status_code == 401


def test_proof_challenge_cannot_be_used_by_another_user(wallet_client) -> None:
    client, _, session, redis = wallet_client
    challenge = _create_challenge(client)
    redis.values[wallets_api._challenge_key(challenge)] = str(uuid4())

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge),
    )

    assert response.status_code == 401
    session.commit.assert_not_awaited()


def test_wallet_already_bound_to_another_user_returns_conflict(wallet_client) -> None:
    client, _, session, _ = wallet_client
    challenge = _create_challenge(client)
    session.scalar.return_value = Wallet(
        id=uuid4(),
        user_id=uuid4(),
        address=WALLET_ADDRESS,
        network="mainnet",
        is_verified=True,
        is_primary=False,
    )

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge),
    )

    assert response.status_code == 409
    session.add.assert_not_called()


def test_database_unique_constraint_race_returns_conflict(wallet_client) -> None:
    client, _, session, _ = wallet_client
    challenge = _create_challenge(client)
    session.commit.side_effect = IntegrityError(
        "insert",
        {},
        WalletAddressUniqueViolation("duplicate"),
    )

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge),
    )

    assert response.status_code == 409
    session.rollback.assert_awaited_once()


def test_unconfigured_allowed_domain_list_disables_proof(
    wallet_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _, _ = wallet_client
    monkeypatch.setattr(
        wallets_api,
        "get_settings",
        lambda: Settings(ton_connect_allowed_domains=[], ton_connect_network="mainnet"),
    )

    response = client.post("/api/wallets/proof/challenge")

    assert response.status_code == 503


def test_unsupported_network_is_rejected(wallet_client) -> None:
    client, _, session, _ = wallet_client
    challenge = _create_challenge(client)

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge, network="-3"),
    )

    assert response.status_code == 401
    session.commit.assert_not_awaited()


def test_malformed_state_init_is_rejected(wallet_client) -> None:
    client, _, session, _ = wallet_client
    challenge = _create_challenge(client)

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge, state_init="bm90LWEtYm9j"),
    )

    assert response.status_code == 401
    session.commit.assert_not_awaited()


def test_optional_client_public_key_must_match_state_init(wallet_client) -> None:
    client, _, session, _ = wallet_client
    challenge = _create_challenge(client)
    proof = _signed_request(challenge)
    proof["public_key"] = "00" * 32

    response = client.post("/api/wallets/proof/verify", json=proof)

    assert response.status_code == 401
    session.commit.assert_not_awaited()


def test_current_user_wallet_list_filters_by_authenticated_user(wallet_client) -> None:
    client, user, session, _ = wallet_client

    class Rows:
        def all(self) -> list[Wallet]:
            return [
                Wallet(
                    id=uuid4(),
                    user_id=user.id,
                    address=WALLET_ADDRESS,
                    network="mainnet",
                    is_verified=True,
                    is_primary=False,
                )
            ]

    session.scalars.return_value = Rows()

    response = client.get("/api/wallets/me")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["address"] == WALLET_ADDRESS
    assert "private_key" not in response.json()[0]
    assert "seed_phrase" not in response.json()[0]
    statement = session.scalars.call_args.args[0]
    assert user.id in statement.compile().params.values()

def test_unsupported_wallet_contract_is_rejected(
    wallet_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, session, _ = wallet_client
    challenge = _create_challenge(client)

    # Treat the V4 R2 code embedded in the fixture as unknown. The verifier
    # must fail closed rather than extracting a public key from an unknown layout.
    monkeypatch.setattr(
        wallet_proof,
        "WALLET_V4_R2_CODE",
        wallet_proof.WALLET_V3_R1_CODE,
    )

    response = client.post(
        "/api/wallets/proof/verify",
        json=_signed_request(challenge),
    )

    assert response.status_code == 401
    session.commit.assert_not_awaited()
