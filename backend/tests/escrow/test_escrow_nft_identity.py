from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pytoniq_core import Address, begin_cell

from app.core.config import Settings
from app.escrow.finality_provider import PytoniqTONTestnetEscrowProvider
from app.escrow.nft_identity import (
    NFTIdentityEvidenceError,
    cell_hash,
    same_nft_identity_anchor,
    validate_nft_identity_snapshot,
    verify_nft_identity_cells,
)
from app.escrow.provider import EscrowProviderInvalidEvidence
from app.escrow.ton_abi import build_state_init_cell

COLLECTION = "0:" + "c" * 64
OWNER = "0:" + "a" * 64
OTHER_OWNER = "0:" + "b" * 64
OTHER_COLLECTION = "0:" + "d" * 64
DERIVATION = "tep62-standard-nft-collection-v1"
BLOCK_HASH = "1" * 64
INIT_HASH = "2" * 64


def _fixture(
    *,
    item_index: int = 7,
    item_collection: str = COLLECTION,
    owner: str = OWNER,
    item_code_override: Any | None = None,
    collection_item_code_override: Any | None = None,
    item_address_override: str | None = None,
) -> dict[str, Any]:
    collection_code = begin_cell().store_uint(0xCAFE, 16).end_cell()
    item_code = item_code_override or begin_cell().store_uint(0x1234, 16).end_cell()
    collection_item_code = collection_item_code_override or item_code
    collection_content = begin_cell().store_uint(1, 1).end_cell()
    royalty = begin_cell().store_uint(0, 16).end_cell()
    collection_data = (
        begin_cell()
        .store_address(Address(OWNER))
        .store_uint(item_index + 1, 64)
        .store_ref(collection_content)
        .store_ref(collection_item_code)
        .store_ref(royalty)
        .end_cell()
    )
    content = begin_cell().store_uint(3, 2).end_cell()
    item_data = (
        begin_cell()
        .store_uint(item_index, 64)
        .store_address(Address(item_collection))
        .store_address(Address(owner))
        .store_ref(content)
        .end_cell()
    )
    derived_state_data = (
        begin_cell()
        .store_uint(item_index, 64)
        .store_address(Address(item_collection))
        .end_cell()
    )
    derived_state_init = build_state_init_cell(item_code, derived_state_data)
    item_address = item_address_override or Address(
        (0, derived_state_init.get_hash(0))
    ).to_str(is_user_friendly=False)
    policy = {
        "policy_id": "reviewed-testnet-collection-v1",
        "collection_address": COLLECTION,
        "collection_code_hash": cell_hash(collection_code),
        "item_code_hash": cell_hash(item_code),
        "derivation": DERIVATION,
    }
    return {
        "item_address": item_address,
        "collection_address": COLLECTION,
        "item_code": item_code,
        "item_data": item_data,
        "collection_code": collection_code,
        "collection_data": collection_data,
        "policy": policy,
        "policy_list": [policy],
        "item_index": item_index,
    }


def _verify_fixture(fixture: dict[str, Any], *, expected_owner: str | None = OWNER):
    return verify_nft_identity_cells(
        item_address=fixture["item_address"],
        collection_address=fixture["collection_address"],
        item_code=fixture["item_code"],
        item_data=fixture["item_data"],
        collection_code=fixture["collection_code"],
        collection_data=fixture["collection_data"],
        policies=fixture["policy_list"],
        expected_owner_address=expected_owner,
        masterchain_seqno=500,
        masterchain_block_hash=BLOCK_HASH,
        trusted_init_key_block_hash=INIT_HASH,
        observed_chain_time_unix=1_800_000_000,
        provider_id="pytoniq-trust0-testnet-v1",
    )


def test_identity_proof_binds_item_collection_code_and_policy_to_one_mc_block() -> None:
    fixture = _fixture()

    evidence = _verify_fixture(fixture)

    validated = validate_nft_identity_snapshot(evidence, evidence["evidence_sha256"])
    assert validated["item_address"] == fixture["item_address"]
    assert validated["collection_address"] == COLLECTION
    assert validated["owner_address"] == OWNER
    assert validated["item_index"] == 7
    assert validated["derived_item_address"] == fixture["item_address"]
    assert validated["policy"]["policy_id"] == "reviewed-testnet-collection-v1"
    assert evidence["masterchain_seqno"] == 500
    assert len(str(evidence["evidence_sha256"])) == 64


def test_identity_rejects_unallowlisted_collection() -> None:
    fixture = _fixture()
    fixture["policy_list"] = []

    with pytest.raises(NFTIdentityEvidenceError, match="No escrow NFT collection policy"):
        _verify_fixture(fixture)


def test_identity_rejects_item_claiming_a_different_collection() -> None:
    fixture = _fixture(item_collection=OTHER_COLLECTION)

    with pytest.raises(NFTIdentityEvidenceError, match="item's proof-read collection"):
        _verify_fixture(fixture)


def test_identity_rejects_same_index_but_wrong_item_address() -> None:
    fixture = _fixture(item_address_override="0:" + "e" * 64)

    with pytest.raises(NFTIdentityEvidenceError, match="address derivation"):
        _verify_fixture(fixture)


def test_identity_rejects_unapproved_item_code_hash() -> None:
    fixture = _fixture(item_code_override=begin_cell().store_uint(0x8888, 16).end_cell())
    fixture["policy"]["item_code_hash"] = cell_hash(
        begin_cell().store_uint(0x1234, 16).end_cell()
    )

    with pytest.raises(NFTIdentityEvidenceError, match="item contract code hash"):
        _verify_fixture(fixture)


def test_identity_rejects_collection_item_code_mismatch() -> None:
    other_item_code = begin_cell().store_uint(0x9999, 16).end_cell()
    fixture = _fixture(collection_item_code_override=other_item_code)

    with pytest.raises(NFTIdentityEvidenceError, match="stored NFT item code"):
        _verify_fixture(fixture)


def test_identity_rejects_owner_mismatch_and_stale_snapshot_hash() -> None:
    fixture = _fixture()

    with pytest.raises(NFTIdentityEvidenceError, match="current owner differs"):
        _verify_fixture(fixture, expected_owner=OTHER_OWNER)

    evidence = _verify_fixture(fixture)
    tampered = dict(evidence)
    tampered["owner_address"] = OTHER_OWNER
    with pytest.raises(NFTIdentityEvidenceError, match="hash mismatch"):
        validate_nft_identity_snapshot(tampered, evidence["evidence_sha256"])


def test_identity_rejects_duplicate_or_wrong_collection_policy() -> None:
    fixture = _fixture()
    fixture["policy_list"] = [fixture["policy"], fixture["policy"]]

    with pytest.raises(NFTIdentityEvidenceError, match="Duplicate NFT collection"):
        _verify_fixture(fixture)

    fixture["policy_list"] = [
        {**fixture["policy"], "collection_address": OTHER_COLLECTION}
    ]
    with pytest.raises(NFTIdentityEvidenceError, match="not explicitly allowlisted"):
        _verify_fixture(fixture)


def test_identity_anchor_allows_owner_and_block_to_change_but_not_code_or_policy() -> None:
    fixture = _fixture()
    initial = _verify_fixture(fixture)
    current_fixture = _fixture(owner=OTHER_OWNER)
    current = _verify_fixture(current_fixture, expected_owner=OTHER_OWNER)

    assert same_nft_identity_anchor(initial, current) is True

    different_policy = dict(current)
    different_policy["policy_sha256"] = "f" * 64
    assert same_nft_identity_anchor(initial, different_policy) is False


class _FakeLiteClient:
    trust_level = 0

    def __init__(self, item: dict[str, Any]) -> None:
        self.block = SimpleNamespace(seqno=500, root_hash=bytes.fromhex(BLOCK_HASH))
        self.last_mc_block = self.block
        self.init_key_block = SimpleNamespace(root_hash=bytes.fromhex(INIT_HASH))
        self.item = item
        self.reads: list[tuple[str, object]] = []
        self.closed = False

    async def connect(self) -> None:
        return None

    async def get_trusted_last_mc_block(self):
        return self.block

    async def raw_get_account_state(self, address: str, *, block: object):
        self.reads.append((address, block))
        if address == self.item["item_address"]:
            code, data = self.item["item_code"], self.item["item_data"]
        elif address == self.item["collection_address"]:
            code, data = self.item["collection_code"], self.item["collection_data"]
        else:
            raise AssertionError("Unexpected account read")
        account = SimpleNamespace(
            storage=SimpleNamespace(
                state=SimpleNamespace(
                    type_="account_active",
                    state_init=SimpleNamespace(code=code, data=data),
                )
            )
        )
        return account, None

    async def raw_get_block(self, block: object):
        assert block is self.block
        return SimpleNamespace(info=SimpleNamespace(gen_utime=1_800_000_000))

    async def close(self) -> None:
        self.closed = True


class _FakeHttp:
    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_provider_reads_item_and_collection_at_the_same_trusted_block() -> None:
    fixture = _fixture()
    fake_client = _FakeLiteClient(fixture)
    settings = Settings(
        _env_file=None,
        environment="test",
        ton_connect_network="testnet",
        ton_center_testnet_base_url="https://testnet.toncenter.com/api/v3",
        ton_center_timeout_seconds=2,
        ton_escrow_nft_collection_policies=fixture["policy_list"],
    )
    provider = PytoniqTONTestnetEscrowProvider(
        settings=settings,
        http_client=_FakeHttp(),
        lite_client_factory=lambda: fake_client,
    )

    evidence = await provider.verify_nft_identity(
        item_address=fixture["item_address"],
        collection_address=fixture["collection_address"],
        expected_owner_address=OWNER,
    )

    assert evidence is not None
    assert len(fake_client.reads) == 2
    assert fake_client.reads[0][1] is fake_client.block
    assert fake_client.reads[1][1] is fake_client.block
    assert fake_client.reads[0][1] is fake_client.reads[1][1]
    assert evidence["masterchain_block_hash"] == BLOCK_HASH
    await provider.close()
    assert fake_client.closed


@pytest.mark.asyncio
async def test_provider_returns_no_owner_proof_when_owner_changed() -> None:
    fixture = _fixture(owner=OTHER_OWNER)
    fake_client = _FakeLiteClient(fixture)
    settings = Settings(
        _env_file=None,
        environment="test",
        ton_connect_network="testnet",
        ton_center_testnet_base_url="https://testnet.toncenter.com/api/v3",
        ton_center_timeout_seconds=2,
        ton_escrow_nft_collection_policies=fixture["policy_list"],
    )
    provider = PytoniqTONTestnetEscrowProvider(
        settings=settings,
        http_client=_FakeHttp(),
        lite_client_factory=lambda: fake_client,
    )

    evidence = await provider.verify_nft_identity(
        item_address=fixture["item_address"],
        collection_address=fixture["collection_address"],
        expected_owner_address=OWNER,
    )

    assert evidence is None
    await provider.close()


@pytest.mark.asyncio
async def test_provider_fails_closed_when_collection_policy_is_missing() -> None:
    fixture = _fixture()
    fake_client = _FakeLiteClient(fixture)
    settings = Settings(
        _env_file=None,
        environment="test",
        ton_connect_network="testnet",
        ton_center_testnet_base_url="https://testnet.toncenter.com/api/v3",
        ton_center_timeout_seconds=2,
        ton_escrow_nft_collection_policies=[],
    )
    provider = PytoniqTONTestnetEscrowProvider(
        settings=settings,
        http_client=_FakeHttp(),
        lite_client_factory=lambda: fake_client,
    )

    with pytest.raises(EscrowProviderInvalidEvidence, match="No escrow NFT collection policy"):
        await provider.verify_nft_identity(
            item_address=fixture["item_address"],
            collection_address=fixture["collection_address"],
            expected_owner_address=OWNER,
        )
    await provider.close()
