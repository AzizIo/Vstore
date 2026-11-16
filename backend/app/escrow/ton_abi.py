"""Pinned DealEscrow ABI, StateInit and TON message codec.

The codec intentionally accepts the compiled code BOC as an injected, immutable
build artifact. It verifies it against the checked-in provenance manifest before
deriving an address or creating a wallet payload. StateInit and message BOC hashes
are pinned against generated Acton/@ton-core vectors in backend tests.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pytoniq_core import Address, Cell, begin_cell

_ARTIFACTS = Path(__file__).resolve().parent / "abi_artifacts"
_NETWORK_ID = -3
_PROTOCOL_VERSION = 1
_CODE_HASH = "9011F274BC3D7E32B76A17F13FCBA17AC49429BB4EECBC4AB97FA202BDAC2940"
_NFT_TRANSFER_OPCODE = 0x5FCC3D14
_NFT_FORWARD_MAGIC = 0x56454E46
_OPCODES = {
    "activate_deal": 0x56450001,
    "fund_deal": 0x56450002,
    "accept_deal": 0x56450003,
    "open_dispute": 0x56450004,
    "timeout_deal": 0x56450007,
    "recover_unexpected_nft": 0x56450008,
}
_TERMINAL_STORAGE_RESERVE = 10_000_000
_MIN_ACTION_VALUE = 10_000_000
_MIN_EXECUTION_RESERVE = 500_000_000
_MIN_SELLER_REFUND = 20_000_000
_MAX_SELLER_REFUND = 100_000_000
_MIN_NFT_TRANSFER = 50_000_000
_MAX_NFT_TRANSFER = 150_000_000
_HEX_256 = re.compile(r"^[0-9a-fA-F]{64}$")


class TONABIError(ValueError):
    """Pinned artifact, immutable terms, address or TL-B value is invalid."""


@dataclass(frozen=True, slots=True)
class VerifiedArtifacts:
    abi_version: str
    abi_sha256: str
    code_hash: str
    code_boc_sha256: str
    code: Cell


@dataclass(frozen=True, slots=True)
class DeploymentStateInit:
    address: str
    state_init_hash: str
    code_hash: str
    data_hash: str
    state_init_boc: str
    data_boc: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_artifact_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TONABIError(f"cannot read pinned artifact {path.name}") from exc
    if not isinstance(value, dict):
        raise TONABIError(f"pinned artifact {path.name} must be a JSON object")
    return value


@lru_cache(maxsize=1)
def load_pinned_abi() -> tuple[dict[str, Any], dict[str, Any]]:
    abi = _read_artifact_json(_ARTIFACTS / "DealEscrow.abi.json")
    manifest = _read_artifact_json(_ARTIFACTS / "manifest.json")
    canonical = json.dumps(abi, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    actual = _sha256(canonical)
    if actual != manifest.get("abi_compact_sha256"):
        raise TONABIError("DealEscrow ABI digest does not match frozen manifest")
    if (
        abi.get("contract_name") != "DealEscrow"
        or abi.get("version") != "1.0.0"
        or abi.get("compiler_name") != "tolk"
        or abi.get("compiler_version") != manifest.get("tolk_version")
        or manifest.get("contract") != "DealEscrow"
        or manifest.get("network_scope") != "TON testnet only"
        or manifest.get("protocol_version") != _PROTOCOL_VERSION
        or manifest.get("compiled_code_hash") != _CODE_HASH
    ):
        raise TONABIError("DealEscrow ABI/manifest identity or testnet scope is invalid")
    return abi, manifest


def load_pinned_code_boc() -> str:
    """Verify and decompress the pinned compiler BOC into canonical base64 text."""
    try:
        compressed_b64 = (
            _ARTIFACTS / "DealEscrow.code.boc.zlib.b64"
        ).read_text(encoding="ascii").strip()
        compressed = base64.b64decode(compressed_b64, validate=True)
    except (OSError, UnicodeError, ValueError) as exc:
        raise TONABIError("pinned DealEscrow code BOC is unavailable or corrupt") from exc

    _, manifest = load_pinned_abi()
    if _sha256(compressed) != manifest.get("compiled_code_boc_zlib_sha256"):
        raise TONABIError("DealEscrow compressed code BOC digest mismatch")

    try:
        raw_boc = zlib.decompress(compressed)
    except zlib.error as exc:
        raise TONABIError("pinned DealEscrow code BOC is unavailable or corrupt") from exc
    return base64.b64encode(raw_boc).decode("ascii")


def verify_compiled_code(code_boc_base64: str | None = None) -> VerifiedArtifacts:
    """Verify compiler BOC digests and the TON cell representation hash."""
    if code_boc_base64 is None:
        code_boc_base64 = load_pinned_code_boc()
    if not isinstance(code_boc_base64, str) or not code_boc_base64:
        raise TONABIError("the pinned DealEscrow code BOC is required")
    try:
        code_boc = base64.b64decode(code_boc_base64, validate=True)
        code = Cell.one_from_boc(code_boc)
    except Exception as exc:
        raise TONABIError("DealEscrow code BOC is malformed") from exc
    abi, manifest = load_pinned_abi()
    if _sha256(code_boc_base64.encode("ascii")) != manifest.get(
        "compiled_code_boc_base64_sha256"
    ):
        raise TONABIError("DealEscrow code BOC base64 digest mismatch")
    if _sha256(code_boc) != manifest.get("compiled_code_boc_sha256"):
        raise TONABIError("DealEscrow decoded code BOC digest mismatch")
    actual_code_hash = code.hash.hex().upper()
    if actual_code_hash != manifest.get("compiled_code_hash") or actual_code_hash != _CODE_HASH:
        raise TONABIError("DealEscrow code cell hash mismatch")
    return VerifiedArtifacts(
        abi_version=str(abi.get("version")),
        abi_sha256=str(manifest["abi_compact_sha256"]),
        code_hash=actual_code_hash,
        code_boc_sha256=_sha256(code_boc),
        code=code,
    )


def parse_basechain_address(value: str, field: str) -> Address:
    if not isinstance(value, str) or not value:
        raise TONABIError(f"{field} is required")
    try:
        address = Address(value)
    except Exception as exc:
        raise TONABIError(f"{field} is not a valid TON address") from exc
    if address.wc != 0 or len(address.hash_part) != 32:
        raise TONABIError(f"{field} must be a basechain workchain-0 address")
    return address


def _uint(value: int, bits: int, field: str, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TONABIError(f"{field} must be an integer")
    minimum = 0 if allow_zero else 1
    if not minimum <= value < (1 << bits):
        raise TONABIError(f"{field} is outside uint{bits}")
    return value


def _coins(value: int, field: str, *, allow_zero: bool = False) -> int:
    value = _uint(value, 120, field, allow_zero=allow_zero)
    if value >= (1 << 120):
        raise TONABIError(f"{field} does not fit TL-B VarUInteger 16")
    return value


def _salt(value: str) -> int:
    if not isinstance(value, str) or not _HEX_256.fullmatch(value):
        raise TONABIError("deal_salt must be exactly 32 bytes of hexadecimal")
    result = int(value, 16)
    if result == 0:
        raise TONABIError("deal_salt must be non-zero")
    return result


def _key(value: int, field: str) -> int:
    return _uint(value, 256, field, allow_zero=False)


def validate_snapshot(snapshot: Any) -> tuple[Address, Address, Address, Address, int]:
    if getattr(snapshot, "network", None) != "testnet":
        raise TONABIError("only TON testnet snapshots are supported")
    if getattr(snapshot, "network_id", None) != _NETWORK_ID:
        raise TONABIError("network_id must be TON testnet global ID -3")
    if getattr(snapshot, "protocol_version", None) != _PROTOCOL_VERSION:
        raise TONABIError("unsupported DealEscrow protocol version")
    listing_key = getattr(snapshot, "listing_key", None)
    if not isinstance(listing_key, str) or not _HEX_256.fullmatch(listing_key):
        raise TONABIError("listing_key must be a 256-bit hexadecimal identifier")
    seller = parse_basechain_address(snapshot.seller_address, "seller_address")
    buyer = parse_basechain_address(snapshot.buyer_address, "buyer_address")
    collection = parse_basechain_address(snapshot.collection_address, "collection_address")
    item = parse_basechain_address(snapshot.item_address, "item_address")
    if seller == buyer:
        raise TONABIError("seller and buyer addresses must differ")
    salt = _salt(snapshot.deal_salt)

    principal = _coins(snapshot.principal_nanotons, "principal_nanotons")
    if principal <= 0:
        raise TONABIError("principal_nanotons must be positive")
    reserve = _coins(snapshot.execution_reserve_nanotons, "execution_reserve_nanotons")
    refund = _coins(
        snapshot.seller_deployment_refund_nanotons, "seller_deployment_refund_nanotons"
    )
    transfer = _coins(snapshot.nft_transfer_value_nanotons, "nft_transfer_value_nanotons")
    if reserve < _MIN_EXECUTION_RESERVE:
        raise TONABIError("execution reserve is below the contract minimum of 0.5 TON")
    if not _MIN_SELLER_REFUND <= refund <= _MAX_SELLER_REFUND:
        raise TONABIError("seller deployment refund must be between 0.02 and 0.1 TON")
    if not _MIN_NFT_TRANSFER <= transfer <= _MAX_NFT_TRANSFER:
        raise TONABIError("NFT transfer value must be between 0.05 and 0.15 TON")
    if reserve < transfer * 3 + refund + _TERMINAL_STORAGE_RESERVE + 100_000_000:
        raise TONABIError("execution reserve does not satisfy the contract's reserve formula")

    query_ids = (
        _uint(snapshot.activation_query_id, 64, "activation_query_id", allow_zero=False),
        _uint(snapshot.fund_query_id, 64, "fund_query_id", allow_zero=False),
        _uint(snapshot.nft_deposit_query_id, 64, "nft_deposit_query_id", allow_zero=False),
        _uint(snapshot.nft_release_query_id, 64, "nft_release_query_id", allow_zero=False),
        _uint(
            snapshot.nft_return_to_escrow_query_id,
            64,
            "nft_return_to_escrow_query_id",
            allow_zero=False,
        ),
    )
    if len(set(query_ids)) != len(query_ids):
        raise TONABIError("all immutable query IDs must be unique")
    oracle = tuple(
        _key(getattr(snapshot, f"oracle_key_{suffix}"), f"oracle_key_{suffix}")
        for suffix in "abc"
    )
    resolver = tuple(
        _key(getattr(snapshot, f"resolver_key_{suffix}"), f"resolver_key_{suffix}")
        for suffix in "abc"
    )
    if len(set(oracle + resolver)) != 6:
        raise TONABIError("oracle and resolver public keys must be globally unique")
    for name in (
        "deployment_value_nanotons",
        "activation_value_nanotons",
        "action_value_nanotons",
        "nft_deposit_value_nanotons",
        "nft_return_value_nanotons",
    ):
        _coins(getattr(snapshot, name), name)
    if snapshot.activation_value_nanotons < _MIN_ACTION_VALUE:
        raise TONABIError("activation value must be at least 0.01 TON")
    if snapshot.action_value_nanotons < _MIN_ACTION_VALUE:
        raise TONABIError("action value must be at least 0.01 TON")
    if snapshot.deployment_value_nanotons <= 0:
        raise TONABIError("deployment value must be positive")
    if (
        snapshot.deployment_value_nanotons
        < snapshot.activation_value_nanotons
        + refund
        + _TERMINAL_STORAGE_RESERVE
    ):
        raise TONABIError(
            "deployment value cannot fund activation, seller refund and terminal storage reserve"
        )
    if snapshot.nft_deposit_value_nanotons < 10_000_000:
        raise TONABIError("NFT deposit value must cover the 0.01 TON forward amount")
    if snapshot.nft_return_value_nanotons < 10_000_000:
        raise TONABIError("NFT return value must cover the 0.01 TON forward amount")
    contract_state = _uint(snapshot.contract_state, 8, "contract_state")
    if contract_state > 13:
        raise TONABIError("contract_state is not defined by DealEscrow v1")
    _uint(snapshot.deadline_unix, 64, "deadline_unix")
    _uint(snapshot.observed_chain_time_unix, 64, "observed_chain_time_unix")
    dispute_phase = _uint(snapshot.dispute_phase, 8, "dispute_phase")
    if dispute_phase > 2:
        raise TONABIError("dispute_phase is not defined by DealEscrow v1")
    if (
        not isinstance(snapshot.nft_in_escrow, bool)
        or not isinstance(snapshot.principal_locked, bool)
    ):
        raise TONABIError("contract flags must be booleans")
    return seller, buyer, collection, item, salt


def _store_ref_cell(cell: Cell, builder: Any) -> None:
    builder.store_ref(cell)


def build_storage_cell(snapshot: Any) -> Cell:
    """Serialize EscrowStorage exactly as the generated Acton wrapper does."""
    seller, buyer, collection, item, salt = validate_snapshot(snapshot)
    roles = (
        begin_cell().store_address(seller).store_address(buyer).end_cell()
    )
    asset = (
        begin_cell().store_address(item).store_address(collection).store_uint(salt, 256).end_cell()
    )
    money = (
        begin_cell()
        .store_coins(snapshot.principal_nanotons)
        .store_coins(snapshot.execution_reserve_nanotons)
        .store_coins(snapshot.seller_deployment_refund_nanotons)
        .store_coins(snapshot.nft_transfer_value_nanotons)
        .store_uint(snapshot.fund_query_id, 64)
        .store_uint(snapshot.nft_deposit_query_id, 64)
        .store_uint(snapshot.nft_release_query_id, 64)
        .store_uint(snapshot.nft_return_to_escrow_query_id, 64)
        .end_cell()
    )
    oracle = (
        begin_cell()
        .store_uint(snapshot.oracle_key_a, 256)
        .store_uint(snapshot.oracle_key_b, 256)
        .store_uint(snapshot.oracle_key_c, 256)
        .end_cell()
    )
    resolver = (
        begin_cell()
        .store_uint(snapshot.resolver_key_a, 256)
        .store_uint(snapshot.resolver_key_b, 256)
        .store_uint(snapshot.resolver_key_c, 256)
        .end_cell()
    )
    security = begin_cell().store_ref(oracle).store_ref(resolver).end_cell()
    terms = (
        begin_cell()
        .store_ref(roles)
        .store_ref(asset)
        .store_ref(money)
        .store_ref(security)
        .store_int(snapshot.network_id, 32)
        .store_uint(snapshot.protocol_version, 16)
        .end_cell()
    )
    evidence = begin_cell().store_uint(0, 256).store_uint(0, 256).end_cell()
    recovery = begin_cell().store_address(None).store_address(None).end_cell()
    # The third reference is the persisted OutboundActionSet introduced by
    # DealProgress v1. Both maybe-ref slots start empty in a fresh deployment.
    outbound_actions = begin_cell().store_bit(0).store_bit(0).end_cell()
    progress = (
        begin_cell()
        .store_uint(0, 8)  # STATE_INTENT_CREATED
        .store_uint(0, 64)  # deadlineUnix
        .store_uint(0, 8)  # DISPUTE_PHASE_NONE
        .store_uint(0, 8)  # PENDING_NONE
        .store_bit(0)  # nftInEscrow
        .store_bit(0)  # principalLocked
        .store_uint(0, 64)  # oracleAttemptId
        .store_uint(0, 64)  # disputeAttemptId
        .store_ref(evidence)
        .store_ref(recovery)
        .store_ref(outbound_actions)
        .end_cell()
    )
    return begin_cell().store_ref(terms).store_ref(progress).end_cell()


def decode_storage_cell(data_cell: Cell) -> dict[str, object]:
    """Decode the authenticated DealEscrow data cell without an unproved remote getter.

    Callers must obtain the data cell from a trust-level-0 LiteClient account-state
    proof at a finalized masterchain block and separately verify the deployed code
    hash. This decoder exposes the contract terms/progress so the observer can
    compare them with the persisted immutable snapshot.
    """

    try:
        root = data_cell.begin_parse()
        terms_cell = root.load_ref()
        progress_cell = root.load_ref()

        terms = terms_cell.begin_parse()
        roles_cell = terms.load_ref()
        asset_cell = terms.load_ref()
        money_cell = terms.load_ref()
        security_cell = terms.load_ref()
        network_id = terms.load_int(32)
        protocol_version = terms.load_uint(16)

        roles = roles_cell.begin_parse()
        seller_address = roles.load_address().to_str(is_user_friendly=False)
        buyer_address = roles.load_address().to_str(is_user_friendly=False)

        asset = asset_cell.begin_parse()
        item_address = asset.load_address().to_str(is_user_friendly=False)
        collection_address = asset.load_address().to_str(is_user_friendly=False)
        deal_salt = f"{asset.load_uint(256):064x}"

        money = money_cell.begin_parse()
        principal_nanotons = money.load_coins()
        execution_reserve_nanotons = money.load_coins()
        seller_deployment_refund_nanotons = money.load_coins()
        nft_transfer_value_nanotons = money.load_coins()
        fund_query_id = money.load_uint(64)
        nft_deposit_query_id = money.load_uint(64)
        nft_release_query_id = money.load_uint(64)
        nft_return_to_escrow_query_id = money.load_uint(64)

        security = security_cell.begin_parse()
        oracle = security.load_ref().begin_parse()
        resolver = security.load_ref().begin_parse()
        oracle_keys = tuple(oracle.load_uint(256) for _ in range(3))
        resolver_keys = tuple(resolver.load_uint(256) for _ in range(3))

        progress = progress_cell.begin_parse()
        contract_state = progress.load_uint(8)
        deadline_unix = progress.load_uint(64)
        dispute_phase = progress.load_uint(8)
        pending_action = progress.load_uint(8)
        nft_in_escrow = bool(progress.load_bit())
        principal_locked = bool(progress.load_bit())
        oracle_attempt_id = progress.load_uint(64)
        dispute_attempt_id = progress.load_uint(64)
        evidence = progress.load_ref().begin_parse()
        last_evidence_hash = evidence.load_uint(256)
        dispute_reason_hash = evidence.load_uint(256)
        recovery = progress.load_ref().begin_parse()
        recovery_previous_owner = recovery.load_address()
        recovery_item_address = recovery.load_address()

        # DealProgress now stores a mandatory OutboundActionSet cell with two
        # optional references. Parse the option bits so the observer rejects an
        # old/truncated storage layout instead of silently accepting it.
        outbound_actions = progress.load_ref().begin_parse()
        outbound_first_present = bool(outbound_actions.load_bit())
        outbound_action_cells = []
        if outbound_first_present:
            outbound_action_cells.append(("first", outbound_actions.load_ref()))
        outbound_second_present = bool(outbound_actions.load_bit())
        if outbound_second_present:
            outbound_action_cells.append(("second", outbound_actions.load_ref()))
        if outbound_actions.remaining_bits != 0 or outbound_actions.remaining_refs != 0:
            raise ValueError("OutboundActionSet contains trailing data")
        outbound_action_rows = []
        for slot, action_cell in outbound_action_cells:
            action = action_cell.begin_parse()
            kind = action.load_uint(8)
            query_id = action.load_uint(64)
            action_deal_salt = f"{action.load_uint(256):064x}"
            attempt_id = action.load_uint(64)
            amount_nanotons = action.load_coins()
            message_value_nanotons = action.load_coins()
            expected_state = action.load_uint(8)
            expected_pending_action = action.load_uint(8)
            retry_window_seconds = action.load_uint(32)
            message_body_hash = f"{action.load_uint(256):064x}"
            status = action.load_uint(8)
            bounce_phase = action.load_uint(8)
            exit_code = action.load_int(32)
            addresses_cell = action.load_ref()
            if action.remaining_bits != 0 or action.remaining_refs != 0:
                raise ValueError("OutboundAction contains trailing data")
            addresses = addresses_cell.begin_parse()
            item_pair = addresses.load_ref().begin_parse()
            item_address = item_pair.load_address().to_str(is_user_friendly=False)
            destination_address = item_pair.load_address().to_str(is_user_friendly=False)
            recipient_pair = addresses.load_ref().begin_parse()
            recipient_address = recipient_pair.load_address().to_str(is_user_friendly=False)
            response_address = recipient_pair.load_address().to_str(is_user_friendly=False)
            if (
                item_pair.remaining_bits != 0 or item_pair.remaining_refs != 0
                or recipient_pair.remaining_bits != 0 or recipient_pair.remaining_refs != 0
                or addresses.remaining_bits != 0 or addresses.remaining_refs != 0
            ):
                raise ValueError("OutboundAction addresses contain trailing data")
            if (
                kind not in {1, 2, 3, 4, 5, 6, 7}
                or query_id <= 0 or attempt_id <= 0
                or action_deal_salt == "0" * 64
                or status not in {0, 1}
                or expected_state > 13
                or bounce_phase not in {0, 1, 2}
                or (status == 0 and (bounce_phase != 0 or exit_code != 0))
            ):
                raise ValueError("OutboundAction contains invalid protocol values")
            outbound_action_rows.append({
                "slot": slot,
                "kind": kind,
                "query_id": query_id,
                "deal_salt": action_deal_salt,
                "attempt_id": attempt_id,
                "amount_nanotons": amount_nanotons,
                "message_value_nanotons": message_value_nanotons,
                "expected_state": expected_state,
                "expected_pending_action": expected_pending_action,
                "retry_window_seconds": retry_window_seconds,
                "message_body_hash": message_body_hash,
                "status": status,
                "bounce_phase": bounce_phase,
                "exit_code": exit_code,
                "item_address": item_address,
                "destination_address": destination_address,
                "recipient_address": recipient_address,
                "response_address": response_address,
            })
    except Exception as exc:
        raise TONABIError("DealEscrow storage data cell is malformed") from exc

    return {
        "network": "testnet",
        "network_id": network_id,
        "protocol_version": protocol_version,
        "seller_address": seller_address,
        "buyer_address": buyer_address,
        "item_address": item_address,
        "collection_address": collection_address,
        "deal_salt": deal_salt,
        "principal_nanotons": principal_nanotons,
        "execution_reserve_nanotons": execution_reserve_nanotons,
        "seller_deployment_refund_nanotons": seller_deployment_refund_nanotons,
        "nft_transfer_value_nanotons": nft_transfer_value_nanotons,
        "fund_query_id": fund_query_id,
        "nft_deposit_query_id": nft_deposit_query_id,
        "nft_release_query_id": nft_release_query_id,
        "nft_return_to_escrow_query_id": nft_return_to_escrow_query_id,
        "oracle_key_a": oracle_keys[0],
        "oracle_key_b": oracle_keys[1],
        "oracle_key_c": oracle_keys[2],
        "resolver_key_a": resolver_keys[0],
        "resolver_key_b": resolver_keys[1],
        "resolver_key_c": resolver_keys[2],
        "contract_state": contract_state,
        "deadline_unix": deadline_unix,
        "dispute_phase": dispute_phase,
        "pending_action": pending_action,
        "nft_in_escrow": nft_in_escrow,
        "principal_locked": principal_locked,
        "oracle_attempt_id": oracle_attempt_id,
        "dispute_attempt_id": dispute_attempt_id,
        "last_evidence_hash": f"{last_evidence_hash:064x}",
        "dispute_reason_hash": f"{dispute_reason_hash:064x}",
        "recovery_previous_owner": (
            recovery_previous_owner.to_str(is_user_friendly=False)
            if recovery_previous_owner is not None else None
        ),
        "recovery_item_address": (
            recovery_item_address.to_str(is_user_friendly=False)
            if recovery_item_address is not None else None
        ),
        "outbound_action_slots": [outbound_first_present, outbound_second_present],
        "outbound_actions": outbound_action_rows,
    }


def build_state_init_cell(code: Cell, data: Cell) -> Cell:
    """StateInit TL-B: split_depth=None, special=None, code=Some, data=Some, libraries=None."""
    return (
        begin_cell()
        .store_bit(0)
        .store_bit(0)
        .store_bit(1)
        .store_ref(code)
        .store_bit(1)
        .store_ref(data)
        .store_bit(0)
        .end_cell()
    )


def derive_deployment(code_boc_base64: str, snapshot: Any) -> DeploymentStateInit:
    artifacts = verify_compiled_code(code_boc_base64)
    data = build_storage_cell(snapshot)
    state_init = build_state_init_cell(artifacts.code, data)
    address = Address((0, state_init.hash))
    return DeploymentStateInit(
        address=address.to_str(is_user_friendly=False),
        state_init_hash=state_init.hash.hex(),
        code_hash=artifacts.code_hash,
        data_hash=data.hash.hex(),
        state_init_boc=base64.b64encode(state_init.to_boc(hash_crc32=True)).decode("ascii"),
        data_boc=base64.b64encode(data.to_boc(hash_crc32=True)).decode("ascii"),
    )


def _body_boc(builder: Any) -> str:
    return base64.b64encode(builder.end_cell().to_boc(hash_crc32=True)).decode("ascii")


def encode_simple_action(action: str, query_id: int, deal_salt: int) -> str:
    opcode = _OPCODES.get(action)
    if opcode is None:
        raise TONABIError(f"unsupported wallet operation: {action}")
    _uint(query_id, 64, "query_id", allow_zero=False)
    _uint(deal_salt, 256, "deal_salt", allow_zero=False)
    return _body_boc(
        begin_cell().store_uint(opcode, 32).store_uint(query_id, 64).store_uint(deal_salt, 256)
    )


def encode_dispute_action(query_id: int, deal_salt: int, reason_hash: int) -> str:
    _uint(query_id, 64, "query_id", allow_zero=False)
    _uint(deal_salt, 256, "deal_salt", allow_zero=False)
    _uint(reason_hash, 256, "reason_hash", allow_zero=False)
    return _body_boc(
        begin_cell()
        .store_uint(_OPCODES["open_dispute"], 32)
        .store_uint(query_id, 64)
        .store_uint(deal_salt, 256)
        .store_uint(reason_hash, 256)
    )


def encode_nft_transfer(
    *,
    query_id: int,
    new_owner: str,
    response_destination: str,
    deal_salt: int,
    forward_amount_nanotons: int = 10_000_000,
) -> str:
    _uint(query_id, 64, "query_id", allow_zero=False)
    _uint(deal_salt, 256, "deal_salt", allow_zero=False)
    new_owner_address = parse_basechain_address(new_owner, "new_owner")
    response_address = parse_basechain_address(response_destination, "response_destination")
    forward_amount = _coins(forward_amount_nanotons, "forward_amount_nanotons")
    # Wallet-originated deposit/return messages use the generated Acton vector's
    # 0.01 TON forward amount, matching the contract's TEP-62 transfer layout.
    if forward_amount != 10_000_000:
        raise TONABIError(
            "DealEscrow TEP-62 user-transfer payload pins forwardTonAmount to 0.01 TON"
        )
    return _body_boc(
        begin_cell()
        .store_uint(_NFT_TRANSFER_OPCODE, 32)
        .store_uint(query_id, 64)
        .store_address(new_owner_address)
        .store_address(response_address)
        .store_maybe_ref(None)  # custom_payload = null
        .store_coins(forward_amount)
        .store_bit(0)  # Either inline forwardPayload; then magic and deal salt
        .store_uint(_NFT_FORWARD_MAGIC, 32)
        .store_uint(deal_salt, 256)
    )
