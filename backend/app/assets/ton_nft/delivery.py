"""Read-only TON Center v3 adapter for correlating TEP-62 NFT transfers.

This adapter produces candidate/indexer evidence only. TON Center v3 is an
indexed data layer, not a cryptographic proof source. Callers must not mark an
order completed from a client-supplied hash or current-owner lookup alone.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable

MAX_DELIVERY_RESPONSE_BYTES = 2_000_000
TRANSFER_PAGE_SIZE = 1000
MAX_TRANSFER_ROWS = 5000
MAX_TRACE_TRANSACTIONS = 2000
TEP62_TRANSFER_OPCODE = 0x5FCC3D14


class DeliveryEvidenceStatus(StrEnum):
    """Outcome of a read-only delivery evidence lookup."""

    VERIFIED_FINALIZED = "verified_finalized"
    NOT_FOUND = "not_found"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TEP62TransferIntent:
    """Immutable values captured before a seller is allowed to transfer."""

    item_address: str
    network: str
    seller_wallet_address: str
    buyer_wallet_address: str
    query_id: int
    candidate_transaction_hash: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryEvidenceResult:
    """Typed result; VERIFIED_FINALIZED still carries an indexer trust assumption."""

    status: DeliveryEvidenceStatus
    item_address: str
    network: str
    seller_wallet_address: str
    buyer_wallet_address: str
    query_id: int
    transaction_hash: str | None = None
    trace_id: str | None = None
    masterchain_seqno: int | None = None
    reason: str | None = None
    evidence_source: str = "toncenter_v3_indexer"


@dataclass(frozen=True, slots=True)
class TONCenterDeliveryConfig:
    """Configuration for one network-specific TON Center v3 endpoint."""

    base_url: str
    network: str
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("TON Center base_url must be an absolute HTTP(S) URL")
        if self.network not in {"mainnet", "testnet"}:
            raise ValueError("TON Center delivery network must be mainnet or testnet")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class TONCenterDeliveryEvidenceProvider:
    """Correlate NFT transfer rows with the exact item-account transaction and trace.

    The adapter fails closed on incomplete or inconsistent data. It requires:
    exact item, seller, buyer and query_id; a non-aborted transfer; the exact
    item-account transaction with a TEP-62 transfer inbound message; successful
    compute/action phases; a complete trace; and a positive masterchain end seqno.

    API v3 is an indexed data layer. VERIFIED_FINALIZED means the returned
    indexer record meets these checks; it is not a Merkle-proof verification.
    """

    def __init__(
        self,
        config: TONCenterDeliveryConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        headers = {"X-API-Key": config.api_key} if config.api_key else {}
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(config.timeout_seconds),
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> TONCenterDeliveryEvidenceProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _get_json(self, path: str, params: dict[str, str | int | bool]) -> dict[str, Any]:
        content = bytearray()
        request_headers = {"X-API-Key": self.config.api_key} if self.config.api_key else None
        try:
            async with self._client.stream(
                "GET",
                path,
                params=params,
                headers=request_headers,
            ) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise InvalidProviderData(
                            "TON Center returned invalid Content-Length"
                        ) from exc
                    if declared_length < 0 or declared_length > MAX_DELIVERY_RESPONSE_BYTES:
                        raise InvalidProviderData(
                            "TON Center response exceeds the allowed size"
                        )
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_DELIVERY_RESPONSE_BYTES:
                        raise InvalidProviderData(
                            "TON Center response exceeds the allowed size"
                        )
                    content.extend(chunk)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise ProviderUnavailable("TON Center delivery evidence request failed") from exc

        try:
            payload: object = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidProviderData("TON Center returned non-JSON data") from exc
        if not isinstance(payload, dict):
            raise InvalidProviderData("TON Center response must be a JSON object")
        if payload.get("code") not in (None, 0):
            raise ProviderUnavailable("TON Center returned an API error")
        return cast(dict[str, Any], payload)

    async def _fetch_transfers(self, item_address: str) -> list[dict[str, Any]]:
        """Read all indexed transfer pages for the exact item, with a hard cap."""
        rows: list[dict[str, Any]] = []
        offset = 0
        while offset < MAX_TRANSFER_ROWS:
            payload = await self._get_json(
                "nft/transfers",
                {
                    "item_address": item_address,
                    "limit": TRANSFER_PAGE_SIZE,
                    "offset": offset,
                    "sort": "desc",
                },
            )
            page = payload.get("nft_transfers")
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise InvalidProviderData("TON Center response has no valid nft_transfers array")
            if len(page) > TRANSFER_PAGE_SIZE:
                raise InvalidProviderData("TON Center returned too many NFT transfer rows")
            rows.extend(cast(list[dict[str, Any]], page))
            if len(page) < TRANSFER_PAGE_SIZE:
                return rows
            offset += len(page)
        raise InvalidProviderData(
            "NFT transfer history exceeded the bounded delivery evidence scan"
        )

    async def _fetch_trace(self, trace_id: str) -> dict[str, Any] | None:
        payload = await self._get_json(
            "traces",
            {"trace_id": trace_id, "include_actions": True, "limit": 10, "offset": 0},
        )
        traces = payload.get("traces")
        if not isinstance(traces, list) or any(not isinstance(row, dict) for row in traces):
            raise InvalidProviderData("TON Center response has no valid traces array")
        matching = [
            cast(dict[str, Any], trace)
            for trace in traces
            if isinstance(trace.get("trace_id"), str)
            and self._normalize_hash(trace["trace_id"], "trace_id") == trace_id
        ]
        if len(matching) > 1:
            raise InvalidProviderData("TON Center returned duplicate records for one trace")
        return matching[0] if matching else None

    @staticmethod
    def _normalized_address(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            raise InvalidProviderData(f"TON Center transfer is missing {field_name}")
        try:
            return normalize_address(value)
        except AddressError as exc:
            raise InvalidProviderData(
                f"TON Center transfer has an invalid {field_name}"
            ) from exc

    @staticmethod
    def _parse_uint64(value: object, field_name: str) -> int:
        if isinstance(value, bool):
            raise InvalidProviderData(f"TON Center transfer has an invalid {field_name}")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise InvalidProviderData(
                f"TON Center transfer has an invalid {field_name}"
            ) from exc
        if parsed < 0 or parsed > 2**64 - 1:
            raise InvalidProviderData(f"TON Center transfer has an out-of-range {field_name}")
        return parsed

    @staticmethod
    def _normalize_hash(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidProviderData(f"TON Center data is missing {field_name}")
        normalized = value.strip().lower()
        if normalized.startswith("0x"):
            normalized = normalized[2:]
        if len(normalized) > 128 or any(
            ord(character) < 33 or character.isspace() for character in normalized
        ):
            raise InvalidProviderData(f"TON Center data has an invalid {field_name}")
        return normalized

    @staticmethod
    def _parse_opcode(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value, 16) if value.lower().startswith("0x") else int(value)
            except ValueError:
                return None
        return None

    @classmethod
    def _trace_transactions(cls, trace: dict[str, Any]) -> Iterator[dict[str, Any]]:
        count = 0
        actions = trace.get("actions")
        if not isinstance(actions, list):
            raise InvalidProviderData("TON Center trace is missing its actions array")
        for action in actions:
            if not isinstance(action, dict):
                raise InvalidProviderData("TON Center trace contains an invalid action")
            transactions = action.get("transactions_full")
            if not isinstance(transactions, list):
                raise InvalidProviderData("TON Center action is missing transactions_full")
            for transaction in transactions:
                if not isinstance(transaction, dict):
                    raise InvalidProviderData("TON Center trace contains an invalid transaction")
                count += 1
                if count > MAX_TRACE_TRANSACTIONS:
                    raise InvalidProviderData("TON Center trace contains too many transactions")
                yield cast(dict[str, Any], transaction)

        root = trace.get("trace")
        if root is not None:
            if not isinstance(root, dict):
                raise InvalidProviderData("TON Center trace tree is malformed")

            def walk(node: dict[str, Any], depth: int = 0) -> Iterator[dict[str, Any]]:
                nonlocal count
                if depth > 64:
                    raise InvalidProviderData("TON Center trace tree is too deep")
                transaction = node.get("transaction")
                if transaction is not None:
                    if not isinstance(transaction, dict):
                        raise InvalidProviderData("TON Center trace tree has an invalid transaction")
                    count += 1
                    if count > MAX_TRACE_TRANSACTIONS:
                        raise InvalidProviderData(
                            "TON Center trace contains too many transactions"
                        )
                    yield cast(dict[str, Any], transaction)
                children = node.get("children", [])
                if not isinstance(children, list):
                    raise InvalidProviderData("TON Center trace tree has invalid children")
                for child in children:
                    if not isinstance(child, dict):
                        raise InvalidProviderData("TON Center trace tree has an invalid child")
                    yield from walk(cast(dict[str, Any], child), depth + 1)

            yield from walk(cast(dict[str, Any], root))

    @classmethod
    def _verify_item_transaction(
        cls,
        trace: dict[str, Any],
        *,
        item_address: str,
        seller_address: str,
        transaction_hash: str,
    ) -> str | None:
        matches: dict[tuple[str, str], dict[str, Any]] = {}
        for transaction in cls._trace_transactions(trace):
            account = transaction.get("account")
            if not isinstance(account, str):
                continue
            try:
                normalized_account = normalize_address(account)
            except AddressError:
                continue
            tx_hash = transaction.get("hash")
            if not isinstance(tx_hash, str):
                continue
            normalized_hash = cls._normalize_hash(tx_hash, "item transaction hash")
            if normalized_account == item_address and normalized_hash == transaction_hash:
                key = (normalized_account, normalized_hash)
                previous = matches.get(key)
                if previous is not None and previous != transaction:
                    raise InvalidProviderData(
                        "TON Center trace returned inconsistent copies of the item transaction"
                    )
                matches[key] = transaction
        if not matches:
            return "Trace does not contain the exact NFT item transaction"
        if len(matches) != 1:
            raise InvalidProviderData("TON Center trace contains duplicate item transactions")

        transaction = next(iter(matches.values()))
        incoming = transaction.get("in_msg")
        if not isinstance(incoming, dict):
            return "NFT item transaction has no inbound message"
        try:
            source = cls._normalized_address(incoming.get("source"), "transaction source")
            destination = cls._normalized_address(
                incoming.get("destination"), "transaction destination"
            )
        except InvalidProviderData:
            return "NFT item transaction has incomplete sender/recipient data"
        opcode = cls._parse_opcode(incoming.get("opcode"))
        if (
            source != seller_address
            or destination != item_address
            or opcode != TEP62_TRANSFER_OPCODE
        ):
            return "NFT item transaction is not the expected seller-signed TEP-62 transfer"

        description = transaction.get("description")
        if not isinstance(description, dict):
            return "NFT item transaction is missing its execution description"
        if description.get("aborted") is True:
            return "NFT item transaction was aborted"
        if description.get("aborted") is not False:
            return "NFT item transaction abort status is incomplete"

        compute = description.get("compute_ph")
        if not isinstance(compute, dict):
            return "NFT item transaction is missing its compute phase"
        if compute.get("success") is False:
            return "NFT item transaction compute phase failed"
        if compute.get("success") is not True:
            return "NFT item transaction compute result is incomplete"

        action = description.get("action")
        if not isinstance(action, dict):
            return "NFT item transaction is missing its action phase"
        if action.get("success") is False:
            return "NFT item transaction action phase failed"
        if action.get("success") is not True:
            return "NFT item transaction action result is incomplete"
        return None

    def _result(
        self,
        intent: TEP62TransferIntent,
        status: DeliveryEvidenceStatus,
        *,
        transaction_hash: str | None = None,
        trace_id: str | None = None,
        masterchain_seqno: int | None = None,
        reason: str | None = None,
    ) -> DeliveryEvidenceResult:
        return DeliveryEvidenceResult(
            status=status,
            item_address=intent.item_address,
            network=intent.network,
            seller_wallet_address=intent.seller_wallet_address,
            buyer_wallet_address=intent.buyer_wallet_address,
            query_id=intent.query_id,
            transaction_hash=transaction_hash,
            trace_id=trace_id,
            masterchain_seqno=masterchain_seqno,
            reason=reason,
        )

    async def verify_transfer(
        self,
        intent: TEP62TransferIntent,
    ) -> DeliveryEvidenceResult:
        """Check exact TEP-62 transfer, then inspect its item transaction and finality."""
        try:
            item_address = normalize_address(intent.item_address)
            seller_address = normalize_address(intent.seller_wallet_address)
            buyer_address = normalize_address(intent.buyer_wallet_address)
        except AddressError as exc:
            raise InvalidProviderData("Delivery intent contains an invalid TON address") from exc
        if intent.network != self.config.network:
            raise InvalidProviderData("Delivery intent network does not match the configured provider")
        if (
            isinstance(intent.query_id, bool)
            or not isinstance(intent.query_id, int)
            or intent.query_id < 0
            or intent.query_id > 2**64 - 1
        ):
            raise InvalidProviderData("Delivery intent query_id must be an unsigned 64-bit integer")
        if seller_address == buyer_address:
            raise InvalidProviderData("Seller and buyer wallet snapshots must be different")

        normalized_intent = TEP62TransferIntent(
            item_address=item_address,
            network=intent.network,
            seller_wallet_address=seller_address,
            buyer_wallet_address=buyer_address,
            query_id=intent.query_id,
            candidate_transaction_hash=intent.candidate_transaction_hash,
        )
        transfers = await self._fetch_transfers(item_address)
        candidates: list[dict[str, Any]] = []
        for row in transfers:
            row_item = self._normalized_address(row.get("nft_address"), "nft_address")
            if row_item != item_address:
                continue
            row_query_id = self._parse_uint64(row.get("query_id"), "query_id")
            if row_query_id == intent.query_id:
                candidates.append(row)

        if not candidates:
            return self._result(
                normalized_intent,
                DeliveryEvidenceStatus.NOT_FOUND,
                reason="No indexed TEP-62 transfer has this item and delivery query_id yet",
            )
        if len(candidates) != 1:
            return self._result(
                normalized_intent,
                DeliveryEvidenceStatus.INCONCLUSIVE,
                reason="Multiple indexed transfer rows share this item and delivery query_id",
            )

        transfer = candidates[0]
        transaction_hash = self._normalize_hash(
            transfer.get("transaction_hash"), "transaction_hash"
        )
        trace_id = self._normalize_hash(transfer.get("trace_id"), "trace_id")
        old_owner = self._normalized_address(transfer.get("old_owner"), "old_owner")
        new_owner = self._normalized_address(transfer.get("new_owner"), "new_owner")
        aborted = transfer.get("transaction_aborted")
        if not isinstance(aborted, bool):
            raise InvalidProviderData("TON Center transfer is missing transaction_aborted")
        if aborted:
            return self._result(
                normalized_intent,
                DeliveryEvidenceStatus.FAILED,
                transaction_hash=transaction_hash,
                trace_id=trace_id,
                reason="TON Center indexed the transfer transaction as aborted",
            )
        if old_owner != seller_address or new_owner != buyer_address:
            return self._result(
                normalized_intent,
                DeliveryEvidenceStatus.FAILED,
                transaction_hash=transaction_hash,
                trace_id=trace_id,
                reason="Indexed TEP-62 transfer sender or recipient differs from the immutable intent",
            )

        trace = await self._fetch_trace(trace_id)
        if trace is None:
            return self._result(
                normalized_intent,
                DeliveryEvidenceStatus.INCONCLUSIVE,
                transaction_hash=transaction_hash,
                trace_id=trace_id,
                reason="The transfer trace is not indexed yet",
            )
        if trace.get("is_incomplete") is not False:
            return self._result(
                normalized_intent,
                DeliveryEvidenceStatus.INCONCLUSIVE,
                transaction_hash=transaction_hash,
                trace_id=trace_id,
                reason="The indexed trace is incomplete or has no explicit completeness flag",
            )
        if trace.get("trace_id") != trace_id:
            raise InvalidProviderData("TON Center returned a mismatched trace id")
        raw_mc_seqno = trace.get("mc_seqno_end")
        try:
            mc_seqno = int(raw_mc_seqno)
        except (TypeError, ValueError) as exc:
            raise InvalidProviderData("TON Center trace has no valid mc_seqno_end") from exc
        if mc_seqno <= 0:
            return self._result(
                normalized_intent,
                DeliveryEvidenceStatus.INCONCLUSIVE,
                transaction_hash=transaction_hash,
                trace_id=trace_id,
                reason="The trace has not been committed to a masterchain block",
            )

        transaction_problem = self._verify_item_transaction(
            trace,
            item_address=item_address,
            seller_address=seller_address,
            transaction_hash=transaction_hash,
        )
        if transaction_problem is not None:
            status = (
                DeliveryEvidenceStatus.FAILED
                if any(
                    marker in transaction_problem
                    for marker in ("failed", "aborted", "not the expected")
                )
                else DeliveryEvidenceStatus.INCONCLUSIVE
            )
            return self._result(
                normalized_intent,
                status,
                transaction_hash=transaction_hash,
                trace_id=trace_id,
                masterchain_seqno=mc_seqno,
                reason=transaction_problem,
            )

        return self._result(
            normalized_intent,
            DeliveryEvidenceStatus.VERIFIED_FINALIZED,
            transaction_hash=transaction_hash,
            trace_id=trace_id,
            masterchain_seqno=mc_seqno,
            reason=(
                "TON Center v3 indexed the exact successful TEP-62 item transfer in a complete "
                "trace committed to a masterchain block; this remains an indexed-data trust result"
            ),
        )
