"""TON Center adapter for indexed candidate discovery and TEP-62 contract reads."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import time
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx
from pytoniq_core.boc.address import Address as TonAddress
from pytoniq_core.boc.cell import Cell, CellError
from pytoniq_core.boc.deserialize import BocError

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.errors import (
    InvalidProviderData,
    ProviderUnavailable,
    UnsupportedAsset,
)
from app.assets.ton_nft.metadata import (
    DEFAULT_IPFS_GATEWAY_URL,
    fetch_metadata_json,
    normalize_media_uri,
    normalize_metadata_uri,
    validate_ipfs_gateway_url,
)
from app.assets.ton_nft.models import NFTInventoryPage, NFTItemSnapshot, NFTMetadata

_fetch_metadata_json = fetch_metadata_json
_normalize_uri = normalize_metadata_uri

MAX_PROVIDER_RESPONSE_BYTES = 2_000_000
MAX_PROVIDER_PAGE_SIZE = 1000
MAX_PROVIDER_REQUEST_ATTEMPTS = 2
_PROVIDER_RETRY_BACKOFF_SECONDS = 0.15
_MAX_METADATA_CACHE_ENTRIES = 2048
_METADATA_CACHE_TTL_SECONDS = 600.0
_METADATA_NEGATIVE_CACHE_TTL_SECONDS = 30.0
_METADATA_FETCH_CONCURRENCY = 5
_METADATA_PAGE_ENRICHMENT_TIMEOUT_SECONDS = 8.0


def _stack_parts(entry: object) -> tuple[str, object]:
    """Normalize TON Center v3 typed stack entries and legacy v2-style pairs."""
    if isinstance(entry, dict):
        kind = entry.get("type") or entry.get("@type")
        value = entry.get("value")
    elif isinstance(entry, (list, tuple)) and len(entry) == 2:
        kind, value = entry
    else:
        raise InvalidProviderData("TON Center returned a malformed get-method stack entry")

    if not isinstance(kind, str):
        raise InvalidProviderData("TON Center returned a get-method stack entry without a type")
    normalized_kind = kind.lower()
    for suffix, target in (
        ("number", "num"),
        ("cell", "cell"),
        ("slice", "slice"),
    ):
        if normalized_kind.endswith(suffix):
            normalized_kind = target
            break

    if isinstance(value, dict):
        value = value.get("bytes", value.get("value"))
    return normalized_kind, value


def _stack_integer(entry: object) -> int:
    kind, value = _stack_parts(entry)
    if kind != "num" or isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InvalidProviderData("TON Center returned a non-numeric get-method stack value")
    try:
        return int(value, 0) if isinstance(value, str) else value
    except ValueError as exc:
        raise InvalidProviderData("TON Center returned an invalid get-method integer") from exc


def _stack_address(entry: object) -> str | None:
    kind, value = _stack_parts(entry)
    if kind not in {"cell", "slice"} or not isinstance(value, str):
        raise InvalidProviderData("TON Center returned a non-address get-method stack value")
    try:
        encoded = value.replace("-", "+").replace("_", "/")
        boc = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4),
            validate=True,
        )
        cell = Cell.one_from_boc(boc)
        address = cell.begin_parse().load_address()
    except (binascii.Error, BocError, CellError, IndexError, TypeError, ValueError) as exc:
        raise InvalidProviderData("TON Center returned an invalid address cell") from exc
    if address is None:
        return None
    if not isinstance(address, TonAddress):
        raise InvalidProviderData("TON Center returned an unsupported address type")
    return normalize_address(address.to_str(is_user_friendly=False))


class NFTDataProvider(Protocol):
    async def get_item(self, address: str) -> NFTItemSnapshot | None: ...

    async def get_items_by_owner(
        self, owner_address: str, *, limit: int, offset: int
    ) -> NFTInventoryPage: ...

    async def get_item_address_by_index(
        self, collection_address: str, index: int
    ) -> str | None: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TONCenterV3Config:
    base_url: str
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 8.0
    ipfs_gateway_url: str = DEFAULT_IPFS_GATEWAY_URL

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("TON Center base_url must be an absolute HTTP(S) URL")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        validate_ipfs_gateway_url(self.ipfs_gateway_url)


def _onchain_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    content = raw.get("content")
    if not isinstance(content, dict):
        return {}
    nested = content.get("metadata")
    if isinstance(nested, dict):
        values = {key: value for key, value in content.items() if key not in {"uri", "metadata"}}
        values.update(nested)
        return values
    return {key: value for key, value in content.items() if key != "uri"}


def _metadata_uri(raw: dict[str, Any]) -> object:
    content = raw.get("content")
    if not isinstance(content, dict):
        return None
    uri = content.get("uri")
    if isinstance(uri, str) and uri:
        return uri
    nested = content.get("metadata")
    return nested.get("uri") if isinstance(nested, dict) else None


def _metadata_fields(
    data: dict[str, Any],
    *,
    ipfs_gateway_url: str = DEFAULT_IPFS_GATEWAY_URL,
) -> NFTMetadata:
    attrs = data.get("attributes")
    safe_attrs = (
        tuple(
            {
                "trait_type": str(attribute.get("trait_type", ""))[:100],
                "value": str(attribute.get("value", ""))[:300],
            }
            for attribute in attrs[:50]
            if isinstance(attribute, dict)
        )
        if isinstance(attrs, list)
        else ()
    )
    name = data.get("name")
    description = data.get("description")
    image = data.get("image")
    if not isinstance(image, str) or not image:
        image = data.get("image_url")
    return NFTMetadata(
        name=name[:200] if isinstance(name, str) else None,
        description=description[:2000] if isinstance(description, str) else None,
        image=normalize_media_uri(image, ipfs_gateway_url=ipfs_gateway_url),
        attributes=safe_attrs,
    )


class TONCenterV3Provider:
    """Fetch NFT item snapshots from TON Center and enrich display metadata separately."""

    def __init__(
        self,
        config: TONCenterV3Config,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        headers = {"X-API-Key": self.config.api_key} if self.config.api_key else {}
        self._client = client or httpx.AsyncClient(
            base_url=self.config.base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(self.config.timeout_seconds),
        )
        self._owns_client = client is None
        self._metadata_semaphore = asyncio.Semaphore(_METADATA_FETCH_CONCURRENCY)
        self._metadata_cache: dict[
            str, tuple[float, dict[str, object] | None]
        ] = {}
        self._metadata_cache_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> TONCenterV3Provider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _get_items(
        self, *, limit: int = 2, offset: int = 0, **params: str | int
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= MAX_PROVIDER_PAGE_SIZE or offset < 0:
            raise ValueError("Invalid TON Center NFT pagination values")
        request_params = {**params, "limit": limit, "offset": offset}
        request_headers = (
            {"X-API-Key": self.config.api_key} if self.config.api_key else None
        )

        for attempt in range(MAX_PROVIDER_REQUEST_ATTEMPTS):
            content = bytearray()
            try:
                async with self._client.stream(
                    "GET",
                    "nft/items",
                    params=request_params,
                    headers=request_headers,
                ) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        retryable_status = (
                            exc.response.status_code == 429
                            or exc.response.status_code >= 500
                        )
                        if retryable_status and attempt + 1 < MAX_PROVIDER_REQUEST_ATTEMPTS:
                            await asyncio.sleep(
                                _PROVIDER_RETRY_BACKOFF_SECONDS * (2**attempt)
                            )
                            continue
                        if retryable_status:
                            raise ProviderUnavailable(
                                "TON Center NFT indexer is temporarily unavailable"
                            ) from exc
                        raise InvalidProviderData(
                            "TON Center rejected the NFT inventory request"
                        ) from exc

                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_length = int(content_length)
                        except ValueError as exc:
                            raise InvalidProviderData(
                                "TON Center returned invalid Content-Length"
                            ) from exc
                        if (
                            declared_length < 0
                            or declared_length > MAX_PROVIDER_RESPONSE_BYTES
                        ):
                            raise InvalidProviderData(
                                "TON Center response exceeds the allowed size"
                            )
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
                            raise InvalidProviderData(
                                "TON Center response exceeds the allowed size"
                            )
                        content.extend(chunk)
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ) as exc:
                if attempt + 1 < MAX_PROVIDER_REQUEST_ATTEMPTS:
                    await asyncio.sleep(
                        _PROVIDER_RETRY_BACKOFF_SECONDS * (2**attempt)
                    )
                    continue
                raise ProviderUnavailable(
                    "TON Center NFT indexer is temporarily unavailable"
                ) from exc
            except httpx.RequestError as exc:
                raise ProviderUnavailable(
                    "TON Center NFT indexer request failed"
                ) from exc

            try:
                payload: object = json.loads(content)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise InvalidProviderData("TON Center returned non-JSON data") from exc

            if not isinstance(payload, dict):
                raise InvalidProviderData("TON Center response has no nft_items array")
            raw_rows = payload.get("nft_items")
            if not isinstance(raw_rows, list):
                raise InvalidProviderData("TON Center response has no nft_items array")
            if len(raw_rows) > limit or any(not isinstance(row, dict) for row in raw_rows):
                raise InvalidProviderData(
                    "TON Center returned too many or malformed NFT items"
                )
            return [cast(dict[str, Any], row) for row in raw_rows]

        raise ProviderUnavailable("TON Center NFT indexer is temporarily unavailable")


    async def _run_get_method(
        self,
        address: str,
        method: str,
        *,
        stack: list[dict[str, str]] | None = None,
    ) -> list[object]:
        """Execute a contract get-method through TON Center, not its NFT index tables."""
        normalized = normalize_address(address)
        request_headers = (
            {"X-API-Key": self.config.api_key} if self.config.api_key else None
        )
        request_body = {
            "address": normalized,
            "method": method,
            "stack": stack or [],
        }

        for attempt in range(MAX_PROVIDER_REQUEST_ATTEMPTS):
            content = bytearray()
            try:
                async with self._client.stream(
                    "POST",
                    "runGetMethod",
                    json=request_body,
                    headers=request_headers,
                ) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        retryable_status = (
                            exc.response.status_code == 429
                            or exc.response.status_code >= 500
                        )
                        if retryable_status and attempt + 1 < MAX_PROVIDER_REQUEST_ATTEMPTS:
                            await asyncio.sleep(
                                _PROVIDER_RETRY_BACKOFF_SECONDS * (2**attempt)
                            )
                            continue
                        if retryable_status:
                            raise ProviderUnavailable(
                                "TON Center contract state is temporarily unavailable"
                            ) from exc
                        raise InvalidProviderData(
                            "TON Center rejected the NFT contract get-method request"
                        ) from exc

                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_length = int(content_length)
                        except ValueError as exc:
                            raise InvalidProviderData(
                                "TON Center returned invalid get-method Content-Length"
                            ) from exc
                        if declared_length < 0 or declared_length > MAX_PROVIDER_RESPONSE_BYTES:
                            raise InvalidProviderData(
                                "TON Center get-method response exceeds the allowed size"
                            )
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
                            raise InvalidProviderData(
                                "TON Center get-method response exceeds the allowed size"
                            )
                        content.extend(chunk)
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ) as exc:
                if attempt + 1 < MAX_PROVIDER_REQUEST_ATTEMPTS:
                    await asyncio.sleep(
                        _PROVIDER_RETRY_BACKOFF_SECONDS * (2**attempt)
                    )
                    continue
                raise ProviderUnavailable(
                    "TON Center contract state is temporarily unavailable"
                ) from exc
            except httpx.RequestError as exc:
                raise ProviderUnavailable(
                    "TON Center contract state request failed"
                ) from exc

            try:
                payload: object = json.loads(content)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise InvalidProviderData(
                    "TON Center returned non-JSON get-method data"
                ) from exc
            if not isinstance(payload, dict):
                raise InvalidProviderData(
                    "TON Center returned malformed get-method data"
                )
            if payload.get("ok") is False:
                raise InvalidProviderData(
                    "TON Center could not execute the NFT contract get-method"
                )
            result = payload.get("result", payload)
            if not isinstance(result, dict):
                raise InvalidProviderData(
                    "TON Center returned a malformed get-method result"
                )
            exit_code = result.get("exit_code")
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                raise InvalidProviderData(
                    "TON Center get-method result has no valid exit code"
                )
            if exit_code != 0:
                raise UnsupportedAsset(
                    "NFT contract does not successfully implement the required TEP-62 get-method"
                )
            result_stack = result.get("stack")
            if not isinstance(result_stack, list):
                raise InvalidProviderData(
                    "TON Center get-method result has no stack"
                )
            return result_stack

        raise ProviderUnavailable("TON Center contract state is temporarily unavailable")

    async def _get_nft_data(self, address: str) -> NFTItemSnapshot:
        stack = await self._run_get_method(address, "get_nft_data")
        if len(stack) < 5:
            raise InvalidProviderData(
                "TEP-62 get_nft_data returned fewer than five stack values"
            )
        initialized = _stack_integer(stack[0]) != 0
        index = _stack_integer(stack[1])
        collection = _stack_address(stack[2])
        owner = _stack_address(stack[3])
        if index < 0 or owner is None:
            raise InvalidProviderData(
                "TEP-62 get_nft_data returned an invalid index or empty owner address"
            )
        return NFTItemSnapshot(
            address=normalize_address(address),
            initialized=initialized,
            index=index,
            collection_address=collection,
            owner_address=owner,
            metadata=NFTMetadata(),
        )

    async def _indexed_metadata(
        self,
        address: str,
        *,
        fetch_remote: bool,
    ) -> NFTMetadata:
        """Use the indexer only for optional display metadata, never for ownership."""
        try:
            rows = await self._get_items(address=address, limit=2)
        except (ProviderUnavailable, InvalidProviderData):
            return NFTMetadata()
        for raw in rows:
            raw_address = raw.get("address")
            try:
                if normalize_address(raw_address) != address:
                    continue
            except (AddressError, TypeError):
                continue
            return await self._metadata_for_raw(
                raw,
                address,
                fetch_remote=fetch_remote,
            )
        return NFTMetadata()

    @staticmethod
    def _metadata(raw: dict[str, Any]) -> NFTMetadata:
        return _metadata_fields(_onchain_metadata(raw))

    async def _get_cached_offchain(
        self, key: str
    ) -> tuple[bool, dict[str, object] | None]:
        async with self._metadata_cache_lock:
            entry = self._metadata_cache.get(key)
            if entry is None:
                return False, None
            expires_at, document = entry
            if expires_at <= time.monotonic():
                self._metadata_cache.pop(key, None)
                return False, None
            return True, document

    async def _cache_offchain(
        self, key: str, document: dict[str, object] | None
    ) -> None:
        ttl = (
            _METADATA_CACHE_TTL_SECONDS
            if document is not None
            else _METADATA_NEGATIVE_CACHE_TTL_SECONDS
        )
        async with self._metadata_cache_lock:
            if key not in self._metadata_cache and len(self._metadata_cache) >= (
                _MAX_METADATA_CACHE_ENTRIES
            ):
                oldest_key = next(iter(self._metadata_cache))
                self._metadata_cache.pop(oldest_key, None)
            self._metadata_cache[key] = (time.monotonic() + ttl, document)

    async def _metadata_for_raw(
        self,
        raw: dict[str, Any],
        item_address: str,
        *,
        fetch_remote: bool,
    ) -> NFTMetadata:
        onchain = _onchain_metadata(raw)
        inline = _metadata_fields(
            onchain,
            ipfs_gateway_url=self.config.ipfs_gateway_url,
        )
        normalized_uri = _normalize_uri(
            _metadata_uri(raw),
            ipfs_gateway_url=self.config.ipfs_gateway_url,
        )
        if normalized_uri is None:
            return inline

        cache_key = f"{item_address}:{normalized_uri}"
        found, document = await self._get_cached_offchain(cache_key)
        if not found and fetch_remote:
            async with self._metadata_semaphore:
                found, document = await self._get_cached_offchain(cache_key)
                if not found:
                    document = await _fetch_metadata_json(
                        normalized_uri,
                        ipfs_gateway_url=self.config.ipfs_gateway_url,
                    )
                    await self._cache_offchain(cache_key, document)

        if not isinstance(document, dict):
            return inline

        # TEP-64 semi-chain metadata: on-chain fields take precedence on collisions.
        merged: dict[str, Any] = dict(document)
        merged.update(onchain)
        if "image_url" in onchain and "image" not in onchain:
            merged["image"] = onchain["image_url"]
        return _metadata_fields(
            merged,
            ipfs_gateway_url=self.config.ipfs_gateway_url,
        )

    async def _parse_item_with_metadata(
        self,
        raw: dict[str, Any],
        *,
        fetch_remote: bool = True,
    ) -> NFTItemSnapshot:
        snapshot = self._parse_item(raw)
        metadata = await self._metadata_for_raw(
            raw,
            snapshot.address,
            fetch_remote=fetch_remote,
        )
        return replace(snapshot, metadata=metadata)

    @classmethod
    def _parse_item(cls, raw: dict[str, Any]) -> NFTItemSnapshot:
        try:
            address = normalize_address(raw["address"])
            owner = normalize_address(raw["owner_address"])
            collection_raw = raw.get("collection_address")
            if not collection_raw and isinstance(raw.get("collection"), dict):
                collection_raw = raw["collection"].get("address")
            collection = normalize_address(collection_raw) if collection_raw else None
            index = int(raw["index"])
            initialized = raw["init"]
            if not isinstance(initialized, bool) or index < 0:
                raise ValueError("Invalid initialization flag or index")
        except (KeyError, TypeError, ValueError, AddressError) as exc:
            raise InvalidProviderData(
                "TON Center returned incomplete or invalid NFT data"
            ) from exc

        return NFTItemSnapshot(
            address=address,
            initialized=initialized,
            index=index,
            collection_address=collection,
            owner_address=owner,
            metadata=cls._metadata(raw),
        )

    async def get_item(self, address: str) -> NFTItemSnapshot | None:
        """Read TEP-62 ownership and collection fields from the contract get-method."""
        normalized = normalize_address(address)
        return await self._get_nft_data(normalized)

    async def get_item_with_metadata(self, address: str) -> NFTItemSnapshot | None:
        """Read ownership from contract state and enrich display metadata separately."""
        normalized = normalize_address(address)
        snapshot = await self._get_nft_data(normalized)
        metadata = await self._indexed_metadata(normalized, fetch_remote=True)
        return replace(snapshot, metadata=metadata)

    async def get_items_by_owner(
        self, owner_address: str, *, limit: int, offset: int
    ) -> NFTInventoryPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError(
                "Inventory page limit must be between 1 and 100 and offset non-negative"
            )
        owner = normalize_address(owner_address)
        rows = await self._get_items(
            owner_address=owner,
            limit=limit + 1,
            offset=offset,
        )
        has_more = len(rows) > limit
        consumed_rows = rows[:limit]
        # Metadata enrichment is page-scoped, bounded-concurrency and cached by the
        # exact item address + URI. Subsequent ownership verification reuses the cache.
        metadata_tasks = [
            asyncio.create_task(self._parse_item_with_metadata(row))
            for row in consumed_rows
        ]
        completed, pending = await asyncio.wait(
            metadata_tasks,
            timeout=_METADATA_PAGE_ENRICHMENT_TIMEOUT_SECONDS,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        # If an external metadata host is slow, return the on-chain snapshot rather
        # than extending the inventory request. Metadata is optional display data.
        snapshots = tuple(
            task.result() if task in completed else self._parse_item(row)
            for row, task in zip(consumed_rows, metadata_tasks, strict=True)
        )
        return NFTInventoryPage(
            items=snapshots,
            has_more=has_more,
            next_offset=offset + len(consumed_rows),
        )

    async def get_item_address_by_index(
        self, collection_address: str, index: int
    ) -> str | None:
        collection = normalize_address(collection_address)
        if index < 0:
            raise ValueError("NFT item index cannot be negative")
        stack = await self._run_get_method(
            collection,
            "get_nft_address_by_index",
            stack=[{"type": "num", "value": str(index)}],
        )
        if not stack:
            raise InvalidProviderData(
                "TEP-62 collection get_nft_address_by_index returned an empty stack"
            )
        return _stack_address(stack[0])
