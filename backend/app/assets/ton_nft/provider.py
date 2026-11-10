"""TON Center API v3 read-only provider adapter (indexed data, not proof)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable
from app.assets.ton_nft.models import NFTItemSnapshot, NFTMetadata


class NFTDataProvider(Protocol):
    async def get_item(self, address: str) -> NFTItemSnapshot | None: ...

    async def get_item_address_by_index(
        self, collection_address: str, index: int
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class TONCenterV3Config:
    base_url: str
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("TON Center base_url must be an absolute HTTP(S) URL")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class TONCenterV3Provider:
    """Fetch NFT item snapshots from the documented TON Center v3 indexer."""

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

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> TONCenterV3Provider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _get_items(self, **params: str | int) -> list[dict[str, Any]]:
        try:
            response = await self._client.get(
                "nft/items",
                params={**params, "limit": 2},
                headers={"X-API-Key": self.config.api_key} if self.config.api_key else None,
            )
            response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise ProviderUnavailable("TON Center NFT indexer request failed") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise InvalidProviderData("TON Center returned non-JSON data") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("nft_items"), list):
            raise InvalidProviderData("TON Center response has no nft_items array")

        rows = payload["nft_items"]
        if len(rows) > 1 or any(not isinstance(row, dict) for row in rows):
            raise InvalidProviderData("TON Center returned ambiguous or malformed NFT items")
        return rows

    @staticmethod
    def _metadata(raw: dict[str, Any]) -> NFTMetadata:
        content = raw.get("content")
        content = content if isinstance(content, dict) else {}
        data = content.get("metadata")
        data = data if isinstance(data, dict) else content
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
        return NFTMetadata(
            name=name[:200] if isinstance(name, str) else None,
            description=description[:2000] if isinstance(description, str) else None,
            image=image[:2048] if isinstance(image, str) else None,
            attributes=safe_attrs,
        )

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
        normalized = normalize_address(address)
        rows = await self._get_items(address=normalized)
        if not rows:
            return None
        item = self._parse_item(rows[0])
        if item.address != normalized:
            raise InvalidProviderData("Indexer returned a different NFT item address")
        return item

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
