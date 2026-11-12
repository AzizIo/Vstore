"""TON Center API v3 read-only provider adapter (indexed data, not proof)."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable
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
_MAX_METADATA_CACHE_ENTRIES = 2048
_METADATA_CACHE_TTL_SECONDS = 600.0
_METADATA_NEGATIVE_CACHE_TTL_SECONDS = 30.0
_METADATA_FETCH_CONCURRENCY = 5
_METADATA_PAGE_ENRICHMENT_TIMEOUT_SECONDS = 8.0


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
        content = bytearray()
        try:
            async with self._client.stream(
                "GET",
                "nft/items",
                params=request_params,
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
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise ProviderUnavailable("TON Center NFT indexer request failed") from exc

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
        """Fetch the exact item for ownership checks; use cache but never wait on metadata."""
        normalized = normalize_address(address)
        rows = await self._get_items(address=normalized, limit=2)
        if not rows:
            return None
        item = await self._parse_item_with_metadata(rows[0], fetch_remote=False)
        if item.address != normalized:
            raise InvalidProviderData("Indexer returned a different NFT item address")
        return item

    async def get_item_with_metadata(self, address: str) -> NFTItemSnapshot | None:
        """Resolve metadata for an exact NFT address without changing ownership semantics."""
        normalized = normalize_address(address)
        rows = await self._get_items(address=normalized, limit=2)
        if not rows:
            return None
        item = await self._parse_item_with_metadata(rows[0], fetch_remote=True)
        if item.address != normalized:
            raise InvalidProviderData("Indexer returned a different NFT item address")
        return item

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
        rows = await self._get_items(collection_address=collection, index=index)
        if not rows:
            return None
        item = self._parse_item(rows[0])
        if item.collection_address != collection or item.index != index:
            raise InvalidProviderData(
                "Indexer returned an item outside the requested collection/index"
            )
        return item.address
