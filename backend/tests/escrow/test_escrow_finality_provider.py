from __future__ import annotations

import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pytoniq_core.tl.block import BlockIdExt

from app.core.config import Settings
from app.escrow.domain import EscrowChainEventType
from app.escrow.finality_provider import (
    PytoniqTONTestnetEscrowProvider,
    _candidate_type,
    _parse_shard,
)
from app.escrow.provider import (
    EscrowProviderInvalidEvidence,
    EscrowProviderUnavailable,
    NormalizedChainEvent,
)


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
    # Indexer fields are not durable correlation facts. Keep them empty until
    # the LiteServer proof and on-chain outbound descriptor enrich this event.
    assert event.source_address is None
    assert event.destination_address is None
    assert event.amount_nanotons is None
    assert event.attempt_id is None
    assert event.query_id is None
    assert event.operation_id == "0xfffffffe"
    # Enrichment with a proof-decoded attempt must not change the dedup identity.
    from dataclasses import replace
    assert replace(event, attempt_id="42", query_id="42").event_key == event.event_key
    await provider.close()



class _FakeOriginalOutboundMessage:
    def __init__(self, body: object, info: object) -> None:
        self.is_internal = True
        self.body = body
        self.info = info

    def serialize(self):
        from pytoniq_core import begin_cell

        return (
            begin_cell()
            .store_address(self.info.src)
            .store_address(self.info.dest)
            .store_uint(self.info.created_lt, 64)
            .store_uint(self.info.created_at, 32)
            .store_coins(self.info.value_coins)
            .store_ref(self.body)
            .end_cell()
        )


class _FakeOriginalOutboundLiteClient:
    def __init__(self, transaction: object, block_id: object) -> None:
        self.transaction = transaction
        self.block_id = block_id
        self.account_state_block = None
        self.block_proof_requested = False

    async def raw_get_account_state(self, _address: object, *, block: object):
        self.account_state_block = block
        return object(), SimpleNamespace(
            last_trans_lt=500,
            last_trans_hash=b"h" * 32,
        )

    async def raw_get_transactions(
        self, _address: object, count: int, from_lt: int, from_hash: bytes
    ):
        assert count == 16
        assert from_lt == 500
        assert from_hash == b"h" * 32
        return [self.transaction], [self.block_id]

    async def raw_get_block_transactions_ext(self, block_id: object, *, count: int):
        assert block_id is self.block_id
        assert count == 1024
        self.block_proof_requested = True
        return [self.transaction]


def _original_outbound_fixture(*, value: int = 90_000_000):
    from pytoniq_core import Address, begin_cell

    contract_address = "0:" + "aa" * 32
    destination_address = "0:" + "bb" * 32
    created_lt = 400
    created_at = 1_700_000_001
    body = (
        begin_cell()
        .store_uint(0x5FCC3D14, 32)
        .store_uint(42, 64)
        .store_address(Address(destination_address))
        .store_address(Address(destination_address))
        .store_bit(0)
        .store_coins(10_000_000)
        .store_bit(0)
        .store_uint(0x56454E46, 32)
        .store_uint(int("cc" * 32, 16), 256)
        .end_cell()
    )
    info = SimpleNamespace(
        src=Address(contract_address),
        dest=Address(destination_address),
        created_lt=created_lt,
        created_at=created_at,
        value_coins=value,
        bounce=True,
        bounced=False,
    )
    message = _FakeOriginalOutboundMessage(body, info)
    transaction = SimpleNamespace(
        account_addr_hex=Address(contract_address).hash_part.hex(),
        lt=created_lt,
        now=created_at,
        prev_trans_lt=300,
        prev_trans_hash=b"p" * 32,
        cell=begin_cell().store_uint(0x77, 8).end_cell(),
        out_msgs=[message],
    )
    block_id = SimpleNamespace(root_hash=b"r" * 32, seqno=777)
    client = _FakeOriginalOutboundLiteClient(transaction, block_id)
    masterchain_id = object()
    action = {
        "destination_address": destination_address,
        "message_body_hash": body.get_hash(0).hex(),
    }
    bounce_details = {
        "bounce_original_created_lt": created_lt,
        "bounce_original_created_at": created_at,
        "bounce_original_body_hash": body.get_hash(0).hex(),
        "bounce_original_value_nanotons": value,
    }
    return client, masterchain_id, contract_address, action, bounce_details, transaction, block_id


@pytest.mark.asyncio
async def test_original_outbound_message_is_bound_to_account_history_and_proved_block() -> None:
    (
        client,
        masterchain_id,
        contract_address,
        action,
        bounce_details,
        transaction,
        block_id,
    ) = _original_outbound_fixture()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: object(),
    )

    proof, reason = await provider._verify_original_outbound_message(
        client,
        contract_address=contract_address,
        masterchain_id=masterchain_id,
        action=action,
        bounce_details=bounce_details,
    )

    assert reason is None
    assert proof is not None
    assert proof["outbound_transaction_hash"] == transaction.cell.get_hash(0).hex()
    assert proof["outbound_block_hash"] == block_id.root_hash.hex()
    assert proof["outbound_block_seqno"] == block_id.seqno
    assert proof["outbound_message_hash"] == transaction.out_msgs[0].serialize().get_hash(0).hex()
    assert client.account_state_block is masterchain_id
    assert client.block_proof_requested is True
    await provider.close()


@pytest.mark.asyncio
async def test_original_outbound_message_rejects_value_or_message_mismatch() -> None:
    (
        client,
        masterchain_id,
        contract_address,
        action,
        bounce_details,
        _transaction,
        _block_id,
    ) = _original_outbound_fixture(value=89_000_000)
    # The bounce claims 90m, but the proved source message contains only 89m.
    bounce_details["bounce_original_value_nanotons"] = 90_000_000
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: object(),
    )

    proof, reason = await provider._verify_original_outbound_message(
        client,
        contract_address=contract_address,
        masterchain_id=masterchain_id,
        action=action,
        bounce_details=bounce_details,
    )

    assert proof is None
    assert reason == "original_outbound_message_info_mismatch"

    (
        client,
        masterchain_id,
        contract_address,
        action,
        bounce_details,
        _transaction,
        _block_id,
    ) = _original_outbound_fixture()
    bounce_details["bounce_original_body_hash"] = "ff" * 32
    proof, reason = await provider._verify_original_outbound_message(
        client,
        contract_address=contract_address,
        masterchain_id=masterchain_id,
        action=action,
        bounce_details=bounce_details,
    )
    assert proof is None
    assert reason == "original_outbound_message_not_uniquely_in_source_transaction"
    await provider.close()


def _block_id(
    workchain: int,
    shard: int,
    seqno: int,
    root_byte: int,
    file_byte: int,
) -> BlockIdExt:
    return BlockIdExt(
        workchain=workchain,
        shard=shard,
        seqno=seqno,
        root_hash=bytes([root_byte]) * 32,
        file_hash=bytes([file_byte]) * 32,
    )


class _FinalityProofClient:
    def __init__(
        self,
        *,
        shard_block: BlockIdExt | None = None,
        master_block: BlockIdExt | None = None,
        latest_seqno: int | None = None,
        validator_proof_error: Exception | None = None,
        shard_proof_error: Exception | None = None,
    ) -> None:
        self.shard_block = shard_block or _block_id(0, -(1 << 63), 100, 1, 2)
        self.master_block = master_block or _block_id(-1, -(1 << 63), 300, 3, 4)
        self.last_key_block = _block_id(-1, -(1 << 63), 250, 5, 6)
        self.latest = _block_id(
            -1,
            -(1 << 63),
            latest_seqno if latest_seqno is not None else self.master_block.seqno + 2,
            7,
            8,
        )
        self.validator_proof_error = validator_proof_error
        self.shard_proof_error = shard_proof_error
        self.lookup_calls: list[tuple[int, int, int]] = []
        self.master_proof_calls: list[tuple[object, object]] = []
        self.shard_proof_calls: list[tuple[object, bool]] = []

    async def lookup_block(self, workchain: int, shard: int, seqno: int):
        self.lookup_calls.append((workchain, shard, seqno))
        return self.shard_block, None

    async def liteserver_request(self, schema: str, data: dict[str, object]):
        assert schema == "getShardBlockProof"
        assert data["id"] == self.shard_block.to_dict()
        return {"masterchain_id": self.master_block.to_dict()}

    async def get_mc_block_proof(self, *, known_block: object, target_block: object):
        self.master_proof_calls.append((known_block, target_block))
        if self.validator_proof_error is not None:
            raise self.validator_proof_error

    async def get_shard_block_proof(self, block: object, prove_mc: bool = False):
        self.shard_proof_calls.append((block, prove_mc))
        if self.shard_proof_error is not None:
            raise self.shard_proof_error

    async def get_trusted_last_mc_block(self):
        return self.latest


def _finality_candidate(
    *, masterchain_seqno: int = 300, block_seqno: int = 100, shard: int = -(1 << 63)
) -> NormalizedChainEvent:
    return NormalizedChainEvent(
        network="testnet",
        transaction_hash="a" * 64,
        event_index=0,
        event_type=EscrowChainEventType.NFT_DEPOSIT_ACCEPTED,
        contract_address="0:" + "b" * 64,
        deal_id=str(uuid4()),
        source_address=None,
        destination_address=None,
        item_address="0:" + "c" * 64,
        amount_nanotons=None,
        masterchain_seqno=masterchain_seqno,
        finalized=True,
        evidence_sha256="d" * 64,
        cursor="candidate",
        message_hash="e" * 64,
        trace_id="f" * 64,
        logical_time=123,
        candidate_workchain=0,
        candidate_shard=shard,
        candidate_block_seqno=block_seqno,
    )


@pytest.mark.asyncio
async def test_finality_requires_trusted_mc_and_shard_inclusion_proofs() -> None:
    client = _FinalityProofClient()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    shard, master, latest = await provider._trusted_shard_and_masterchain(
        _finality_candidate(), client
    )

    assert shard is client.shard_block
    assert master.to_dict() == client.master_block.to_dict()
    assert latest.seqno == 302
    assert client.lookup_calls == [(0, -(1 << 63), 100)]
    assert client.master_proof_calls == [(client.last_key_block, client.master_block)]
    assert client.shard_proof_calls == [(client.shard_block, True)]
    await provider.close()


@pytest.mark.asyncio
async def test_finality_rejects_shard_block_locator_mismatch() -> None:
    client = _FinalityProofClient(
        shard_block=_block_id(0, -(1 << 63), 101, 9, 10)
    )
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    with pytest.raises(EscrowProviderInvalidEvidence, match="different shard block"):
        await provider._trusted_shard_and_masterchain(_finality_candidate(), client)
    assert client.master_proof_calls == []
    await provider.close()


@pytest.mark.asyncio
async def test_finality_rejects_masterchain_sequence_conflicting_with_candidate() -> None:
    client = _FinalityProofClient()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    with pytest.raises(
        EscrowProviderInvalidEvidence,
        match="Indexed masterchain sequence does not match",
    ):
        await provider._trusted_shard_and_masterchain(
            _finality_candidate(masterchain_seqno=301), client
        )
    await provider.close()


@pytest.mark.asyncio
async def test_finality_stays_pending_until_configured_masterchain_depth() -> None:
    client = _FinalityProofClient(latest_seqno=301)
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(ton_escrow_finality_min_depth=2),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    with pytest.raises(EscrowProviderUnavailable, match="configured finality depth"):
        await provider._trusted_shard_and_masterchain(_finality_candidate(), client)
    await provider.close()


@pytest.mark.asyncio
async def test_validator_configuration_proof_failure_is_not_finalized() -> None:
    client = _FinalityProofClient(
        validator_proof_error=ValueError("validator signature/config proof mismatch")
    )
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    with pytest.raises(
        EscrowProviderUnavailable,
        match="Could not verify TON block inclusion proof",
    ):
        await provider._trusted_shard_and_masterchain(_finality_candidate(), client)
    assert client.shard_proof_calls == []
    await provider.close()


@pytest.mark.asyncio
async def test_shard_inclusion_proof_failure_is_not_finalized() -> None:
    client = _FinalityProofClient(
        shard_proof_error=ValueError("shard inclusion merkle proof mismatch")
    )
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    with pytest.raises(
        EscrowProviderUnavailable,
        match="Could not verify TON block inclusion proof",
    ):
        await provider._trusted_shard_and_masterchain(_finality_candidate(), client)
    await provider.close()
