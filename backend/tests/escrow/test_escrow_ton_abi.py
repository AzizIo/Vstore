from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from pytoniq_core import Address, Cell, begin_cell

from app.escrow.ton_abi import (
    TONABIError,
    build_storage_cell,
    decode_storage_cell,
    encode_simple_action,
)


def _initial_snapshot() -> SimpleNamespace:
    # Matches scripts/verify_state_init_vector.ts exactly.
    return SimpleNamespace(
        network="testnet",
        network_id=-3,
        protocol_version=1,
        listing_key="01" * 32,
        seller_address="0:" + "11" * 32,
        buyer_address="0:" + "22" * 32,
        collection_address="0:" + "33" * 32,
        item_address="0:" + "44" * 32,
        principal_nanotons=1_000_000_000,
        execution_reserve_nanotons=500_000_000,
        seller_deployment_refund_nanotons=50_000_000,
        nft_transfer_value_nanotons=80_000_000,
        deal_salt="01" * 32,
        activation_query_id=1000,
        fund_query_id=1001,
        nft_deposit_query_id=1002,
        nft_release_query_id=1003,
        nft_return_to_escrow_query_id=1004,
        oracle_key_a=1,
        oracle_key_b=2,
        oracle_key_c=3,
        resolver_key_a=4,
        resolver_key_b=5,
        resolver_key_c=6,
        deployment_value_nanotons=100_000_000,
        activation_value_nanotons=20_000_000,
        action_value_nanotons=20_000_000,
        nft_deposit_value_nanotons=80_000_000,
        nft_return_value_nanotons=80_000_000,
        contract_state=0,
        deadline_unix=0,
        observed_chain_time_unix=0,
        dispute_phase=0,
        nft_in_escrow=False,
        principal_locked=False,
    )


def test_initial_storage_matches_acton_state_init_vector_and_has_empty_action_slots() -> None:
    cell = build_storage_cell(_initial_snapshot())
    assert cell.hash.hex() == (
        "faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b"
    )

    decoded = decode_storage_cell(cell)
    assert decoded["outbound_action_slots"] == [False, False]
    assert decoded["seller_address"] == "0:" + "11" * 32
    assert decoded["buyer_address"] == "0:" + "22" * 32



def test_storage_decoder_reads_both_outbound_action_slots_and_full_descriptor() -> None:
    root = build_storage_cell(_initial_snapshot()).begin_parse()
    terms = root.load_ref()
    initial_progress = root.load_ref()
    progress = initial_progress.begin_parse()
    progress.load_uint(8)
    progress.load_uint(64)
    progress.load_uint(8)
    progress.load_uint(8)
    progress.load_bit()
    progress.load_bit()
    progress.load_uint(64)
    progress.load_uint(64)
    evidence = progress.load_ref()
    recovery = progress.load_ref()

    item = Address("0:" + "44" * 32)
    buyer = Address("0:" + "22" * 32)
    item_pair = begin_cell().store_address(item).store_address(item).end_cell()
    recipient_pair = begin_cell().store_address(buyer).store_address(buyer).end_cell()
    addresses = begin_cell().store_ref(item_pair).store_ref(recipient_pair).end_cell()
    action = (
        begin_cell()
        .store_uint(1, 8)
        .store_uint(42, 64)
        .store_uint(int("01" * 32, 16), 256)
        .store_uint(42, 64)
        .store_coins(80_000_000)
        .store_coins(90_000_000)
        .store_uint(4, 8)
        .store_uint(0, 8)
        .store_uint(1800, 32)
        .store_uint(int("ab" * 32, 16), 256)
        .store_uint(1, 8)
        .store_uint(2, 8)
        .store_int(37, 32)
        .store_ref(addresses)
        .end_cell()
    )
    action_set = begin_cell().store_bit(1).store_ref(action).store_bit(0).end_cell()
    updated_progress = (
        begin_cell()
        .store_uint(0, 8)
        .store_uint(0, 64)
        .store_uint(0, 8)
        .store_uint(0, 8)
        .store_bit(0)
        .store_bit(0)
        .store_uint(0, 64)
        .store_uint(0, 64)
        .store_ref(evidence)
        .store_ref(recovery)
        .store_ref(action_set)
        .end_cell()
    )
    updated_storage = begin_cell().store_ref(terms).store_ref(updated_progress).end_cell()

    decoded = decode_storage_cell(updated_storage)

    assert decoded["outbound_action_slots"] == [True, False]
    assert decoded["outbound_actions"] == [{
        "slot": "first",
        "kind": 1,
        "query_id": 42,
        "deal_salt": "01" * 32,
        "attempt_id": 42,
        "amount_nanotons": 80_000_000,
        "message_value_nanotons": 90_000_000,
        "expected_state": 4,
        "expected_pending_action": 0,
        "retry_window_seconds": 1800,
        "message_body_hash": "ab" * 32,
        "status": 1,
        "bounce_phase": 2,
        "exit_code": 37,
        "item_address": "0:" + "44" * 32,
        "destination_address": "0:" + "44" * 32,
        "recipient_address": "0:" + "22" * 32,
        "response_address": "0:" + "22" * 32,
    }]



def test_retry_failed_outbound_action_uses_contract_opcode_and_exact_fields() -> None:
    payload = encode_simple_action(
        "retry_failed_outbound_action", 0x0102030405060708, int("ab" * 32, 16)
    )
    parser = Cell.one_from_boc(base64.b64decode(payload)).begin_parse()
    assert parser.load_uint(32) == 0x56450009
    assert parser.load_uint(64) == 0x0102030405060708
    assert parser.load_uint(256) == int("ab" * 32, 16)
    assert parser.remaining_bits == 0
    assert parser.remaining_refs == 0


@pytest.mark.parametrize("query_id", [0, -1, 1 << 64])
def test_retry_failed_outbound_action_rejects_invalid_query_id(query_id: int) -> None:
    with pytest.raises(TONABIError):
        encode_simple_action("retry_failed_outbound_action", query_id, 1)
