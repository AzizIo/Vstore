"""Fail-closed TEP-62 identity evidence backed by proof-anchored TON account state.

This module deliberately does not trust TON Center indexed NFT fields or remote
get-method results. The caller supplies item and collection code/data cells read by
a trust-level-0 LiteServer client at the same masterchain block.
"""
from __future__ import annotations

import hashlib
import json
import re

from pytoniq_core import Address, Cell, begin_cell

from app.escrow.ton_abi import build_state_init_cell

_POLICY_DERIVATION = "tep62-standard-nft-collection-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_POLICY_FIELDS = (
    "policy_id",
    "collection_address",
    "collection_code_hash",
    "item_code_hash",
    "derivation",
)


class NFTIdentityEvidenceError(ValueError):
    """The proof-read NFT identity cannot be bound to the configured policy."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_address(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NFTIdentityEvidenceError("NFT address is missing")
    try:
        address = Address(value.strip())
    except Exception as exc:
        raise NFTIdentityEvidenceError("NFT address is malformed") from exc
    if address.wc != 0:
        raise NFTIdentityEvidenceError("Escrow NFT identity only supports basechain workchain 0")
    return address.to_str(is_user_friendly=False)


def cell_hash(cell: Cell) -> str:
    return cell.get_hash(0).hex()


def _valid_hash(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value.lower()))


def _parse_policy(
    policies: object,
    collection_address: str,
) -> tuple[dict[str, str], str]:
    if not isinstance(policies, list) or not policies:
        raise NFTIdentityEvidenceError("No escrow NFT collection policy is configured")

    parsed: list[dict[str, str]] = []
    seen_addresses: set[str] = set()
    for policy in policies:
        if not isinstance(policy, dict):
            raise NFTIdentityEvidenceError("NFT collection policy must be a JSON object")
        if any(not isinstance(policy.get(field), str) for field in _POLICY_FIELDS):
            raise NFTIdentityEvidenceError(
                "NFT collection policy is missing a required string field"
            )
        candidate = {
            "policy_id": policy["policy_id"].strip(),
            "collection_address": canonical_address(policy["collection_address"]),
            "collection_code_hash": policy["collection_code_hash"].strip().lower(),
            "item_code_hash": policy["item_code_hash"].strip().lower(),
            "derivation": policy["derivation"].strip(),
        }
        if not candidate["policy_id"] or len(candidate["policy_id"]) > 128:
            raise NFTIdentityEvidenceError("NFT collection policy id is invalid")
        if candidate["collection_address"] in seen_addresses:
            raise NFTIdentityEvidenceError("Duplicate NFT collection policies are not allowed")
        seen_addresses.add(candidate["collection_address"])
        if not _valid_hash(candidate["collection_code_hash"]) or not _valid_hash(
            candidate["item_code_hash"]
        ):
            raise NFTIdentityEvidenceError("NFT collection policy code hashes must be SHA-256 hex")
        if candidate["derivation"] != _POLICY_DERIVATION:
            raise NFTIdentityEvidenceError("Unsupported NFT collection derivation policy")
        parsed.append(candidate)

    matches = [policy for policy in parsed if policy["collection_address"] == collection_address]
    if len(matches) != 1:
        raise NFTIdentityEvidenceError("NFT collection is not explicitly allowlisted")
    policy = matches[0]
    return policy, sha256_json(policy)


def verify_nft_identity_cells(
    *,
    item_address: str,
    collection_address: str,
    item_code: Cell,
    item_data: Cell,
    collection_code: Cell,
    collection_data: Cell,
    policies: object,
    expected_owner_address: str | None,
    masterchain_seqno: int,
    masterchain_block_hash: str,
    trusted_init_key_block_hash: str,
    observed_chain_time_unix: int,
    provider_id: str,
) -> dict[str, object]:
    """Bind an item to one explicitly allowlisted standard collection at one block."""
    item = canonical_address(item_address)
    collection = canonical_address(collection_address)
    expected_owner = (
        canonical_address(expected_owner_address)
        if expected_owner_address is not None
        else None
    )
    if masterchain_seqno <= 0:
        raise NFTIdentityEvidenceError("Trusted masterchain sequence is invalid")
    if not _valid_hash(masterchain_block_hash) or not _valid_hash(trusted_init_key_block_hash):
        raise NFTIdentityEvidenceError("Trusted masterchain block identity is malformed")
    if not provider_id or not provider_id.strip():
        raise NFTIdentityEvidenceError("Proof provider identity is missing")

    policy, policy_sha256 = _parse_policy(policies, collection)
    item_code_hash = cell_hash(item_code)
    collection_code_hash = cell_hash(collection_code)
    if collection_code_hash != policy["collection_code_hash"]:
        raise NFTIdentityEvidenceError("Collection contract code hash is not allowlisted")
    if item_code_hash != policy["item_code_hash"]:
        raise NFTIdentityEvidenceError("NFT item contract code hash is not allowlisted")

    item_parser = item_data.begin_parse()
    try:
        item_index = item_parser.load_uint(64)
        item_collection = item_parser.load_address()
        item_owner = item_parser.load_address()
        item_parser.load_ref()  # TEP-62 item content cell
    except Exception as exc:
        raise NFTIdentityEvidenceError("TEP-62 item storage is malformed") from exc
    if item_parser.remaining_bits != 0 or item_parser.remaining_refs != 0:
        raise NFTIdentityEvidenceError("TEP-62 item storage has unexpected trailing data")
    if item_collection is None or item_owner is None:
        raise NFTIdentityEvidenceError("TEP-62 item collection or owner address is empty")
    actual_collection = canonical_address(item_collection.to_str(is_user_friendly=False))
    actual_owner = canonical_address(item_owner.to_str(is_user_friendly=False))
    if actual_collection != collection:
        raise NFTIdentityEvidenceError("NFT item's proof-read collection differs from the policy")
    if expected_owner is not None and actual_owner != expected_owner:
        raise NFTIdentityEvidenceError("NFT current owner differs from the expected wallet")

    collection_parser = collection_data.begin_parse()
    try:
        collection_parser.load_address()  # Collection owner; not the marketplace seller.
        next_item_index = collection_parser.load_uint(64)
        collection_parser.load_ref()  # Collection/common content wrapper.
        collection_item_code = collection_parser.load_ref()
        collection_parser.load_ref()  # Royalty parameters.
    except Exception as exc:
        raise NFTIdentityEvidenceError("Standard TEP-62 collection storage is malformed") from exc
    if collection_parser.remaining_bits != 0 or collection_parser.remaining_refs != 0:
        raise NFTIdentityEvidenceError("Collection storage has unexpected trailing data")
    if cell_hash(collection_item_code) != policy["item_code_hash"]:
        raise NFTIdentityEvidenceError(
            "Collection's stored NFT item code differs from the allowlist"
        )
    if next_item_index <= item_index:
        raise NFTIdentityEvidenceError("NFT index is outside the collection's minted index range")

    # TEP-62 standard collection get_nft_address_by_index(index) derives the
    # NFT StateInit from uint64 index + collection address + stored item code.
    item_state_data = (
        begin_cell()
        .store_uint(item_index, 64)
        .store_address(Address(collection))
        .end_cell()
    )
    item_state_init = build_state_init_cell(collection_item_code, item_state_data)
    item_workchain = Address(item).wc
    derived_item = Address((item_workchain, item_state_init.get_hash(0))).to_str(
        is_user_friendly=False
    )
    if derived_item != item:
        raise NFTIdentityEvidenceError(
            "Collection get_nft_address_by_index derivation does not match the item account"
        )

    payload: dict[str, object] = {
        "version": 1,
        "network": "testnet",
        "policy": policy,
        "policy_sha256": policy_sha256,
        "provider_id": provider_id,
        "masterchain_seqno": masterchain_seqno,
        "masterchain_block_hash": masterchain_block_hash.lower(),
        "trusted_init_key_block_hash": trusted_init_key_block_hash.lower(),
        "observed_chain_time_unix": observed_chain_time_unix,
        "item_address": item,
        "collection_address": collection,
        "item_index": item_index,
        "owner_address": actual_owner,
        "item_code_hash": item_code_hash,
        "collection_code_hash": collection_code_hash,
        "collection_item_code_hash": cell_hash(collection_item_code),
        "item_data_hash": cell_hash(item_data),
        "collection_data_hash": cell_hash(collection_data),
        "derived_item_address": derived_item,
        "collection_next_item_index": next_item_index,
    }
    payload["evidence_sha256"] = sha256_json(payload)
    return payload


def validate_nft_identity_snapshot(
    snapshot: object,
    stored_sha256: object,
) -> dict[str, object]:
    if not isinstance(snapshot, dict):
        raise NFTIdentityEvidenceError("Persisted NFT identity snapshot is missing")
    payload = dict(snapshot)
    embedded_hash = payload.pop("evidence_sha256", None)
    if (
        not isinstance(embedded_hash, str)
        or not _valid_hash(embedded_hash)
        or embedded_hash != sha256_json(payload)
        or stored_sha256 != embedded_hash
    ):
        raise NFTIdentityEvidenceError("Persisted NFT identity evidence hash mismatch")
    required = {
        "version", "network", "policy", "policy_sha256", "provider_id",
        "masterchain_seqno", "masterchain_block_hash", "item_address",
        "collection_address", "item_index", "owner_address", "item_code_hash",
        "collection_code_hash", "collection_item_code_hash", "item_data_hash",
        "collection_data_hash", "derived_item_address",
    }
    if not required.issubset(snapshot):
        raise NFTIdentityEvidenceError("Persisted NFT identity evidence is incomplete")

    if snapshot.get("version") != 1 or snapshot.get("network") != "testnet":
        raise NFTIdentityEvidenceError("Persisted NFT identity evidence has an unsupported version/network")
    if (
        isinstance(snapshot.get("masterchain_seqno"), bool)
        or not isinstance(snapshot.get("masterchain_seqno"), int)
        or int(snapshot["masterchain_seqno"]) <= 0
    ):
        raise NFTIdentityEvidenceError("Persisted NFT identity masterchain sequence is invalid")
    if (
        isinstance(snapshot.get("item_index"), bool)
        or not isinstance(snapshot.get("item_index"), int)
        or int(snapshot["item_index"]) < 0
    ):
        raise NFTIdentityEvidenceError("Persisted NFT identity item index is invalid")
    policy = snapshot.get("policy")
    if not isinstance(policy, dict) or snapshot.get("policy_sha256") != sha256_json(policy):
        raise NFTIdentityEvidenceError("Persisted NFT identity policy digest mismatch")
    if (
        policy.get("collection_address") != snapshot.get("collection_address")
        or policy.get("collection_code_hash") != snapshot.get("collection_code_hash")
        or policy.get("item_code_hash") != snapshot.get("item_code_hash")
        or policy.get("derivation") != _POLICY_DERIVATION
    ):
        raise NFTIdentityEvidenceError("Persisted NFT identity policy does not bind the recorded item")
    for field in (
        "masterchain_block_hash",
        "trusted_init_key_block_hash",
        "item_code_hash",
        "collection_code_hash",
        "collection_item_code_hash",
        "item_data_hash",
        "collection_data_hash",
    ):
        if not _valid_hash(snapshot.get(field)):
            raise NFTIdentityEvidenceError(f"Persisted NFT identity {field} is malformed")
    for field in ("item_address", "collection_address", "owner_address", "derived_item_address"):
        try:
            normalized = canonical_address(snapshot.get(field))
        except NFTIdentityEvidenceError as exc:
            raise NFTIdentityEvidenceError(f"Persisted NFT identity {field} is malformed") from exc
        if normalized != snapshot.get(field):
            raise NFTIdentityEvidenceError(f"Persisted NFT identity {field} is not canonical")
    if snapshot.get("derived_item_address") != snapshot.get("item_address"):
        raise NFTIdentityEvidenceError("Persisted NFT identity derived address does not match the item")
    next_index = snapshot.get("collection_next_item_index")
    if (
        isinstance(next_index, bool)
        or not isinstance(next_index, int)
        or int(next_index) <= int(snapshot["item_index"])
    ):
        raise NFTIdentityEvidenceError("Persisted NFT identity collection index range is invalid")
    if not isinstance(snapshot.get("provider_id"), str) or not str(snapshot["provider_id"]).strip():
        raise NFTIdentityEvidenceError("Persisted NFT identity provider id is missing")
    return dict(snapshot)


def same_nft_identity_anchor(initial: dict[str, object], current: dict[str, object]) -> bool:
    """Compare policy and identity, intentionally ignoring owner and block position."""
    fields = (
        "network",
        "policy_sha256",
        "item_address",
        "collection_address",
        "item_index",
        "item_code_hash",
        "collection_code_hash",
        "collection_item_code_hash",
        "derived_item_address",
    )
    return all(initial.get(field) == current.get(field) for field in fields)
