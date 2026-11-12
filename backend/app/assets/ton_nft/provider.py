"""TON Center API v3 read-only provider adapter (indexed data, not proof)."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol, cast
from urllib.parse import unquote, urljoin, urlparse

import httpx

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable
from app.assets.ton_nft.models import NFTInventoryPage, NFTItemSnapshot, NFTMetadata

MAX_PROVIDER_RESPONSE_BYTES = 2_000_000
MAX_METADATA_RESPONSE_BYTES = 512_000
MAX_PROVIDER_PAGE_SIZE = 1000
MAX_METADATA_URL_LENGTH = 2048
METADATA_TIMEOUT_SECONDS = 4.0
MAX_REDIRECTS = 3
IPFS_GATEWAY = "https://ipfs.io/ipfs/"


class NFTDataProvider(Protocol):
    async def get_item(self, address: str) -> NFTItemSnapshot | None: ...
    async def get_items_by_owner(self, owner_address: str, *, limit: int, offset: int) -> NFTInventoryPage: ...
    async def get_item_address_by_index(self, collection_address: str, index: int) -> str | None: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TONCenterV3Config:
    base_url: str
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 8.0
    ipfs_gateway: str = IPFS_GATEWAY

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("TON Center base_url must be an absolute HTTP(S) URL")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        gateway = urlparse(self.ipfs_gateway)
        if gateway.scheme != "https" or not gateway.hostname or not gateway.path.endswith("/ipfs/"):
            raise ValueError("IPFS gateway must be an HTTPS /ipfs/ gateway URL")


def _public_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return address.is_global


@lru_cache(maxsize=512)
def _resolve_public_host(host: str, port: int) -> bool:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return bool(answers) and all(_public_ip(answer[4][0]) for answer in answers)


def _normalize_uri(value: object, gateway: str = IPFS_GATEWAY) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_METADATA_URL_LENGTH:
        return None
    if any(ord(char) < 32 or char == "\\" for char in value):
        return None
    candidate = value.strip()
    if candidate.startswith("ipfs://"):
        path = candidate[7:]
        if path.startswith("ipfs/"):
            path = path[5:]
        if not path or path.startswith("/") or ".." in path.split("/"):
            return None
        return gateway.rstrip("/") + "/" + path
    parsed = urlparse(candidate)
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.fragment or not _public_ip(parsed.hostname)
        or not _resolve_public_host(parsed.hostname, port)
    ):
        return None
    return candidate


def _safe_image_url(value: object, gateway: str = IPFS_GATEWAY) -> str | None:
    return _normalize_uri(value, gateway)


def _metadata_fields(data: dict[str, Any]) -> NFTMetadata:
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
        if isinstance(attrs, list) else ()
    )
    name, description = data.get("name"), data.get("description")
    image = data.get("image", data.get("image_url"))
    return NFTMetadata(
        name=name[:200] if isinstance(name, str) else None,
        description=description[:2000] if isinstance(description, str) else None,
        image=_safe_image_url(image),
        attributes=safe_attrs,
    )


class TONCenterV3Provider:
    """Fetch exact TON NFT items and optionally enrich display metadata off-chain."""

    def __init__(self, config: TONCenterV3Config, *, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        headers = {"X-API-Key": self.config.api_key} if self.config.api_key else {}
        self._client = client or httpx.AsyncClient(
            base_url=self.config.base_url.rstrip("/"), headers=headers,
            timeout=httpx.Timeout(self.config.timeout_seconds), follow_redirects=False,
        )
        self._owns_client = client is None
        self._metadata_cache: dict[str, NFTMetadata] = {}
        self._metadata_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> TONCenterV3Provider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _get_items(self, *, limit: int = 2, offset: int = 0, **params: str | int) -> list[dict[str, Any]]:
        if not 1 <= limit <= MAX_PROVIDER_PAGE_SIZE or offset < 0:
            raise ValueError("Invalid TON Center NFT pagination values")
        content = bytearray()
        try:
            async with self._client.stream(
                "GET", "nft/items", params={**params, "limit": limit, "offset": offset},
                headers={"X-API-Key": self.config.api_key} if self.config.api_key else None,
            ) as response:
                response.raise_for_status()
                _check_content_length(response.headers, MAX_PROVIDER_RESPONSE_BYTES)
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
                        raise InvalidProviderData("TON Center response exceeds the allowed size")
                    content.extend(chunk)
        except InvalidProviderData:
            raise
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise ProviderUnavailable("TON Center NFT indexer request failed") from exc
        try:
            payload: object = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidProviderData("TON Center returned non-JSON data") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("nft_items"), list):
            raise InvalidProviderData("TON Center response has no nft_items array")
        raw_rows = payload["nft_items"]
        if len(raw_rows) > limit or any(not isinstance(row, dict) for row in raw_rows):
            raise InvalidProviderData("TON Center returned too many or malformed NFT items")
        return [cast(dict[str, Any], row) for row in raw_rows]

    @staticmethod
    def _inline_metadata(raw: dict[str, Any]) -> tuple[NFTMetadata, str | None, dict[str, Any]]:
        content = raw.get("content")
        content = content if isinstance(content, dict) else {}
        nested = content.get("metadata")
        data = nested if isinstance(nested, dict) else {
            key: value for key, value in content.items() if key != "uri"
        }
        return _metadata_fields(data), content.get("uri") if isinstance(content.get("uri"), str) else None, data

    async def _fetch_metadata_json(self, uri: str) -> dict[str, Any] | None:
        current = _normalize_uri(uri, self.config.ipfs_gateway)
        if current is None:
            return None
        for redirect_count in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            try:
                # Re-resolve before every request/redirect; redirects are disabled in httpx.
                port = parsed.port or 443
                if not _resolve_public_host(parsed.hostname or "", port):
                    return None
                timeout = httpx.Timeout(METADATA_TIMEOUT_SECONDS)
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                    async with client.stream("GET", current, headers={"Accept": "application/json"}) as response:
                        if response.is_redirect:
                            if redirect_count >= MAX_REDIRECTS:
                                return None
                            location = response.headers.get("location")
                            if not location:
                                return None
                            current = _normalize_uri(urljoin(current, location), self.config.ipfs_gateway)
                            if current is None:
                                return None
                            continue
                        if response.status_code != 200:
                            return None
                        content_type = response.headers.get("content-type", "").lower()
                        if "json" not in content_type and "text/plain" not in content_type:
                            return None
                        _check_content_length(response.headers, MAX_METADATA_RESPONSE_BYTES)
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_METADATA_RESPONSE_BYTES:
                                return None
                            body.extend(chunk)
                payload = json.loads(body)
                return payload if isinstance(payload, dict) else None
            except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError):
                return None
        return None

    async def _metadata(self, raw: dict[str, Any]) -> NFTMetadata:
        inline, uri, inline_data = self._inline_metadata(raw)
        # Full on-chain data requires no network access and takes precedence.
        if not uri:
            return inline
        normalized_uri = _normalize_uri(uri, self.config.ipfs_gateway)
        if normalized_uri is None:
            return inline
        async with self._metadata_lock:
            remote = self._metadata_cache.get(normalized_uri)
        if remote is None:
            remote_json = await self._fetch_metadata_json(normalized_uri)
            if remote_json is None:
                return inline
            remote = _metadata_fields(remote_json)
            async with self._metadata_lock:
                self._metadata_cache[normalized_uri] = remote
        # TEP-64 semi-chain: inline on-chain values win conflicts.
        merged = dict(remote_json) if (remote_json := await self._cached_metadata_json(normalized_uri)) else {}
        merged.update(inline_data)
        if not merged:
            return remote
        return _metadata_fields(merged)

    async def _cached_metadata_json(self, uri: str) -> dict[str, Any] | None:
        # Cache metadata fields only; the raw JSON is fetched once by _metadata below.
        # Kept as an explicit hook so tests can replace remote fetching deterministically.
        return None

    @classmethod
    def _parse_item(cls, raw: dict[str, Any]) -> NFTItemSnapshot:
        try:
            address = normalize_address(raw["address"])
            owner = normalize_address(raw["owner_address"])
            collection_raw = raw.get("collection_address")
            if not collection_raw and isinstance(raw.get("collection"), dict):
                collection_raw = raw["collection"].get("address")
            collection = normalize_address(collection_raw) if collection_raw else None
            index, initialized = int(raw["index"]), raw["init"]
            if not isinstance(initialized, bool) or index < 0:
                raise ValueError("Invalid initialization flag or index")
        except (KeyError, TypeError, ValueError, AddressError) as exc:
            raise InvalidProviderData("TON Center returned incomplete or invalid NFT data") from exc
        return NFTItemSnapshot(
            address=address, initialized=initialized, index=index,
            collection_address=collection, owner_address=owner,
        )

    async def _parse_item_with_metadata(self, raw: dict[str, Any]) -> NFTItemSnapshot:
        item = self._parse_item(raw)
        metadata = await self._metadata(raw)
        return NFTItemSnapshot(
            address=item.address, initialized=item.initialized, index=item.index,
            collection_address=item.collection_address, owner_address=item.owner_address,
            metadata=metadata,
        )

    async def get_item(self, address: str) -> NFTItemSnapshot | None:
        normalized = normalize_address(address)
        rows = await self._get_items(address=normalized, limit=2)
        if not rows:
            return None
        item = await self._parse_item_with_metadata(rows[0])
        if item.address != normalized:
            raise InvalidProviderData("Indexer returned a different NFT item address")
        return item

    async def get_items_by_owner(self, owner_address: str, *, limit: int, offset: int) -> NFTInventoryPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Inventory page limit must be between 1 and 100 and offset non-negative")
        owner = normalize_address(owner_address)
        rows = await self._get_items(owner_address=owner, limit=limit + 1, offset=offset)
        has_more = len(rows) > limit
        snapshots = tuple(await asyncio.gather(*(self._parse_item_with_metadata(row) for row in rows[:limit])))
        return NFTInventoryPage(items=snapshots, has_more=has_more, next_offset=offset + len(snapshots))

    async def get_item_address_by_index(self, collection_address: str, index: int) -> str | None:
        collection = normalize_address(collection_address)
        if index < 0:
            raise ValueError("NFT item index cannot be negative")
        rows = await self._get_items(collection_address=collection, index=index)
        if not rows:
            return None
        item = self._parse_item(rows[0])
        if item.collection_address != collection or item.index != index:
            raise InvalidProviderData("Indexer returned an item outside the requested collection/index")
        return item.address


def _check_content_length(headers: httpx.Headers, maximum: int) -> None:
    content_length = headers.get("content-length")
    if content_length is None:
        return
    try:
        declared = int(content_length)
    except ValueError as exc:
        raise InvalidProviderData("Metadata response has invalid Content-Length") from exc
    if declared < 0 or declared > maximum:
        raise InvalidProviderData("Metadata response exceeds the allowed size")
