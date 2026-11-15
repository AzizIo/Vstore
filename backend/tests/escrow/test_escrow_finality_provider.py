from __future__ import annotations

import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.escrow.domain import EscrowChainEventType
from app.escrow.finality_provider import (
    PytoniqTONTestnetEscrowProvider,
    _candidate_type,
    _parse_shard,
)
from app.escrow.provider import EscrowProviderInvalidEvidence


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "ton_connect_network": "testnet",
        "ton_center_testnet_base_url": "https://testnet.toncenter.com/api/v3",
        "ton_center_timeout_seconds": 2.0,
        "ton_escrow_finality_min_depth": 2,
    }
    values.update(overrides)
    return Settings(**values)


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _FakeHttp:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get(self, path: str, *, params: dict[str, object]):
        self.calls.append((path, params))
        return _FakeResponse(self.payload)


class _FakeScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalars(self, _query: object) -> _FakeScalarResult:
        return _FakeScalarResult(self.rows)


class _FakeSessionFactory:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def __call__(self) -> _FakeSession:
        return _FakeSession(self.rows)


def _b64_hash(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _deal():
    return SimpleNamespace(
        id=uuid4(),
        network="testnet",
        contract_address="0:" + "a" * 64,
        item_address="0:" + "b" * 64,
        collection_address_snapshot="0:" + "f" * 64,
        deal_salt="c" * 64,
        deployment_snapshot_json={"contract_state": 0},
        created_at=None,
    )


def test_provider_refuses_mainnet_or_unapproved_discovery_host() -> None:
    with pytest.raises(ValueError, match="only supports TON testnet"):
        PytoniqTONTestnetEscrowProvider(
            settings=_settings(ton_connect_network="mainnet"),
            http_client=_FakeHttp({"transactions": []}),
            lite_client_factory=lambda: object(),
        )

    with pytest.raises(ValueError, match="official testnet TON Center"):
        PytoniqTONTestnetEscrowProvider(
            settings=_settings(
                ton_center_testnet_base_url="https://example.com/api/v3"
            ),
            http_client=_FakeHttp({"transactions": []}),
            lite_client_factory=lambda: object(),
        )


@pytest.mark.asyncio
async def test_liteclient_must_be_trust_level_zero_before_any_proof_use() -> None:
    class UntrustedLiteClient:
        trust_level = 1

        async def connect(self) -> None:
            raise AssertionError("trust-level guard must run before connect")

    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=UntrustedLiteClient,
    )
    with pytest.raises(EscrowProviderInvalidEvidence, match="trust_level must be 0"):
        await provider._get_lite_client()
    await provider.close()


@pytest.mark.parametrize(
    ("opcode", "expected"),
    [
        (0x56450001, EscrowChainEventType.CONTRACT_ACTIVATED),
        (0x56450002, EscrowChainEventType.BUYER_PAYMENT_ACCEPTED),
        (0x56450005, EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED),
        (0x05138D91, EscrowChainEventType.NFT_DEPOSIT_ACCEPTED),
        (0x56450007, EscrowChainEventType.DEAL_TIMEOUT_ACCEPTED),
        (0x56450008, EscrowChainEventType.RECOVERY_NFT_RETURN_STARTED),
        (0xFFFFFFFE, EscrowChainEventType.OUTBOUND_ACTION_BOUNCED),
        (0xFFFFFFFF, EscrowChainEventType.OUTBOUND_ACTION_BOUNCED),
    ],
)
def test_discovery_opcode_mapping_is_provisional_and_state_independent(
    opcode: int, expected: EscrowChainEventType
) -> None:
    assert _candidate_type(opcode) is expected


def test_unknown_opcode_is_not_a_candidate() -> None:
    assert _candidate_type(0xDEADBEEF) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("8000000000000000", -(1 << 63)),
        ("7fffffffffffffff", (1 << 63) - 1),
        ("0x8000000000000000", -(1 << 63)),
        (-1, -1),
    ],
)
def test_shard_parser_handles_signed_int64_encoding(value: object, expected: int) -> None:
    assert _parse_shard(value) == expected


def test_shard_parser_rejects_invalid_or_out_of_range_values() -> None:
    for value in (True, None, "not-a-shard", 1 << 70):
        with pytest.raises((ValueError, TypeError)):
            _parse_shard(value)


@pytest.mark.asyncio
async def test_scan_events_only_emits_bounded_discovery_candidates_and_durable_cursor() -> None:
    deal = _deal()
    tx_hash = _b64_hash(b"t" * 32)
    message_hash = _b64_hash(b"m" * 32)
    row = {
        "lt": "100",
        "hash": tx_hash,
        "mc_block_seqno": 300,
        "now": 1_700_000_000,
        "block_ref": {
            "workchain": 0,
            "shard": "8000000000000000",
            "seqno": 299,
        },
        "in_msg": {
            "hash": message_hash,
            "source": "0:" + "c" * 64,
            "destination": deal.contract_address,
            "value": "10000000",
            "opcode": 0x56450001,
            "message_content": {"opcode": 0x56450001, "body": ""},
        },
    }
    http = _FakeHttp({"transactions": [row]})
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        session_factory=_FakeSessionFactory([deal]),  # type: ignore[arg-type]
        http_client=http,
        lite_client_factory=lambda: object(),
    )

    batch = await provider.scan_events(cursor=None, limit=5)

    assert len(batch.events) == 1
    event = batch.events[0]
    assert event.event_type is EscrowChainEventType.CONTRACT_ACTIVATED
    assert event.candidate_workchain == 0
    assert event.candidate_shard == -(1 << 63)
    assert event.candidate_block_seqno == 299
    assert event.masterchain_seqno == 300
    assert event.finalized is True  # candidate flag only; a proof is still required
    assert "last_lt_by_address" in (batch.next_cursor or "")
    assert http.calls[0][1]["include_msg_body"] == "true"
    await provider.close()


@pytest.mark.asyncio
async def test_scan_rejects_corrupted_or_wrong_version_cursor() -> None:
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        session_factory=_FakeSessionFactory([]),  # type: ignore[arg-type]
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: object(),
    )
    for cursor in ("{bad-json", '{"version":2,"last_lt_by_address":{}}',
                   '{"version":1,"last_lt_by_address":{"address":"not-a-number"}}'):
        with pytest.raises(EscrowProviderInvalidEvidence, match="cursor"):
            await provider.scan_events(cursor=cursor, limit=1)
    await provider.close()



@pytest.mark.asyncio
async def test_scan_persists_bounce_candidate_without_untrusted_attempt_or_query_id() -> None:
    deal = _deal()
    row = {
        "lt": "501",
        "hash": _b64_hash(b"t" * 32),
        "mc_block_seqno": 600,
        "now": 1_700_000_001,
        "block_ref": {"workchain": 0, "shard": "8000000000000000", "seqno": 599},
        "in_msg": {
            "hash": _b64_hash(b"b" * 32),
            "source": "0:" + "d" * 64,
            "destination": deal.contract_address,
            "value": "90000000",
            "bounced": True,
            "opcode": 0xFFFFFFFE,
            "message_content": {"opcode": 0xFFFFFFFE, "body": ""},
        },
    }
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        session_factory=_FakeSessionFactory([deal]),  # type: ignore[arg-type]
        http_client=_FakeHttp({"transactions": [row]}),
        lite_client_factory=lambda: object(),
    )

    batch = await provider.scan_events(cursor=None, limit=5)

    assert len(batch.events) == 1
    event = batch.events[0]
    assert event.event_type is EscrowChainEventType.OUTBOUND_ACTION_BOUNCED
    assert event.phase == "bounce"
    assert event.attempt_id is None
    assert event.query_id is None
    assert event.operation_id == "0xfffffffe"
    # Enrichment with a proof-decoded attempt must not change the dedup identity.
    from dataclasses import replace
    assert replace(event, attempt_id="42", query_id="42").event_key == event.event_key
    await provider.close()
