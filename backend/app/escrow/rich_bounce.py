"""Strict parser and correlation rules for TON's new RichBounce body."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RICH_BOUNCE_OPCODE = 0xFFFFFFFE
CLASSIC_BOUNCE_OPCODE = 0xFFFFFFFF
NFT_TRANSFER_OPCODE = 0x5FCC3D14
NFT_FORWARD_MAGIC = 0x56454E46
_STATE_NAMES = {
    0: "intent_created", 1: "awaiting_nft", 2: "awaiting_buyer_funds",
    3: "funded_review", 4: "nft_release_pending", 5: "delivered_dispute_window",
    6: "disputed", 7: "nft_return_pending", 8: "seller_payout_pending",
    9: "buyer_refund_pending", 10: "settled", 11: "refunded",
    12: "expired", 13: "manual_review",
}

class RichBounceParseError(ValueError):
    """The body is not a complete, well-formed TON new_bounce_body."""

@dataclass(frozen=True, slots=True)
class RichBounceEnvelope:
    original_body: Any
    original_body_hash: str
    original_value_nanotons: int
    original_has_extra_currencies: bool
    original_created_lt: int
    original_created_at: int
    bounced_by_phase: int
    exit_code: int
    gas_used: int | None
    vm_steps: int | None

def parse_rich_bounce_body(body: Any) -> RichBounceEnvelope:
    """Decode the exact TL-B new_bounce_body layout from a proof-verified cell."""
    try:
        parser = body.begin_parse()
        if parser.load_uint(32) != RICH_BOUNCE_OPCODE:
            raise ValueError("wrong RichBounce tag")
        if parser.remaining_refs < 2:
            raise ValueError("missing RichBounce references")
        original_body = parser.load_ref()
        original_info_cell = parser.load_ref()
        info = original_info_cell.begin_parse()
        original_value = info.load_coins()
        has_extra = bool(info.load_bit())
        if has_extra:
            info.load_ref()
        created_lt = info.load_uint(64)
        created_at = info.load_uint(32)
        if info.remaining_bits != 0 or info.remaining_refs != 0:
            raise ValueError("original info has trailing data")
        phase = parser.load_uint(8)
        exit_code = parser.load_int(32)
        has_compute = bool(parser.load_bit())
        gas_used = parser.load_uint(32) if has_compute else None
        vm_steps = parser.load_uint(32) if has_compute else None
        if parser.remaining_bits != 0 or parser.remaining_refs != 0:
            raise ValueError("RichBounce body has trailing data")
        if phase not in {0, 1, 2} or (phase == 0) == has_compute:
            raise ValueError("RichBounce phase/compute metadata is inconsistent")
        body_hash = original_body.get_hash(0).hex()
        if len(body_hash) != 64 or created_lt <= 0 or created_at <= 0:
            raise ValueError("original message identity is invalid")
        return RichBounceEnvelope(
            original_body, body_hash, original_value, has_extra, created_lt,
            created_at, phase, exit_code, gas_used, vm_steps,
        )
    except RichBounceParseError:
        raise
    except Exception as exc:
        raise RichBounceParseError("Malformed TON RichBounce body") from exc

def _address(value: Any) -> str:
    return value.to_str(is_user_friendly=False) if value is not None else ""

def _validate_original_body(
    action: dict[str, Any], envelope: RichBounceEnvelope, *,
    deal_salt: str, item_address: str, seller_address: str, buyer_address: str,
    recovery_item_address: str | None, recovery_previous_owner: str | None,
) -> str | None:
    kind = int(action["kind"])
    try:
        parser = envelope.original_body.begin_parse()
        query_id = int(action["query_id"])
        salt = int(deal_salt, 16)
        if kind in {1, 2, 3}:
            if parser.load_uint(32) != NFT_TRANSFER_OPCODE:
                return "outbound_body_opcode_mismatch"
            body_query_id = parser.load_uint(64)
            recipient = _address(parser.load_address())
            response = _address(parser.load_address())
            has_custom_payload = bool(parser.load_bit())
            if has_custom_payload:
                return "outbound_nft_custom_payload_unexpected"
            forward_amount = parser.load_coins()
            payload_in_ref = bool(parser.load_bit())
            payload = parser.load_ref().begin_parse() if payload_in_ref else parser
            if (
                forward_amount != 10_000_000
                or payload.load_bit() != 0
                or payload.load_uint(32) != NFT_FORWARD_MAGIC
                or payload.load_uint(256) != salt
                or payload.remaining_bits != 0
                or payload.remaining_refs != 0
            ):
                return "outbound_nft_payload_mismatch"
            if body_query_id != query_id:
                return "outbound_query_id_mismatch"
            if recipient != action["recipient_address"]:
                return "outbound_recipient_mismatch"
            if response != action["response_address"]:
                return "outbound_response_address_mismatch"
            if kind in {1, 2} and (
                action["item_address"] != item_address
                or action["destination_address"] != item_address
            ):
                return "outbound_nft_item_mismatch"
            if kind == 1 and recipient != buyer_address:
                return "outbound_nft_release_recipient_mismatch"
            if kind == 2 and recipient != seller_address:
                return "outbound_nft_return_recipient_mismatch"
            if kind == 3 and (
                not recovery_item_address or not recovery_previous_owner
                or action["item_address"] != recovery_item_address
                or action["destination_address"] != recovery_item_address
                or recipient != recovery_previous_owner
            ):
                return "outbound_recovery_route_mismatch"
        else:
            body_query_id = parser.load_uint(64)
            body_salt = parser.load_uint(256)
            settlement_action = parser.load_uint(8)
            expected_action = {4: 3, 5: 4, 6: 7, 7: 6}[kind]
            if body_query_id != query_id:
                return "outbound_query_id_mismatch"
            if body_salt != salt:
                return "outbound_deal_salt_mismatch"
            if settlement_action != expected_action:
                return "outbound_settlement_action_mismatch"
            destination = action["destination_address"]
            if destination != action["recipient_address"]:
                return "outbound_settlement_recipient_mismatch"
            if kind in {4, 6} and destination != seller_address:
                return "outbound_seller_destination_mismatch"
            if kind == 5 and destination != buyer_address:
                return "outbound_buyer_destination_mismatch"
            if kind == 7:
                expected_reserve_recipient = (
                    seller_address if int(action["expected_state"]) == 12
                    else buyer_address if int(action["expected_state"]) in {10, 11}
                    else None
                )
                if expected_reserve_recipient is None or destination != expected_reserve_recipient:
                    return "outbound_reserve_destination_mismatch"
        if parser.remaining_bits != 0 or parser.remaining_refs != 0:
            return "outbound_body_has_trailing_data"
        if int(action["query_id"]) != int(action["attempt_id"]):
            return "outbound_query_and_attempt_id_mismatch"
        return None
    except Exception:
        return "outbound_body_malformed"

def match_rich_bounce_to_action(
    envelope: RichBounceEnvelope, actions: list[dict[str, Any]], *,
    bounce_sender: str, contract_address: str, transaction_lt: int,
    deal_salt: str, item_address: str, seller_address: str, buyer_address: str,
    principal_nanotons: int, seller_deployment_refund_nanotons: int,
    nft_transfer_value_nanotons: int,
    recovery_item_address: str | None, recovery_previous_owner: str | None,
    current_contract_state: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Match a verified RichBounce to exactly one BOUNCED contract descriptor."""
    if envelope.original_has_extra_currencies:
        return None, "bounce_contains_unsupported_extra_currencies"
    if envelope.original_created_lt >= transaction_lt:
        return None, "bounce_original_logical_time_is_not_earlier"
    if bounce_sender == contract_address:
        return None, "bounce_sender_is_not_outbound_destination"
    exact_body = [
        action for action in actions
        if action.get("message_body_hash") == envelope.original_body_hash
    ]
    if not exact_body:
        return None, "outbound_action_descriptor_not_found"
    if len(exact_body) != 1:
        return None, "outbound_action_descriptor_ambiguous"
    action = exact_body[0]
    kind = int(action["kind"])
    expected_amount = (
        nft_transfer_value_nanotons if kind in {1, 2, 3}
        else principal_nanotons if kind in {4, 5}
        else seller_deployment_refund_nanotons if kind == 6
        else 0
    )
    if int(action["amount_nanotons"]) != expected_amount:
        return None, "outbound_action_amount_differs_from_deal_snapshot"
    if kind != 7 and int(action["message_value_nanotons"]) != expected_amount:
        return None, "outbound_message_value_differs_from_deal_snapshot"
    if action.get("status") != 1:
        return None, "outbound_action_not_marked_bounced_by_contract"
    if action.get("deal_salt") != deal_salt:
        return None, "outbound_action_deal_salt_mismatch"
    if action.get("destination_address") != bounce_sender:
        return None, "bounce_sender_does_not_match_outbound_destination"
    if kind != 7 and int(action["message_value_nanotons"]) != envelope.original_value_nanotons:
        return None, "bounce_original_value_mismatch"
    if int(action["bounce_phase"]) != envelope.bounced_by_phase:
        return None, "bounce_phase_differs_from_contract_descriptor"
    if int(action["exit_code"]) != envelope.exit_code:
        return None, "bounce_exit_code_differs_from_contract_descriptor"
    body_reason = _validate_original_body(
        action, envelope, deal_salt=deal_salt, item_address=item_address,
        seller_address=seller_address, buyer_address=buyer_address,
        recovery_item_address=recovery_item_address,
        recovery_previous_owner=recovery_previous_owner,
    )
    if body_reason:
        return None, body_reason
    expected_state = _STATE_NAMES.get(int(action["expected_state"]))
    if kind <= 5:
        if current_contract_state != "manual_review":
            return None, "critical_bounce_not_reflected_in_manual_review_state"
    elif current_contract_state != expected_state:
        return None, "noncritical_bounce_changed_unexpected_contract_state"
    return action, None
