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


def _retry_descriptor(
    *,
    query_id: int = 42,
    kind: int = 4,
    recipient: str = "0:" + "b" * 64,
    deal_salt: str = "c" * 64,
    status: int = 1,
    retry_window_seconds: int = 1800,
    amount_nanotons: int = 90_000_000,
) -> dict[str, object]:
    return {
        "slot": "first",
        "kind": kind,
        "query_id": query_id,
        "deal_salt": deal_salt,
        "attempt_id": 7,
        "amount_nanotons": amount_nanotons,
        "message_value_nanotons": amount_nanotons,
        "expected_state": 10,
        "expected_pending_action": 0,
        "retry_window_seconds": retry_window_seconds,
        "message_body_hash": "d" * 64,
        "status": status,
        "bounce_phase": 1,
        "exit_code": 37,
        "item_address": "0:" + "a" * 64,
        "destination_address": recipient,
        "recipient_address": recipient,
        "response_address": recipient,
    }


class _FakeRetryLiteClient:
    trust_level = 0

    def __init__(self) -> None:
        from pytoniq_core import begin_cell

        data = begin_cell().store_uint(1, 1).end_cell()
        self.account = SimpleNamespace(
            storage=SimpleNamespace(
                state=SimpleNamespace(
                    type_="account_active",
                    state_init=SimpleNamespace(data=data),
                )
            )
        )
        self.masterchain = SimpleNamespace(seqno=700, root_hash=b"m" * 32)

    async def get_trusted_last_mc_block(self):
        return self.masterchain

    async def raw_get_account_state(self, _address: str, *, block: object):
        return self.account, object()

    async def raw_get_block(self, _block: object):
        return SimpleNamespace(info=SimpleNamespace(gen_utime=1_700_000_100))


@pytest.mark.asyncio
async def test_current_retry_proof_accepts_terminal_refund_zero_window(monkeypatch) -> None:
    deal = _deal()
    descriptor = _retry_descriptor(kind=6, retry_window_seconds=0)
    client = _FakeRetryLiteClient()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )
    async def get_client():
        return client

    async def read_state(_deal, _masterchain, _client):
        return ({
            "outbound_actions": [descriptor],
            "deadline_unix": 0,
            "observed_chain_time_unix": 1_700_000_100,
        }, "settled", "getter-identity")

    monkeypatch.setattr(provider, "_get_lite_client", get_client)
    monkeypatch.setattr(provider, "_read_contract_state", read_state)

    proofs = await provider.read_current_outbound_retry_proofs(deal)

    assert len(proofs) == 1
    assert proofs[0].action.kind == 6
    assert proofs[0].action.retry_window_seconds == 0
    assert proofs[0].masterchain_seqno == 700
    assert proofs[0].masterchain_block_hash == (b"m" * 32).hex()


@pytest.mark.asyncio
async def test_current_retry_proof_blocks_execution_reserve_until_seller_allowance_retry(monkeypatch) -> None:
    deal = _deal()
    seller_allowance = _retry_descriptor(
        query_id=42, kind=6, retry_window_seconds=0,
        recipient="0:" + "b" * 64,
    )
    execution_reserve = _retry_descriptor(
        query_id=43, kind=7, retry_window_seconds=0,
        recipient="0:" + "c" * 64, amount_nanotons=0,
    )
    client = _FakeRetryLiteClient()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    async def get_client():
        return client

    async def read_state(_deal, _masterchain, _client):
        return ({
            "outbound_actions": [seller_allowance, execution_reserve],
            "deadline_unix": 0,
            "observed_chain_time_unix": 1_700_000_100,
        }, "refunded", "getter-identity")

    monkeypatch.setattr(provider, "_get_lite_client", get_client)
    monkeypatch.setattr(provider, "_read_contract_state", read_state)

    proofs = await provider.read_current_outbound_retry_proofs(deal)

    assert [proof.action.kind for proof in proofs] == [6]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("descriptor", "deadline"),
    [
        (_retry_descriptor(kind=4, retry_window_seconds=1799), 1_700_000_200),
        (_retry_descriptor(kind=6, retry_window_seconds=1800), 0),
        (_retry_descriptor(kind=7, retry_window_seconds=1), 0),
        (_retry_descriptor(kind=4, amount_nanotons=0), 1_700_000_200),
    ],
)
async def test_current_retry_proof_rejects_invalid_or_expired_retry_window(
    monkeypatch, descriptor: dict[str, object], deadline: int
) -> None:
    deal = _deal()
    client = _FakeRetryLiteClient()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    async def get_client():
        return client

    async def read_state(_deal, _masterchain, _client):
        return ({
            "outbound_actions": [descriptor],
            "deadline_unix": deadline,
            "observed_chain_time_unix": 1_700_000_100,
        }, "settled", "getter-identity")

    monkeypatch.setattr(provider, "_get_lite_client", get_client)
    monkeypatch.setattr(provider, "_read_contract_state", read_state)

    assert await provider.read_current_outbound_retry_proofs(deal) == ()


@pytest.mark.asyncio
async def test_current_retry_proof_rejects_duplicate_query_ids_and_noncanonical_recipient(
    monkeypatch,
) -> None:
    from pytoniq_core import Address

    deal = _deal()
    first = _retry_descriptor(query_id=42)
    second = _retry_descriptor(query_id=42)
    noncanonical = _retry_descriptor(
        query_id=43,
        recipient=Address("0:" + "b" * 64).to_str(is_user_friendly=True),
    )
    client = _FakeRetryLiteClient()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    async def get_client():
        return client

    async def read_state(_deal, _masterchain, _client):
        return ({
            "outbound_actions": [first, second, noncanonical],
            "deadline_unix": 1_700_000_200,
            "observed_chain_time_unix": 1_700_000_100,
        }, "settled", "getter-identity")

    monkeypatch.setattr(provider, "_get_lite_client", get_client)
    monkeypatch.setattr(provider, "_read_contract_state", read_state)

    assert await provider.read_current_outbound_retry_proofs(deal) == ()


@pytest.mark.asyncio
async def test_current_retry_proof_accepts_zero_value_execution_reserve_when_unblocked(
    monkeypatch,
) -> None:
    deal = _deal()
    descriptor = _retry_descriptor(
        query_id=43, kind=7, retry_window_seconds=0, amount_nanotons=0,
    )
    client = _FakeRetryLiteClient()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    async def get_client():
        return client

    async def read_state(_deal, _masterchain, _client):
        return ({
            "outbound_actions": [descriptor],
            "deadline_unix": 0,
            "observed_chain_time_unix": 1_700_000_100,
        }, "refunded", "getter-identity")

    monkeypatch.setattr(provider, "_get_lite_client", get_client)
    monkeypatch.setattr(provider, "_read_contract_state", read_state)

    proofs = await provider.read_current_outbound_retry_proofs(deal)

    assert len(proofs) == 1
    assert proofs[0].action.kind == 7
    assert proofs[0].action.amount_nanotons == 0
    assert proofs[0].action.message_value_nanotons == 0


@pytest.mark.asyncio
async def test_bounced_lifecycle_action_is_not_hidden_when_contract_clears_deadline(
    monkeypatch,
) -> None:
    deal = _deal()
    descriptor = _retry_descriptor(kind=4, retry_window_seconds=1800)
    client = _FakeRetryLiteClient()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    async def get_client():
        return client

    async def read_state(_deal, _masterchain, _client):
        return ({
            "outbound_actions": [descriptor],
            "deadline_unix": 0,
            "observed_chain_time_unix": 1_700_000_100,
        }, "manual_review", "getter-identity")

    monkeypatch.setattr(provider, "_get_lite_client", get_client)
    monkeypatch.setattr(provider, "_read_contract_state", read_state)

    proofs = await provider.read_current_outbound_retry_proofs(deal)

    assert len(proofs) == 1
    assert proofs[0].action.kind == 4


@pytest.mark.asyncio
async def test_current_retry_proof_rejects_getter_time_not_bound_to_proved_masterchain_block(
    monkeypatch,
) -> None:
    deal = _deal()
    client = _FakeRetryLiteClient()
    provider = PytoniqTONTestnetEscrowProvider(
        settings=_settings(),
        http_client=_FakeHttp({"transactions": []}),
        lite_client_factory=lambda: client,
    )

    async def get_client():
        return client

    async def read_state(_deal, _masterchain, _client):
        return ({
            "outbound_actions": [_retry_descriptor(kind=6, retry_window_seconds=0)],
            "deadline_unix": 0,
            "observed_chain_time_unix": 1_700_000_101,
        }, "refunded", "getter-identity")

    monkeypatch.setattr(provider, "_get_lite_client", get_client)
    monkeypatch.setattr(provider, "_read_contract_state", read_state)

    with pytest.raises(EscrowProviderInvalidEvidence, match="retry time fields"):
        await provider.read_current_outbound_retry_proofs(deal)
