from __future__ import annotations

from types import SimpleNamespace

from app.escrow.ton_abi import build_storage_cell, decode_storage_cell


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
