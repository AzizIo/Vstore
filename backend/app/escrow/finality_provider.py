"""Proof-checked TON testnet finality and TEP-62 owner verification.

TON Center v3 is used only to discover bounded candidate transactions. No indexed
`finalized`, trace or status field is an authorization input. Each accepted event
must be found in a Pytoniq trust-level-0 shard block whose inclusion is proven to a
trusted masterchain block, must match the exact incoming message cell, and must agree
with the immutable DealEscrow constructor snapshot and proof-read on-chain storage.

The implementation is explicitly testnet-only. It never signs, broadcasts or submits
a wallet message.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.escrow.contracts import DealEscrowDeploymentSnapshot
from app.escrow.domain import EscrowChainEventType
from app.escrow.models import EscrowDeal
from app.escrow.provider import (
    ChainEventBatch,
    EscrowProviderInvalidEvidence,
    EscrowProviderUnavailable,
    FinalityVerification,
    NormalizedChainEvent,
    TerminalOwnerVerification,
)
from app.escrow.ton_abi import (
    decode_storage_cell,
    derive_deployment,
    load_pinned_code_boc,
    validate_snapshot,
    verify_compiled_code,
)

logger = logging.getLogger(__name__)

_TESTNET_API_BASE = "https://testnet.toncenter.com/api/v3"
_PROVIDER_ID = "pytoniq-trust0-testnet-v1"
_PROTOCOL_VERSION = 1
_NETWORK_ID = -3
_ESCROW_DOMAIN = 0x56455343
_NFT_FORWARD_MAGIC = 0x56454E46
_NFT_TRANSFER_OPCODE = 0x5FCC3D14
_NFT_NOTIFICATION_OPCODE = 0x05138D91
_OP_ACTIVATE = 0x56450001
_OP_FUND = 0x56450002
_OP_ACCEPT = 0x56450003
_OP_DISPUTE = 0x56450004
_OP_ORACLE = 0x56450005
_OP_RESOLVE = 0x56450006
_OP_TIMEOUT = 0x56450007
_OP_RECOVER = 0x56450008

_STATE_NAMES = {
    0: "intent_created",
    1: "awaiting_nft",
    2: "awaiting_buyer_funds",
    3: "funded_review",
    4: "nft_release_pending",
    5: "delivered_dispute_window",
    6: "disputed",
    7: "nft_return_pending",
    8: "seller_payout_pending",
    9: "buyer_refund_pending",
    10: "settled",
    11: "refunded",
    12: "expired",
    13: "manual_review",
}
_GETTER_FIELDS = (
    "contract_state",
    "deadline_unix",
    "observed_chain_time_unix",
    "dispute_phase",
    "nft_in_escrow",
    "principal_locked",
    "recovery_previous_owner",
    "recovery_item_address",
)
_DIRECT_OPCODES = {
    _OP_ACTIVATE,
    _OP_FUND,
    _OP_ACCEPT,
    _OP_DISPUTE,
    _OP_RESOLVE,
    _OP_TIMEOUT,
    _OP_RECOVER,
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _cell_hash(cell: Any) -> str:
    return cell.get_hash(0).hex()


def _normalise_hash(value: object) -> str | None:
    if isinstance(value, bytes) and len(value) == 32:
        return value.hex()
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if len(candidate) == 64:
        try:
            bytes.fromhex(candidate)
            return candidate.lower()
        except ValueError:
            pass
    try:
        raw = base64.b64decode(candidate + "=" * (-len(candidate) % 4), validate=True)
    except (ValueError, TypeError):
        return None
    return raw.hex() if len(raw) == 32 else None


def _canonical_address(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        from pytoniq_core import Address

        return Address(value.strip()).to_str(is_user_friendly=False)
    except Exception:
        return None


def _hash_part(value: str) -> str:
    from pytoniq_core import Address

    return Address(value).hash_part.hex()


def _parse_shard(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("shard must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        raw = value.strip()
        if raw.startswith("-"):
            result = int(raw, 10)
        elif raw.lower().startswith("0x"):
            result = int(raw, 16)
        elif len(raw) == 16 and all(ch in "0123456789abcdefABCDEF" for ch in raw):
            result = int(raw, 16)
        else:
            result = int(raw, 10)
    else:
        raise ValueError("missing shard")
    if result >= 1 << 63:
        result -= 1 << 64
    if not -(1 << 63) <= result < (1 << 63):
        raise ValueError("shard outside int64 range")
    return result


def _untrusted_boc(value: object) -> Any | None:
    """Decode a candidate BOC for discovery only. This never establishes trust."""
    if not isinstance(value, str) or not value:
        return None
    try:
        from pytoniq_core import Cell

        raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
        cells = Cell.from_boc(raw)
        return cells[0] if cells else None
    except Exception:
        return None


def _candidate_opcode(in_msg: dict[str, Any]) -> int | None:
    for value in (
        in_msg.get("opcode"),
        in_msg.get("op_code"),
        (in_msg.get("message_content") or {}).get("opcode")
        if isinstance(in_msg.get("message_content"), dict)
        else None,
    ):
        if isinstance(value, bool):
            continue
        try:
            if isinstance(value, str):
                raw = value.strip().lower()
                result = int(raw, 16) if raw.startswith("0x") else int(raw)
            elif isinstance(value, int):
                result = value
            else:
                continue
            if 0 <= result < (1 << 32):
                return result
        except (TypeError, ValueError):
            continue
    body = (
        (in_msg.get("message_content") or {}).get("body")
        if isinstance(in_msg.get("message_content"), dict)
        else None
    )
    cell = _untrusted_boc(body)
    if cell is not None:
        try:
            parser = cell.begin_parse()
            if parser.remaining_bits >= 32:
                return parser.load_uint(32)
        except Exception:
            pass
    return None


def _candidate_type(opcode: int, state: int | None = None) -> EscrowChainEventType | None:
    """Map an opcode to a provisional event label for database lookup only.

    State-dependent meanings are resolved exclusively after a proof-checked
    transaction and a proof-read DealEscrow storage snapshot.
    """
    if opcode == _OP_ACTIVATE:
        return EscrowChainEventType.CONTRACT_ACTIVATED
    if opcode == _OP_FUND:
        return EscrowChainEventType.BUYER_PAYMENT_ACCEPTED
    if opcode == _OP_ACCEPT:
        return EscrowChainEventType.BUYER_ACCEPTANCE_RECORDED
    if opcode == _OP_DISPUTE:
        return EscrowChainEventType.DISPUTE_OPENED_ONCHAIN
    if opcode == _OP_RESOLVE:
        return EscrowChainEventType.DISPUTE_RESOLUTION_ACCEPTED
    if opcode == _OP_TIMEOUT:
        return EscrowChainEventType.DEAL_TIMEOUT_ACCEPTED
    if opcode == _OP_RECOVER:
        return EscrowChainEventType.RECOVERY_NFT_RETURN_STARTED
    if opcode == _OP_ORACLE:
        return EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED
    if opcode == _NFT_NOTIFICATION_OPCODE:
        return EscrowChainEventType.NFT_DEPOSIT_ACCEPTED
    return None


class PytoniqTONTestnetEscrowProvider:
    """Testnet-only TON provider whose decisions are based on LiteServer proofs.

    `http_client` and `lite_client_factory` are injectable for deterministic tests.
    The default factory builds a trust-level-0 Pytoniq client from TON's public
    testnet config and additionally checks that its configured init key block is in
    Pytoniq's built-in trusted testnet key-block set.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
        *,
        settings: Any | None = None,
        http_client: Any | None = None,
        lite_client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if self._settings.ton_connect_network != "testnet":
            raise ValueError("TON escrow provider only supports TON testnet")
        base = self._settings.ton_center_testnet_base_url.rstrip("/")
        parsed = urlsplit(base)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "testnet.toncenter.com"
            or parsed.path.rstrip("/") != "/api/v3"
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("TON escrow discovery must use the official testnet TON Center v3 endpoint")
        self._base_url = base
        self._session_factory = session_factory
        self._http = http_client
        self._owns_http = http_client is None
        if self._http is None:
            headers = {"accept": "application/json"}
            api_key = getattr(self._settings, "ton_center_api_key", None)
            if api_key is not None:
                headers["X-API-Key"] = api_key.get_secret_value()
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=self._settings.ton_center_timeout_seconds,
            )
        self._lite_factory = lite_client_factory
        self._lite = None
        self._lite_lock = asyncio.Lock()
        self._closed = False

    async def close(self) -> None:
        self._closed = True
        if self._lite is not None:
            client, self._lite = self._lite, None
            try:
                await client.close()
            except Exception:
                logger.warning("Could not close Pytoniq testnet client", exc_info=True)
        if self._owns_http and self._http is not None:
            await self._http.aclose()

    async def _get_lite_client(self) -> Any:
        async with self._lite_lock:
            if self._closed:
                raise EscrowProviderUnavailable("TON escrow provider is closed")
            if self._lite is not None:
                return self._lite
            try:
                if self._lite_factory is None:
                    from pytoniq.liteclient.client import LiteClient

                    client = await asyncio.to_thread(
                        LiteClient.from_testnet_config,
                        trust_level=0,
                        timeout=int(self._settings.ton_center_timeout_seconds),
                    )
                else:
                    client = self._lite_factory()
                    if hasattr(client, "__await__"):
                        client = await client
                if getattr(client, "trust_level", None) != 0:
                    raise EscrowProviderInvalidEvidence("Pytoniq trust_level must be 0")
                await client.connect()
                if getattr(client, "trust_level", None) != 0:
                    raise EscrowProviderInvalidEvidence("Pytoniq trust_level changed after connect")
                if self._lite_factory is None:
                    from pytoniq.liteclient.utils import init_testnet_blocks

                    init_block = getattr(client, "init_key_block", None)
                    if init_block is None or not any(
                        getattr(init_block, "seqno", None) == known.seqno
                        and getattr(init_block, "root_hash", None) == known.root_hash
                        and getattr(init_block, "file_hash", None) == known.file_hash
                        for known in init_testnet_blocks
                    ):
                        await client.close()
                        raise EscrowProviderInvalidEvidence(
                            "Pytoniq testnet init key block is not in the built-in trust set"
                        )
                if getattr(client, "last_mc_block", None) is None:
                    await client.close()
                    raise EscrowProviderUnavailable("Pytoniq did not establish a trusted masterchain head")
                self._lite = client
                return client
            except (EscrowProviderInvalidEvidence, EscrowProviderUnavailable):
                raise
            except Exception as exc:
                raise EscrowProviderUnavailable(
                    "Could not establish a trusted TON testnet LiteServer session"
                ) from exc

    async def _deals(self) -> list[EscrowDeal]:
        async with self._session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(EscrowDeal)
                        .where(
                            EscrowDeal.network == "testnet",
                            EscrowDeal.contract_address.is_not(None),
                            EscrowDeal.deployment_snapshot_json.is_not(None),
                        )
                        .order_by(EscrowDeal.created_at, EscrowDeal.id)
                    )
                ).all()
            )

    async def _discover_transactions(
        self, address: str, *, start_lt: int | None, limit: int
    ) -> list[dict[str, Any]]:
        params: dict[str, object] = {
            "account": address,
            "sort": "asc",
            "limit": limit,
            "include_msg_body": "true",
        }
        if start_lt is not None:
            params["start_lt"] = start_lt
        try:
            response = await self._http.get("/transactions", params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise EscrowProviderUnavailable(
                "TON Center testnet candidate discovery failed"
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("transactions"), list):
            raise EscrowProviderInvalidEvidence("TON Center returned malformed transaction discovery data")
        rows = data["transactions"]
        if len(rows) > limit or any(not isinstance(row, dict) for row in rows):
            raise EscrowProviderInvalidEvidence("TON Center returned an invalid candidate page")
        return rows

    async def scan_events(self, *, cursor: str | None, limit: int) -> ChainEventBatch:
        if limit < 1 or limit > 100:
            raise ValueError("escrow scan limit must be between 1 and 100")
        if self._closed:
            raise EscrowProviderUnavailable("TON escrow provider is closed")
        cursor_state: dict[str, Any] = {"version": 1, "last_lt_by_address": {}}
        if cursor:
            try:
                parsed = json.loads(cursor)
                if (
                    not isinstance(parsed, dict)
                    or parsed.get("version") != 1
                    or not isinstance(parsed.get("last_lt_by_address"), dict)
                ):
                    raise ValueError("unsupported cursor shape")
                cursor_state = {
                    "version": 1,
                    "last_lt_by_address": {
                        str(key): str(value)
                        for key, value in parsed["last_lt_by_address"].items()
                    },
                }
                if any(
                    not isinstance(value, str)
                    or not value.isdecimal()
                    or int(value) < 0
                    for value in cursor_state["last_lt_by_address"].values()
                ):
                    raise ValueError("invalid logical-time cursor")
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise EscrowProviderInvalidEvidence("Escrow scan cursor is malformed") from exc

        deals = await self._deals()
        address_to_deal: dict[str, EscrowDeal] = {}
        for deal in deals:
            canonical = _canonical_address(deal.contract_address)
            if canonical is None or canonical in address_to_deal:
                raise EscrowProviderInvalidEvidence("Duplicate or malformed escrow contract address")
            address_to_deal[canonical] = deal
        if not address_to_deal:
            return ChainEventBatch(events=(), next_cursor=cursor)

        per_account_limit = max(1, min(100, (limit + len(address_to_deal) - 1) // len(address_to_deal) + 1))
        scanned: list[tuple[int, int, str, dict[str, Any], EscrowDeal]] = []
        for address, deal in address_to_deal.items():
            previous = cursor_state["last_lt_by_address"].get(address)
            start_lt = int(previous) + 1 if previous is not None else 0
            rows = await self._discover_transactions(
                address, start_lt=start_lt, limit=per_account_limit
            )
            for row in rows:
                try:
                    lt = int(row["lt"])
                    block_ref = row["block_ref"]
                    mc_seqno = int(row["mc_block_seqno"])
                    now = int(row.get("now") or 0)
                    workchain = int(block_ref["workchain"])
                    shard = _parse_shard(block_ref["shard"])
                    block_seqno = int(block_ref["seqno"])
                except (KeyError, TypeError, ValueError) as exc:
                    # An unparseable candidate cannot safely advance this account's cursor.
                    raise EscrowProviderInvalidEvidence(
                        "TON Center returned malformed block or logical-time metadata"
                    ) from exc
                if lt < start_lt or mc_seqno <= 0 or block_seqno <= 0:
                    continue
                scanned.append((mc_seqno, now, address, row, deal))
        scanned.sort(
            key=lambda item: (
                item[0],
                item[1],
                int(item[3]["lt"]),
                item[2],
            )
        )
        selected = scanned[:limit]
        events: list[NormalizedChainEvent] = []
        next_cursor_state = {
            "version": 1,
            "last_lt_by_address": dict(cursor_state["last_lt_by_address"]),
        }
        for mc_seqno, _now, address, row, deal in selected:
            lt = int(row["lt"])
            old = next_cursor_state["last_lt_by_address"].get(address)
            if old is not None and lt <= int(old):
                continue
            # Advance over every selected transaction, including unrelated opcodes.
            # This is only a discovery cursor; event confirmation requires a proof.
            next_cursor_state["last_lt_by_address"][address] = str(lt)
            in_msg = row.get("in_msg")
            if not isinstance(in_msg, dict):
                continue
            opcode = _candidate_opcode(in_msg)
            event_type = _candidate_type(opcode, -1) if opcode is not None else None
            if event_type is None:
                # State-dependent oracle/timeout events are emitted only for opcodes
                # known to the escrow protocol; the verified phase selects final semantics.
                continue
            transaction_hash = _normalise_hash(row.get("hash"))
            message_hash = _normalise_hash(
                in_msg.get("hash")
                or in_msg.get("hash_norm")
                or (
                    (in_msg.get("message_content") or {}).get("hash")
                    if isinstance(in_msg.get("message_content"), dict)
                    else None
                )
            )
            try:
                block_ref = row["block_ref"]
                if not transaction_hash or not message_hash:
                    continue
                lt = int(row["lt"])
                source = _canonical_address(in_msg.get("source"))
                destination = _canonical_address(in_msg.get("destination"))
                evidence_sha256 = _sha256(row)
                trace_id = hashlib.sha256(
                    f"{address}|{transaction_hash}|{message_hash}|{lt}".encode()
                ).hexdigest()
                body = (
                    (in_msg.get("message_content") or {}).get("body")
                    if isinstance(in_msg.get("message_content"), dict)
                    else None
                )
                body_cell = _untrusted_boc(body)
                query_id = None
                if body_cell is not None:
                    try:
                        parser = body_cell.begin_parse()
                        if parser.remaining_bits >= 96:
                            if parser.load_uint(32) == opcode:
                                query_id = str(parser.load_uint(64))
                    except Exception:
                        query_id = None
                events.append(
                    NormalizedChainEvent(
                        network="testnet",
                        transaction_hash=transaction_hash,
                        event_index=0,
                        event_type=event_type,
                        contract_address=address,
                        deal_id=str(deal.id),
                        source_address=source,
                        destination_address=destination,
                        item_address=deal.item_address,
                        amount_nanotons=(
                            int(in_msg.get("value", 0))
                            if str(in_msg.get("value", "0")).isdecimal() else None
                        ),
                        masterchain_seqno=mc_seqno,
                        # This is only a candidate eligibility bit. The observer calls
                        # verify_event before treating it as final.
                        finalized=True,
                        evidence_sha256=evidence_sha256,
                        cursor=f"{address}:{lt}",
                        collection_address=deal.collection_address_snapshot,
                        message_hash=message_hash,
                        trace_id=trace_id,
                        logical_time=lt,
                        phase="contract_in",
                        attempt_id=query_id or message_hash[:32],
                        query_id=query_id,
                        operation_id=f"0x{opcode:08x}",
                        deal_salt=deal.deal_salt,
                        account_address=address,
                        candidate_workchain=int(block_ref["workchain"]),
                        candidate_shard=_parse_shard(block_ref["shard"]),
                        candidate_block_seqno=int(block_ref["seqno"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                # Never advance a malformed row as if it represented a verified event.
                next_cursor_state["last_lt_by_address"].pop(address, None)
                raise EscrowProviderInvalidEvidence("Malformed indexed event candidate")
        next_cursor = _canonical_json(next_cursor_state)
        return ChainEventBatch(events=tuple(events), next_cursor=next_cursor)

    async def _trusted_shard_and_masterchain(
        self, event: NormalizedChainEvent, client: Any
    ) -> tuple[Any, Any, Any]:
        if (
            event.candidate_workchain is None
            or event.candidate_shard is None
            or event.candidate_block_seqno is None
        ):
            raise EscrowProviderInvalidEvidence("Candidate block locator is missing")
        try:
            shard_id, _block = await client.lookup_block(
                event.candidate_workchain,
                event.candidate_shard,
                event.candidate_block_seqno,
            )
            if (
                shard_id.workchain != event.candidate_workchain
                or shard_id.shard != event.candidate_shard
                or shard_id.seqno != event.candidate_block_seqno
            ):
                raise EscrowProviderInvalidEvidence("LiteServer returned a different shard block")
            # This call validates that the shard block is included by a masterchain
            # block and verifies the masterchain chain from the trusted key block.
            proof_result = await client.liteserver_request(
                "getShardBlockProof", {"id": shard_id.to_dict()}
            )
            master_id = __import__(
                "pytoniq_core.tl.block", fromlist=["BlockIdExt"]
            ).BlockIdExt.from_dict(proof_result["masterchain_id"])
            await client.get_mc_block_proof(
                known_block=client.last_key_block, target_block=master_id
            )
            await client.get_shard_block_proof(shard_id, prove_mc=True)
            latest_mc = await client.get_trusted_last_mc_block()
        except EscrowProviderInvalidEvidence:
            raise
        except Exception as exc:
            raise EscrowProviderUnavailable("Could not verify TON block inclusion proof") from exc
        if master_id.seqno != event.masterchain_seqno:
            raise EscrowProviderInvalidEvidence(
                "Indexed masterchain sequence does not match the LiteServer inclusion proof"
            )
        minimum_head = master_id.seqno + self._settings.ton_escrow_finality_min_depth
        if latest_mc.seqno < minimum_head:
            raise EscrowProviderUnavailable("Candidate has not reached the configured finality depth")
        return shard_id, master_id, latest_mc

    async def _read_contract_state(
        self, deal: EscrowDeal, masterchain_id: Any, client: Any
    ) -> tuple[dict[str, object], str, str]:
        stored = deal.deployment_snapshot_json
        stored_hash = deal.deployment_snapshot_sha256
        if (
            not isinstance(stored, dict)
            or not isinstance(stored_hash, str)
            or _sha256(stored) != stored_hash
        ):
            raise EscrowProviderInvalidEvidence("Persisted deployment snapshot hash mismatch")
        try:
            snapshot = DealEscrowDeploymentSnapshot(**stored)
            validate_snapshot(snapshot)
            derived = derive_deployment(load_pinned_code_boc(), snapshot)
            if _canonical_address(derived.address) != _canonical_address(deal.contract_address):
                raise EscrowProviderInvalidEvidence("Contract address differs from pinned constructor snapshot")
            account, _shard_account = await client.raw_get_account_state(
                deal.contract_address, block=masterchain_id
            )
            if account is None or account.storage.state.type_ != "account_active":
                raise EscrowProviderInvalidEvidence("DealEscrow account is not active at the proof block")
            state_init = account.storage.state.state_init
            code = state_init.code
            data = state_init.data
            artifacts = verify_compiled_code(load_pinned_code_boc())
            if _cell_hash(code).upper() != artifacts.code_hash.upper():
                raise EscrowProviderInvalidEvidence("Deployed DealEscrow code hash differs from pinned code")
            decoded = decode_storage_cell(data)
            expected_salt = int(snapshot.deal_salt, 16)
            normalized_expect = {
                "network_id": snapshot.network_id,
                "protocol_version": snapshot.protocol_version,
                "seller_address": _canonical_address(snapshot.seller_address),
                "buyer_address": _canonical_address(snapshot.buyer_address),
                "item_address": _canonical_address(snapshot.item_address),
                "collection_address": _canonical_address(snapshot.collection_address),
                "deal_salt": f"{expected_salt:064x}",
                "principal_nanotons": snapshot.principal_nanotons,
                "execution_reserve_nanotons": snapshot.execution_reserve_nanotons,
                "seller_deployment_refund_nanotons": snapshot.seller_deployment_refund_nanotons,
                "nft_transfer_value_nanotons": snapshot.nft_transfer_value_nanotons,
                "fund_query_id": snapshot.fund_query_id,
                "nft_deposit_query_id": snapshot.nft_deposit_query_id,
                "nft_release_query_id": snapshot.nft_release_query_id,
                "nft_return_to_escrow_query_id": snapshot.nft_return_to_escrow_query_id,
                "oracle_key_a": snapshot.oracle_key_a,
                "oracle_key_b": snapshot.oracle_key_b,
                "oracle_key_c": snapshot.oracle_key_c,
                "resolver_key_a": snapshot.resolver_key_a,
                "resolver_key_b": snapshot.resolver_key_b,
                "resolver_key_c": snapshot.resolver_key_c,
            }
            for key, expected in normalized_expect.items():
                actual = decoded.get(key)
                if actual != expected:
                    raise EscrowProviderInvalidEvidence(f"On-chain constructor field mismatch: {key}")
        except EscrowProviderInvalidEvidence:
            raise
        except Exception as exc:
            raise EscrowProviderInvalidEvidence("Could not decode or compare DealEscrow state") from exc
        try:
            master_block = await client.raw_get_block(masterchain_id)
            observed_time = int(master_block.info.gen_utime)
        except Exception as exc:
            raise EscrowProviderUnavailable("Could not obtain verified masterchain timestamp") from exc
        decoded["observed_chain_time_unix"] = observed_time
        snapshot_values = {
            field: decoded[field]
            for field in _GETTER_FIELDS
            if field in decoded
        }
        if len(snapshot_values) != len(_GETTER_FIELDS):
            raise EscrowProviderInvalidEvidence("Decoded DealEscrow getter state is incomplete")
        state_number = int(decoded["contract_state"])
        if state_number not in _STATE_NAMES:
            raise EscrowProviderInvalidEvidence("DealEscrow getter returned an unknown state")
        state_name = _STATE_NAMES[state_number]
        data_hash = _cell_hash(data)
        getter_identity = {
            "contract_address": deal.contract_address,
            "masterchain_seqno": masterchain_id.seqno,
            "masterchain_block_hash": _cell_hash(master_block.serialize()),
            "state_data_hash": data_hash,
            "code_hash": _cell_hash(code),
            "snapshot_sha256": stored_hash,
            "getter": decoded,
        }
        return decoded, state_name, _sha256(getter_identity)

    def _decode_direct_body(
        self, body: Any, opcode: int, deal: EscrowDeal
    ) -> tuple[int, int, int | None]:
        try:
            parser = body.begin_parse()
            if parser.load_uint(32) != opcode:
                raise ValueError("opcode changed")
            query_id = parser.load_uint(64)
            salt = parser.load_uint(256)
            expected_salt = int(deal.deal_salt, 16)
            if salt != expected_salt or query_id <= 0:
                raise ValueError("query ID/deal salt mismatch")
            reason_hash = parser.load_uint(256) if opcode == _OP_DISPUTE else None
            if opcode == _OP_DISPUTE and (reason_hash is None or reason_hash == 0):
                raise ValueError("dispute reason hash is missing")
            return query_id, salt, reason_hash
        except Exception as exc:
            raise EscrowProviderInvalidEvidence("Direct escrow message body failed ABI validation") from exc

    def _decode_oracle_attestation(
        self,
        body: Any,
        deal: EscrowDeal,
        inclusion_mc_seqno: int,
        getter: dict[str, object],
    ) -> dict[str, object]:
        try:
            parser = body.begin_parse()
            if parser.load_uint(32) != _OP_ORACLE:
                raise ValueError("unexpected oracle opcode")
            data_cell = parser.load_ref()
            _signatures_cell = parser.load_ref()
            data = data_cell.begin_parse()
            context = data.load_ref().begin_parse()
            route = data.load_ref().begin_parse()
            position = data.load_ref().begin_parse()
            hashes = data.load_ref().begin_parse()
            domain = context.load_uint(32)
            protocol_version = context.load_uint(16)
            network_id = context.load_int(32)
            escrow_address = context.load_address()
            salt = context.load_uint(256)
            action = context.load_uint(8)
            attempt_id = context.load_uint(64)

            item_address = route.load_address()
            source_address = route.load_address()
            destination_address = route.load_address()
            amount_nanotons = route.load_coins()
            query_id = route.load_uint(64)

            attested_mc_seqno = position.load_uint(32)
            attested_lt = position.load_uint(64)
            message_hash = hashes.load_uint(256)
            trace_hash = hashes.load_uint(256)
            evidence_hash = hashes.load_uint(256)

            snapshot = deal.deployment_snapshot_json
            if not isinstance(snapshot, dict):
                raise ValueError("snapshot is missing")
            if (
                domain != _ESCROW_DOMAIN
                or protocol_version != _PROTOCOL_VERSION
                or network_id != _NETWORK_ID
                or _canonical_address(escrow_address.to_str(is_user_friendly=False))
                    != _canonical_address(deal.contract_address)
                or salt != int(deal.deal_salt, 16)
                or attempt_id <= 0
                or query_id != attempt_id
                or attested_mc_seqno <= 0
                or attested_mc_seqno > inclusion_mc_seqno
                or attested_lt <= 0
                or message_hash == 0
                or trace_hash == 0
                or evidence_hash == 0
                or (
                    action != 5
                    and _canonical_address(item_address.to_str(is_user_friendly=False))
                    != _canonical_address(snapshot["item_address"])
                )
                or (action == 5 and item_address is None)
            ):
                raise ValueError("oracle attestation context does not match the deal")
            if action == 5:
                # Recovery is deliberately manual-review-only. The deployed
                # contract verifies both the attested item and prior owner against
                # its pre-transition recovery storage before clearing those fields.
                # The accepted result never authorizes automatic listing release.
                if int(getter["contract_state"]) != 13:
                    raise ValueError("unexpected-NFT recovery must remain in manual review")
            return {
                "action": action,
                "attempt_id": attempt_id,
                "query_id": query_id,
                "item_address": item_address.to_str(is_user_friendly=False),
                "source_address": source_address.to_str(is_user_friendly=False),
                "destination_address": destination_address.to_str(is_user_friendly=False),
                "amount_nanotons": amount_nanotons,
                "attested_masterchain_seqno": attested_mc_seqno,
                "attested_logical_time": attested_lt,
                "message_hash": f"{message_hash:064x}",
                "trace_hash": f"{trace_hash:064x}",
                "evidence_hash": f"{evidence_hash:064x}",
            }
        except Exception as exc:
            raise EscrowProviderInvalidEvidence("Oracle attestation body failed ABI validation") from exc

    def _verified_event(
        self,
        event: NormalizedChainEvent,
        tx: Any,
        deal: EscrowDeal,
        getter: dict[str, object],
        state_name: str,
        oracle: dict[str, object] | None,
        message_source: str | None,
        message_destination: str | None,
        message_value: int,
    ) -> tuple[EscrowChainEventType, str | None, str | None, str | None, str | None, int | None, bool]:
        state = int(getter["contract_state"])
        opcode = int(event.operation_id, 16) if event.operation_id else -1
        snapshot = deal.deployment_snapshot_json
        if not isinstance(snapshot, dict):
            raise EscrowProviderInvalidEvidence("DealEscrow snapshot is missing")
        if opcode in _DIRECT_OPCODES:
            query_id, _salt, _reason_hash = self._decode_direct_body(tx.in_msg.body, opcode, deal)
            expected_state = {
                _OP_ACTIVATE: 1,
                _OP_FUND: 3,
                _OP_ACCEPT: 4,
                _OP_DISPUTE: 6,
                _OP_RECOVER: 7,
            }.get(opcode)
            if opcode == _OP_RESOLVE and state not in {4, 7}:
                raise EscrowProviderInvalidEvidence("ResolveDispute did not reach an allowed state")
            if opcode == _OP_TIMEOUT and state not in {7, 8, 12, 13}:
                raise EscrowProviderInvalidEvidence("TimeoutDeal did not reach an allowed state")
            if expected_state is not None and state != expected_state:
                raise EscrowProviderInvalidEvidence("Direct message and getter state disagree")
            if opcode == _OP_FUND:
                required_amount = int(snapshot["principal_nanotons"]) + int(
                    snapshot["execution_reserve_nanotons"]
                )
                if message_value != required_amount:
                    raise EscrowProviderInvalidEvidence("Buyer funding value is not exact principal plus reserve")
            if opcode == _OP_ACTIVATE and message_source != _canonical_address(snapshot["seller_address"]):
                raise EscrowProviderInvalidEvidence("Only the snapshotted seller may activate the deal")
            if opcode in {_OP_FUND, _OP_ACCEPT} and message_source != _canonical_address(snapshot["buyer_address"]):
                raise EscrowProviderInvalidEvidence("Buyer action source does not match the snapshot")
            if opcode == _OP_RESOLVE:
                event_type = EscrowChainEventType.DISPUTE_RESOLUTION_ACCEPTED
            elif opcode == _OP_TIMEOUT:
                event_type = EscrowChainEventType.DEAL_TIMEOUT_ACCEPTED
            elif opcode == _OP_RECOVER:
                event_type = EscrowChainEventType.RECOVERY_NFT_RETURN_STARTED
            else:
                event_type = {
                    _OP_ACTIVATE: EscrowChainEventType.CONTRACT_ACTIVATED,
                    _OP_FUND: EscrowChainEventType.BUYER_PAYMENT_ACCEPTED,
                    _OP_ACCEPT: EscrowChainEventType.BUYER_ACCEPTANCE_RECORDED,
                    _OP_DISPUTE: EscrowChainEventType.DISPUTE_OPENED_ONCHAIN,
                }[opcode]
            source = message_source
            destination = message_destination
            item = _canonical_address(snapshot["item_address"])
            collection = _canonical_address(snapshot["collection_address"])
            amount = message_value
            accepted = False
            if opcode == _OP_RECOVER:
                recovery_item = _canonical_address(getter.get("recovery_item_address"))
                recovery_owner = _canonical_address(getter.get("recovery_previous_owner"))
                if (
                    state != 7
                    or not bool(getter.get("nft_in_escrow"))
                    or recovery_item is None
                    or recovery_owner is None
                    or source != recovery_owner
                    or destination != _canonical_address(deal.contract_address)
                ):
                    raise EscrowProviderInvalidEvidence(
                        "Unexpected NFT recovery does not match the proof-read recovery state"
                    )
                item = recovery_item
        elif opcode == _NFT_NOTIFICATION_OPCODE:
            parser = tx.in_msg.body.begin_parse()
            if parser.load_uint(32) != _NFT_NOTIFICATION_OPCODE:
                raise EscrowProviderInvalidEvidence("NFT notification opcode mismatch")
            query_id = parser.load_uint(64)
            previous_owner = parser.load_address()
            is_ref = parser.load_bit()
            payload_cell = parser.load_ref() if is_ref else parser.to_cell()
            payload = payload_cell.begin_parse()
            if payload.load_uint(32) != _NFT_FORWARD_MAGIC:
                raise EscrowProviderInvalidEvidence("TEP-62 forward payload magic mismatch")
            salt = payload.load_uint(256)
            if query_id <= 0 or salt != int(deal.deal_salt, 16):
                raise EscrowProviderInvalidEvidence("TEP-62 notification query/deal salt mismatch")
            previous_owner_address = previous_owner.to_str(is_user_friendly=False)
            item = _canonical_address(message_source)
            collection = _canonical_address(snapshot["collection_address"])
            if item != _canonical_address(snapshot["item_address"]):
                raise EscrowProviderInvalidEvidence("TEP-62 notification came from a different NFT item")
            if state == 2:
                if _canonical_address(previous_owner_address) != _canonical_address(snapshot["seller_address"]):
                    raise EscrowProviderInvalidEvidence("Initial NFT deposit did not come from the seller")
                event_type = EscrowChainEventType.NFT_DEPOSIT_ACCEPTED
            elif state == 7:
                if _canonical_address(previous_owner_address) != _canonical_address(snapshot["buyer_address"]):
                    raise EscrowProviderInvalidEvidence("NFT return did not come from the buyer")
                event_type = EscrowChainEventType.NFT_RETURN_EVIDENCE_OBSERVED
            elif state == 13:
                event_type = EscrowChainEventType.MANUAL_REVIEW_REQUIRED
            else:
                raise EscrowProviderInvalidEvidence("TEP-62 notification/getter state mismatch")
            source = previous_owner_address
            destination = _canonical_address(deal.contract_address)
            amount = None
            accepted = False
        elif opcode == _OP_ORACLE:
            if oracle is None:
                raise EscrowProviderInvalidEvidence("Oracle attestation data is missing")
            action = int(oracle["action"])
            expected_routes = {
                1: ("contract", "buyer", {5, 8}, 0),
                2: ("contract", "seller", {9, 12}, 0),
                3: ("contract", "seller", {10}, int(snapshot["principal_nanotons"])),
                4: ("contract", "buyer", {11}, int(snapshot["principal_nanotons"])),
                5: ("contract", None, {13}, 0),
            }
            if action not in expected_routes:
                raise EscrowProviderInvalidEvidence("Unknown oracle attestation action")
            source_role, destination_role, expected_states, expected_amount = expected_routes[action]
            source = _canonical_address(oracle["source_address"])
            destination = _canonical_address(oracle["destination_address"])
            item = _canonical_address(oracle["item_address"])
            collection = _canonical_address(snapshot["collection_address"])
            amount = int(oracle["amount_nanotons"])
            expected_source = _canonical_address(deal.contract_address)
            expected_dest = (
                _canonical_address(snapshot["buyer_address"])
                if destination_role == "buyer"
                else _canonical_address(snapshot["seller_address"])
                if destination_role == "seller"
                else _canonical_address(oracle["destination_address"])
                if action == 5
                else _canonical_address(getter.get("recovery_previous_owner"))
            )
            item_matches_snapshot = item == _canonical_address(snapshot["item_address"])
            recovery_action = action == 5 and state == 13
            if (
                state not in expected_states
                or source != expected_source
                or expected_dest is None
                or destination != expected_dest
                or amount != expected_amount
                or (not item_matches_snapshot and not recovery_action)
                or _canonical_address(message_source) is None
                or int(oracle["evidence_hash"], 16) != int(getter.get("last_evidence_hash", "0"), 16)
            ):
                raise EscrowProviderInvalidEvidence("Oracle attestation route/evidence disagrees with getter state")
            event_type = {
                (1, 5): EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED,
                (1, 8): EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED,
                (2, 9): EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED,
                (2, 12): EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED,
                (3, 10): EscrowChainEventType.SELLER_PAYOUT_RECONCILED,
                (4, 11): EscrowChainEventType.BUYER_REFUND_RECONCILED,
                (5, 13): EscrowChainEventType.MANUAL_REVIEW_REQUIRED,
            }.get((action, state))
            if event_type is None:
                raise EscrowProviderInvalidEvidence("Oracle action and final contract state are inconsistent")
            accepted = True
        else:
            raise EscrowProviderInvalidEvidence("The candidate opcode is not part of the DealEscrow v1 ABI")
        return event_type, source, destination, item, collection, amount, accepted

    async def verify_event(self, event: NormalizedChainEvent) -> FinalityVerification | None:
        if event.network != "testnet" or not event.deal_id:
            raise EscrowProviderInvalidEvidence("Event is not bound to a testnet escrow deal")
        client = await self._get_lite_client()
        async with self._session_factory() as session:
            deal = await session.scalar(select(EscrowDeal).where(EscrowDeal.id == event.deal_id))
        if (
            deal is None
            or deal.network != "testnet"
            or _canonical_address(deal.contract_address) != _canonical_address(event.contract_address)
            or deal.contract_address is None
        ):
            raise EscrowProviderInvalidEvidence("Event contract/deal binding mismatch")
        try:
            shard_id, master_id, _latest = await self._trusted_shard_and_masterchain(event, client)
            transactions = await client.raw_get_block_transactions_ext(shard_id, count=1024)
            contract_hash_part = _hash_part(deal.contract_address)
            matches = [
                tx for tx in transactions
                if getattr(tx, "account_addr_hex", "") == contract_hash_part
                and int(getattr(tx, "lt", -1)) == event.logical_time
                and _cell_hash(tx.cell) == event.transaction_hash
            ]
            if len(matches) != 1:
                raise EscrowProviderInvalidEvidence("Candidate transaction was not uniquely proven in the shard block")
            tx = matches[0]
            message = getattr(tx, "in_msg", None)
            if message is None or not message.is_internal:
                raise EscrowProviderInvalidEvidence("Escrow transaction has no internal input message")
            message_hash = _cell_hash(message.serialize())
            if message_hash != event.message_hash:
                raise EscrowProviderInvalidEvidence("Incoming message hash differs from the indexed candidate")
            if _canonical_address(message.info.dest.to_str(is_user_friendly=False)) != _canonical_address(deal.contract_address):
                raise EscrowProviderInvalidEvidence("Proven incoming message destination is not the escrow")
            description = getattr(tx, "description", None)
            compute = getattr(description, "compute_ph", None)
            action_phase = getattr(description, "action", None)
            if (
                bool(getattr(description, "aborted", True))
                or compute is None
                or getattr(compute, "type_", None) != "vm"
                or not bool(getattr(compute, "success", False))
                or (action_phase is not None and not bool(getattr(action_phase, "success", False)))
            ):
                raise EscrowProviderInvalidEvidence("DealEscrow transaction did not execute successfully")
            getter, state_name, getter_identity_sha = await self._read_contract_state(
                deal, master_id, client
            )
            opcode = message.body.begin_parse().load_uint(32)
            oracle = (
                self._decode_oracle_attestation(message.body, deal, master_id.seqno, getter)
                if opcode == _OP_ORACLE
                else None
            )
            source = (
                message.info.src.to_str(is_user_friendly=False)
                if getattr(message.info, "src", None) is not None else None
            )
            destination = (
                message.info.dest.to_str(is_user_friendly=False)
                if getattr(message.info, "dest", None) is not None else None
            )
            amount = int(getattr(message.info, "value_coins", 0) or 0)
            event_type, verified_source, verified_destination, item, collection, verified_amount, accepted = (
                self._verified_event(
                    event, tx, deal, getter, state_name, oracle, source, destination, amount
                )
            )
            # The proof's local trace identity is derived only from the actually
            # included transaction and message; the V3 trace_id is not trusted.
            trace_id = hashlib.sha256(
                f"{deal.contract_address}|{event.transaction_hash}|{message_hash}|{tx.lt}".encode()
            ).hexdigest()
            if trace_id != event.trace_id:
                raise EscrowProviderInvalidEvidence("Transaction/message trace binding mismatch")
            block = await client.raw_get_block(master_id)
            block_hash = master_id.root_hash.hex()
            proof_digest = _sha256(
                {
                    "provider": _PROVIDER_ID,
                    "trusted_init_key_block": client.init_key_block.root_hash.hex(),
                    "shard_block_seqno": shard_id.seqno,
                    "shard_block_hash": shard_id.root_hash.hex(),
                    "masterchain_seqno": master_id.seqno,
                    "masterchain_block_hash": block_hash,
                    "transaction_hash": event.transaction_hash,
                    "message_hash": message_hash,
                    "transaction_lt": tx.lt,
                    "contract_data_hash": getter_identity_sha,
                    "contract_state": state_name,
                    "attestation": oracle,
                    "generation_time": int(block.info.gen_utime),
                }
            )
            getter_snapshot = dict(getter)
            getter_snapshot["observed_chain_time_unix"] = int(block.info.gen_utime)
            getter_snapshot_sha = _sha256(getter_snapshot)
            return FinalityVerification(
                network="testnet",
                transaction_hash=event.transaction_hash,
                masterchain_seqno=master_id.seqno,
                masterchain_block_hash=block_hash,
                message_hash=message_hash,
                trace_id=trace_id,
                proof_sha256=proof_digest,
                provider_id=_PROVIDER_ID,
                finalized=True,
                masterchain_inclusion_verified=True,
                trace_binding_verified=True,
                verified_event_type=event_type,
                source_address=verified_source,
                destination_address=verified_destination,
                item_address=item,
                collection_address=collection,
                amount_nanotons=verified_amount,
                observed_contract_state=state_name,
                attestation_accepted=accepted,
                contract_state_reconciled=True,
                getter_snapshot_json=getter_snapshot,
                getter_snapshot_sha256=getter_snapshot_sha,
                getter_snapshot_masterchain_seqno=master_id.seqno,
                getter_snapshot_block_hash=block_hash,
                getter_snapshot_provider=_PROVIDER_ID,
            )
        except (EscrowProviderInvalidEvidence, EscrowProviderUnavailable):
            raise
        except Exception as exc:
            raise EscrowProviderUnavailable("Could not independently verify escrow transaction finality") from exc

    async def verify_terminal_owner(
        self,
        *,
        item_address: str,
        expected_owner_address: str,
        minimum_masterchain_seqno: int,
    ) -> TerminalOwnerVerification | None:
        item = _canonical_address(item_address)
        expected_owner = _canonical_address(expected_owner_address)
        if item is None or expected_owner is None or minimum_masterchain_seqno <= 0:
            raise EscrowProviderInvalidEvidence("Terminal owner query is malformed")
        async with self._session_factory() as session:
            deals = list(
                (
                    await session.scalars(
                        select(EscrowDeal)
                        .where(EscrowDeal.network == "testnet", EscrowDeal.item_address == item)
                        .order_by(EscrowDeal.created_at.desc())
                    )
                ).all()
            )
        collections = {
            _canonical_address(deal.collection_address_snapshot)
            for deal in deals
        }
        collections.discard(None)
        if not deals or len(collections) != 1:
            raise EscrowProviderInvalidEvidence("NFT item is not uniquely bound to a persisted testnet collection")
        collection = next(iter(collections))
        client = await self._get_lite_client()
        try:
            master_id = await client.get_trusted_last_mc_block()
            if master_id.seqno < minimum_masterchain_seqno:
                raise EscrowProviderUnavailable("No trusted masterchain head at requested minimum sequence")
            account, _shard_account = await client.raw_get_account_state(item, block=master_id)
            if account is None or account.storage.state.type_ != "account_active":
                return None
            state_init = account.storage.state.state_init
            data = state_init.data
            if data is None:
                return None
            parser = data.begin_parse()
            index = parser.load_uint(64)
            actual_collection = parser.load_address()
            actual_owner = parser.load_address()
            actual_collection_raw = actual_collection.to_str(is_user_friendly=False)
            actual_owner_raw = actual_owner.to_str(is_user_friendly=False)
            if _canonical_address(actual_collection_raw) != collection:
                raise EscrowProviderInvalidEvidence("TEP-62 collection differs from the persisted NFT listing")
            if _canonical_address(actual_owner_raw) != expected_owner:
                return None
            if index < 0:
                return None
            master_block = await client.raw_get_block(master_id)
            proof_digest = _sha256(
                {
                    "provider": _PROVIDER_ID,
                    "trusted_init_key_block": client.init_key_block.root_hash.hex(),
                    "masterchain_seqno": master_id.seqno,
                    "masterchain_block_hash": master_id.root_hash.hex(),
                    "item_address": item,
                    "collection_address": collection,
                    "item_index": index,
                    "owner_address": _canonical_address(actual_owner_raw),
                    "state_data_hash": _cell_hash(data),
                    "code_hash": _cell_hash(state_init.code),
                    "observed_chain_time_unix": int(master_block.info.gen_utime),
                }
            )
            return TerminalOwnerVerification(
                network="testnet",
                item_address=item,
                owner_address=expected_owner,
                masterchain_seqno=master_id.seqno,
                proof_sha256=proof_digest,
                provider_id=_PROVIDER_ID,
                verified=True,
            )
        except (EscrowProviderInvalidEvidence, EscrowProviderUnavailable):
            raise
        except Exception as exc:
            raise EscrowProviderUnavailable("Could not verify TEP-62 owner from a trusted account-state proof") from exc
