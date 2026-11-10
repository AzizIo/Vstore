from __future__ import annotations

import httpx
import pytest

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable
from app.assets.ton_nft.models import NFTItemSnapshot, NFTMetadata, VerificationStatus
from app.assets.ton_nft.provider import TONCenterV3Config, TONCenterV3Provider
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

    async def get_item_address_by_index(self, collection_address: str, index: int) -> str | None:
        self.calls.append(("index", collection_address, index))
        return self.resolved


def test_normalizes_raw_address() -> None:
    assert normalize_address(ITEM.upper().replace("0:", "0:")) == ITEM


def test_rejects_invalid_raw_address() -> None:
    with pytest.raises(AddressError):
        normalize_address("0:1234")


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
    result = await TONNFTVerifier(FakeProvider(item=snapshot(initialized=False))).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.INVALID_DATA


@pytest.mark.asyncio
async def test_collection_index_mismatch_is_invalid() -> None:
    result = await TONNFTVerifier(FakeProvider(item=snapshot(), resolved=OTHER)).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.INVALID_DATA


@pytest.mark.asyncio
async def test_owner_mismatch_is_not_verified() -> None:
    result = await TONNFTVerifier(FakeProvider(item=snapshot(owner_address=OTHER))).verify(ITEM, OWNER)
    assert result.status is VerificationStatus.OWNER_MISMATCH


@pytest.mark.asyncio
async def test_provider_timeout_is_not_owner_mismatch() -> None:
    result = await TONNFTVerifier(FakeProvider(error=ProviderUnavailable("timeout"))).verify(ITEM, OWNER)
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
    provider = TONCenterV3Provider(TONCenterV3Config(base_url="https://mock.test/api/v3"), client=client)
    parsed = await provider.get_item(ITEM)
    resolved = await provider.get_item_address_by_index(COLLECTION, 7)
    assert parsed is not None and parsed.metadata.name == "NFT"
    assert resolved == ITEM
    assert requests[1].url.params["collection_address"] == COLLECTION
    assert requests[1].url.params["index"] == "7"
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_timeout_maps_to_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.test/api/v3")
    provider = TONCenterV3Provider(client=client)
    with pytest.raises(ProviderUnavailable):
        await provider.get_item(ITEM)
    await client.aclose()


@pytest.mark.asyncio
async def test_malformed_provider_item_maps_to_invalid_data() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"nft_items": [{"address": ITEM}]})),
        base_url="https://mock.test/api/v3",
    )
    provider = TONCenterV3Provider(client=client)
    with pytest.raises(InvalidProviderData):
        await provider.get_item(ITEM)
    await client.aclose()
