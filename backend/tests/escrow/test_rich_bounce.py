from __future__ import annotations

from typing import Any

import pytest
from pytoniq_core import Address, Cell, begin_cell

from app.escrow.rich_bounce import (
    CLASSIC_BOUNCE_OPCODE,
    NFT_FORWARD_MAGIC,
    NFT_TRANSFER_OPCODE,
    RICH_BOUNCE_OPCODE,
    RichBounceParseError,
    match_rich_bounce_to_action,
    parse_rich_bounce_body,
)


SALT = "01" * 32
ITEM = "0:" + "44" * 32
CONTRACT = "0:" + "aa" * 32
SELLER = "0:" + "11" * 32
BUYER = "0:" + "22" * 32


def _nft_transfer_body(*, query_id: int = 42, salt: str = SALT) -> Cell:
    # Matches DealEscrow's TEP-62 body: null custom payload and inline
    # 0 | NFT_FORWARD_MAGIC | deal_salt forward payload.
    return (
        begin_cell()
        .store_uint(NFT_TRANSFER_OPCODE, 32)
        .store_uint(query_id, 64)
        .store_address(Address(BUYER))
        .store_address(Address(BUYER))
        .store_bit(0)
        .store_coins(10_000_000)
        .store_bit(0)
        .store_bit(0)
        .store_uint(NFT_FORWARD_MAGIC, 32)
        .store_uint(int(salt, 16), 256)
        .end_cell()
    )


def _rich_bounce(
    original_body: Cell,
    *,
    value: int = 90_000_000,
    created_lt: int = 300,
    phase: int = 2,
    exit_code: int = 37,
    extra_currencies: bool = False,
) -> Cell:
    info_builder = begin_cell().store_coins(value).store_bit(int(extra_currencies))
    if extra_currencies:
        info_builder.store_ref(begin_cell().end_cell())
    info = (
        info_builder
        .store_uint(created_lt, 64)
        .store_uint(1_700_000_000, 32)
        .end_cell()
    )
    builder = (
        begin_cell()
        .store_uint(RICH_BOUNCE_OPCODE, 32)
        .store_ref(original_body)
        .store_ref(info)
        .store_uint(phase, 8)
        .store_int(exit_code, 32)
        .store_bit(int(phase != 0))
    )
    if phase != 0:
        builder.store_uint(1200, 32).store_uint(900, 32)
    # Round-trip through BOC; tests exercise real TON cell serialization.
    return Cell.one_from_boc(builder.end_cell().to_boc(hash_crc32=True))


def _nft_descriptor(body: Cell, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "slot": "first",
        "kind": 1,
        "query_id": 42,
        "deal_salt": SALT,
        "attempt_id": 42,
        "amount_nanotons": 80_000_000,
        "message_value_nanotons": 90_000_000,
        "expected_state": 4,
        "expected_pending_action": 0,
        "retry_window_seconds": 0,
        "message_body_hash": body.get_hash(0).hex(),
        "status": 1,
        "bounce_phase": 2,
        "exit_code": 37,
        "item_address": ITEM,
        "destination_address": ITEM,
        "recipient_address": BUYER,
        "response_address": BUYER,
    }
    values.update(overrides)
    return values


def _match(
    envelope: Any,
    action: dict[str, Any],
    *,
    sender: str = ITEM,
    current_state: str = "manual_review",
    transaction_lt: int = 500,
):
    return match_rich_bounce_to_action(
        envelope,
        [action],
        bounce_sender=sender,
        contract_address=CONTRACT,
        transaction_lt=transaction_lt,
        deal_salt=SALT,
        item_address=ITEM,
        seller_address=SELLER,
        buyer_address=BUYER,
        principal_nanotons=2_500_000_000,
        seller_deployment_refund_nanotons=50_000_000,
        nft_transfer_value_nanotons=80_000_000,
        recovery_item_address=None,
        recovery_previous_owner=None,
        current_contract_state=current_state,
    )


@pytest.mark.parametrize("phase", [0, 1, 2])
def test_rich_bounce_roundtrips_real_boc_and_parses_tlb_fields(phase: int) -> None:
    original = _nft_transfer_body()
    bounce = _rich_bounce(
        original,
        phase=phase,
        exit_code=-3 if phase == 0 else 37,
    )
    decoded = parse_rich_bounce_body(bounce)

    assert decoded.original_body_hash == original.get_hash(0).hex()
    assert decoded.original_value_nanotons == 90_000_000
    assert decoded.original_created_lt == 300
    assert decoded.original_created_at == 1_700_000_000
    assert decoded.bounced_by_phase == phase
    assert decoded.exit_code == (-3 if phase == 0 else 37)
    if phase == 0:
        assert decoded.gas_used is None
        assert decoded.vm_steps is None
    else:
        assert decoded.gas_used == 1200
        assert decoded.vm_steps == 900


def test_malformed_or_classic_bounce_is_not_parsed_as_rich() -> None:
    malformed = begin_cell().store_uint(RICH_BOUNCE_OPCODE, 32).end_cell()
    with pytest.raises(RichBounceParseError):
        parse_rich_bounce_body(malformed)

    classic = begin_cell().store_uint(CLASSIC_BOUNCE_OPCODE, 32).store_uint(0, 256).end_cell()
    with pytest.raises(RichBounceParseError):
        parse_rich_bounce_body(classic)


def test_match_requires_exact_proof_read_action_descriptor() -> None:
    original = _nft_transfer_body()
    envelope = parse_rich_bounce_body(_rich_bounce(original))
    action = _nft_descriptor(original)

    matched, reason = _match(envelope, action)

    assert reason is None
    assert matched is action


@pytest.mark.parametrize(
    ("overrides", "sender", "state", "lt", "expected_reason"),
    [
        ({"message_body_hash": "ff" * 32}, ITEM, "manual_review", 500,
         "outbound_action_descriptor_not_found"),
        ({}, SELLER, "manual_review", 500,
         "bounce_sender_does_not_match_outbound_destination"),
        ({"status": 0}, ITEM, "manual_review", 500,
         "outbound_action_not_marked_bounced_by_contract"),
        ({"message_value_nanotons": 1}, ITEM, "manual_review", 500,
         "bounce_original_value_mismatch"),
        ({"bounce_phase": 1}, ITEM, "manual_review", 500,
         "bounce_phase_differs_from_contract_descriptor"),
        ({"exit_code": 1}, ITEM, "manual_review", 500,
         "bounce_exit_code_differs_from_contract_descriptor"),
        ({}, ITEM, "nft_release_pending", 500,
         "critical_bounce_not_reflected_in_manual_review_state"),
        ({}, ITEM, "manual_review", 100,
         "bounce_original_logical_time_is_not_earlier"),
    ],
)
def test_correlator_fails_closed_for_stale_or_conflicting_bounces(
    overrides: dict[str, Any],
    sender: str,
    state: str,
    lt: int,
    expected_reason: str,
) -> None:
    original = _nft_transfer_body()
    envelope = parse_rich_bounce_body(_rich_bounce(original))
    action = _nft_descriptor(original, **overrides)

    matched, reason = _match(
        envelope, action, sender=sender, current_state=state, transaction_lt=lt
    )

    assert matched is None
    assert reason == expected_reason


def test_execution_reserve_refund_uses_carry_all_value_exception() -> None:
    settlement = (
        begin_cell()
        .store_uint(77, 64)
        .store_uint(int(SALT, 16), 256)
        .store_uint(6, 8)
        .end_cell()
    )
    envelope = parse_rich_bounce_body(
        _rich_bounce(settlement, value=250_000_000, phase=1, exit_code=37)
    )
    action = {
        "slot": "second",
        "kind": 7,
        "query_id": 77,
        "deal_salt": SALT,
        "attempt_id": 77,
        "amount_nanotons": 0,
        "message_value_nanotons": 0,
        "expected_state": 11,
        "expected_pending_action": 0,
        "retry_window_seconds": 0,
        "message_body_hash": settlement.get_hash(0).hex(),
        "status": 1,
        "bounce_phase": 1,
        "exit_code": 37,
        "item_address": ITEM,
        "destination_address": BUYER,
        "recipient_address": BUYER,
        "response_address": BUYER,
    }

    matched, reason = match_rich_bounce_to_action(
        envelope,
        [action],
        bounce_sender=BUYER,
        contract_address=CONTRACT,
        transaction_lt=500,
        deal_salt=SALT,
        item_address=ITEM,
        seller_address=SELLER,
        buyer_address=BUYER,
        principal_nanotons=2_500_000_000,
        seller_deployment_refund_nanotons=50_000_000,
        nft_transfer_value_nanotons=80_000_000,
        recovery_item_address=None,
        recovery_previous_owner=None,
        current_contract_state="refunded",
    )

    assert reason is None
    assert matched is action


def test_extra_currency_bounce_is_retained_as_unmatched_not_accepted() -> None:
    original = _nft_transfer_body()
    envelope = parse_rich_bounce_body(
        _rich_bounce(original, extra_currencies=True)
    )

    matched, reason = _match(envelope, _nft_descriptor(original))

    assert matched is None
    assert reason == "bounce_contains_unsupported_extra_currencies"



def test_expired_execution_reserve_refund_must_return_to_snapshotted_seller() -> None:
    settlement = (
        begin_cell()
        .store_uint(78, 64)
        .store_uint(int(SALT, 16), 256)
        .store_uint(6, 8)
        .end_cell()
    )
    envelope = parse_rich_bounce_body(
        _rich_bounce(settlement, value=175_000_000, phase=1, exit_code=37)
    )
    action = {
        "slot": "second",
        "kind": 7,
        "query_id": 78,
        "deal_salt": SALT,
        "attempt_id": 78,
        "amount_nanotons": 0,
        "message_value_nanotons": 0,
        "expected_state": 12,
        "expected_pending_action": 0,
        "retry_window_seconds": 0,
        "message_body_hash": settlement.get_hash(0).hex(),
        "status": 1,
        "bounce_phase": 1,
        "exit_code": 37,
        "item_address": ITEM,
        "destination_address": SELLER,
        "recipient_address": SELLER,
        "response_address": SELLER,
    }

    matched, reason = match_rich_bounce_to_action(
        envelope,
        [action],
        bounce_sender=SELLER,
        contract_address=CONTRACT,
        transaction_lt=500,
        deal_salt=SALT,
        item_address=ITEM,
        seller_address=SELLER,
        buyer_address=BUYER,
        principal_nanotons=2_500_000_000,
        seller_deployment_refund_nanotons=50_000_000,
        nft_transfer_value_nanotons=80_000_000,
        recovery_item_address=None,
        recovery_previous_owner=None,
        current_contract_state="expired",
    )

    assert reason is None
    assert matched is action
