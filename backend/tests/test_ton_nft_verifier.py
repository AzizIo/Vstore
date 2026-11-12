from __future__ import annotations

import httpx
import pytest

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable, UnsupportedAsset
from app.assets.ton_nft.models import (
    NFTInventoryPage,
    NFTItemSnapshot,
    NFTMetadata,
    VerificationStatus,
)
from app.assets.ton_nft.provider import (
    MAX_PROVIDER_RESPONSE_BYTES,
    TONCenterV3Config,
    TONCenterV3Provider,
)
from app.assets.ton_nft.verifier import TONNFTVerifier

ITEM = "0:" + "11" * 32
COLLECTION = "0:" + "22" * 32
OWNER = "0:" + "33" * 32
OTHER = "0:" + "44" * 32


def snapshot(**changes: object) -> NFTItemSnapshot:
    data: dict[str, object] = {
        "address": ITEM, "initialized": True, "index": 7,
        "collection_address": COLLECTION, "owner_address": OWNER,
        "metadata": NFTMetadata(name="Display only"),
    }
    data.update(changes)
    return NFTItemSnapshot(**data)  # type: ignore[arg-type]


class FakeProvider:
    def __init__(self, item: NFTItemSnapshot | None = None, resolved: str | None = ITEM,
                 error: Exception | None = None) -> None:
        self.item, self.resolved, self.error = item, resolved, error
        self.calls: list[tuple[object, ...]] = []

    async def get_item(self, address: str) -> NFTItemSnapshot | None:
        self.calls.append(("item", address))
        if self.error:
            raise self.error
        return self.item

    async def get_items_by_owner(
        self, owner_address: str, *, limit: int, offset: int
    ) -> NFTInventoryPage:
        return NFTInventoryPage(items=(), has_more=False, next_offset=offset)

    async def get_item_address_by_index(self, collection_address: str, index: int) -> str | None:
        self.calls.append(("index", collection_address, index))
        return self.resolved


def test_normalizes_raw_address() -> None:
    raw_upper = "0:" + ("11" * 32).upper()
    assert normalize_address(raw_upper) == ITEM


def test_normalizes_checksum_valid_friendly_address() -> None:
    friendly = (
        "EQD3LzasMd4GAmhIEkCQ4k6LnziTqNZ6VPtRfeZKHu0Fmkho"
    )
    expected = "0:f72f36ac31de06026848124090e24e8b9f3893a8d67a54fb517de64a1eed059a"
    assert normalize_address(friendly) == expected


def test_rejects_invalid_raw_address_and_friendly_checksum() -> None:
    with pytest.raises(AddressError):
        normalize_address("0:1234")
    with pytest.raises(AddressError):
        normalize_address("EQD3LzasMd4GAmhIEkCQ4k6LnziTqNZ6VPtRfeZKHu0Fmkha")


@pytest.mark.asyncio
async def test_verifies_initialized_item_collection_and_owner() -> None:
    provider = FakeProvider(item=snapshot())
    result = await TONNFTVerifier(provider).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.VERIFIED
    assert result.is_verified
    assert ("index", COLLECTION, 7) in provider.calls


@pytest.mark.asyncio
async def test_item_not_found() -> None:
    result = await TONNFTVerifier(FakeProvider(item=None)).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_uninitialized_item_is_invalid() -> None:
    provider = FakeProvider(item=snapshot(initialized=False))
    result = await TONNFTVerifier(provider).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.INVALID_DATA


@pytest.mark.asyncio
async def test_collection_index_mismatch_is_invalid() -> None:
    result = await TONNFTVerifier(FakeProvider(item=snapshot(), resolved=OTHER)).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.INVALID_DATA


@pytest.mark.asyncio
async def test_owner_mismatch_is_not_verified() -> None:
    provider = FakeProvider(item=snapshot(owner_address=OTHER))
    result = await TONNFTVerifier(provider).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.OWNER_MISMATCH


@pytest.mark.asyncio
async def test_provider_timeout_is_not_owner_mismatch() -> None:
    provider = FakeProvider(error=ProviderUnavailable("timeout"))
    result = await TONNFTVerifier(provider).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_invalid_input_is_structured() -> None:
    result = await TONNFTVerifier(FakeProvider()).verify("bad-address", OWNER)
    assert result.status is VerificationStatus.INVALID_DATA


@pytest.mark.asyncio
async def test_collectionless_item_skips_index_lookup() -> None:
    provider = FakeProvider(item=snapshot(collection_address=None))
    result = await TONNFTVerifier(provider).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.VERIFIED
    assert not any(call[0] == "index" for call in provider.calls)


@pytest.mark.asyncio
async def test_toncenter_provider_parses_item_and_queries_collection_index() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        row = {
            "address": ITEM, "owner_address": OWNER, "collection_address": COLLECTION,
            "index": "7", "init": True, "content": {"metadata": {"name": "NFT"}},
        }
        return httpx.Response(200, json={"nft_items": [row]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.test/api/v3")
    config = TONCenterV3Config(base_url="https://mock.test/api/v3")
    provider = TONCenterV3Provider(config, client=client)
    parsed = await provider.get_item(ITEM)
    resolved = await provider.get_item_address_by_index(COLLECTION, 7)
    assert parsed is not None and parsed.metadata.name == "NFT"
    assert resolved == ITEM
    assert requests[0].url.path == "/api/v3/nft/items"
    assert requests[1].url.params["collection_address"] == COLLECTION
    assert requests[1].url.params["index"] == "7"
    await client.aclose()


@pytest.mark.asyncio
async def test_toncenter_owner_inventory_uses_bounded_offset_pagination() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        rows = [
            {
                "address": f"0:{index:064x}",
                "owner_address": OWNER,
                "collection_address": None,
                "index": str(index),
                "init": True,
            }
            for index in range(3)
        ]
        return httpx.Response(200, json={"nft_items": rows})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://mock.test/api/v3"
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.test/api/v3"), client=client
    )

    page = await provider.get_items_by_owner(OWNER, limit=2, offset=4)

    assert len(page.items) == 2
    assert page.has_more is True
    assert page.next_offset == 6
    assert requests[0].url.params["owner_address"] == OWNER
    assert requests[0].url.params["limit"] == "3"
    assert requests[0].url.params["offset"] == "4"
    await client.aclose()


@pytest.mark.asyncio
async def test_toncenter_owner_inventory_reports_last_page_without_fabricated_total() -> (
    None
):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "nft_items": [
                        {
                            "address": ITEM,
                            "owner_address": OWNER,
                            "collection_address": None,
                            "index": "0",
                            "init": True,
                        }
                    ]
                },
            )
        ),
        base_url="https://mock.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.test/api/v3"), client=client
    )

    page = await provider.get_items_by_owner(OWNER, limit=2, offset=0)

    assert len(page.items) == 1
    assert page.has_more is False
    assert page.next_offset == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_timeout_maps_to_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.test/api/v3")
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.test/api/v3"), client=client
    )
    with pytest.raises(ProviderUnavailable):
        await provider.get_item(ITEM)
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_retries_a_transient_dns_connect_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError(
                "Name or service not known",
                request=request,
            )
        return httpx.Response(200, json={"nft_items": []})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mock.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.test/api/v3"),
        client=client,
    )

    assert await provider.get_item(ITEM) is None
    assert attempts == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_retries_a_transient_http_503_response() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"detail": "temporarily unavailable"})
        return httpx.Response(200, json={"nft_items": []})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mock.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.test/api/v3"),
        client=client,
    )

    assert await provider.get_item(ITEM) is None
    assert attempts == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_bounds_persistent_dns_connect_failures() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError(
            "Name or service not known",
            request=request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mock.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.test/api/v3"),
        client=client,
    )

    with pytest.raises(ProviderUnavailable, match="temporarily unavailable"):
        await provider.get_item(ITEM)
    assert attempts == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_does_not_retry_non_retryable_auth_configuration_errors() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"detail": "invalid api key"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mock.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.test/api/v3"),
        client=client,
    )

    with pytest.raises(InvalidProviderData, match="rejected"):
        await provider.get_item(ITEM)
    assert attempts == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_malformed_provider_item_maps_to_invalid_data() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"nft_items": [{"address": ITEM}]})
        ),
        base_url="https://mock.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.test/api/v3"), client=client
    )
    with pytest.raises(InvalidProviderData):
        await provider.get_item(ITEM)
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_rejects_oversized_inventory_response_before_parsing() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=b" " * (MAX_PROVIDER_RESPONSE_BYTES + 1)
            )
        ),
        base_url="https://mock.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.test/api/v3"), client=client
    )
    with pytest.raises(InvalidProviderData, match="exceeds the allowed size"):
        await provider.get_items_by_owner(OWNER, limit=2, offset=0)
    await client.aclose()


@pytest.mark.asyncio
async def test_unsupported_asset_has_distinct_status() -> None:
    provider = FakeProvider(error=UnsupportedAsset("unsupported"))
    result = await TONNFTVerifier(provider).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.UNSUPPORTED


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("https://cdn.example.test/nft.png", "https://cdn.example.test/nft.png"),
        ("http://cdn.example.test/nft.png", None),
        ("javascript:alert(1)", None),
        ("data:image/png;base64,AA==", None),
        ("https://user:pass@cdn.example.test/nft.png", None),
        ("https://cdn.example.test/" + "x" * 2050, None),
    ],
)
def test_provider_rejects_unsafe_or_oversized_image_urls(image: str, expected: str | None) -> None:
    metadata = TONCenterV3Provider._metadata({"content": {"metadata": {"image": image}}})
    assert metadata.image == expected
