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

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://mock.test/api/v3"
    )
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
        ("http://cdn.example.test/nft.png", "http://cdn.example.test/nft.png"),
        ("javascript:alert(1)", None),
        ("data:image/png;base64,AA==", None),
        ("https://user:pass@cdn.example.test/nft.png", None),
        ("https://cdn.example.test/" + "x" * 2050, None),
    ],
)
def test_provider_rejects_unsafe_or_oversized_image_urls(image: str, expected: str | None) -> None:
    metadata = TONCenterV3Provider._metadata({"content": {"metadata": {"image": image}}})
    assert metadata.image == expected


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (
            "ipfs://bafybeigdyrzt5sfp7udm7hu76uh2yltop2wyklgdnzbz3u7zvy3gq/item.json",
            "https://ipfs.io/ipfs/bafybeigdyrzt5sfp7udm7hu76uh2yltop2wyklgdnzbz3u7zvy3gq/item.json",
        ),
        ("https://metadata.example/item.json", "https://metadata.example/item.json"),
        ("http://metadata.example/item.json", "http://metadata.example/item.json"),
        ("ipfs://bafybeigdyrzt5sfp7udm7hu76uh2yltop2wyklgdnzbz3u7zvy3gq/%2e%2e/secret", None),
        ("https://127.0.0.1/private.json", None),
        ("https://[::1]/private.json", None),
        ("http://localhost/private.json", None),
        ("file:///etc/passwd", None),
        ("https://user:pass@metadata.example/item.json", None),
        ("https://metadata.example:8443/item.json", None),
    ],
)
def test_normalizes_supported_metadata_uris(uri: str, expected: str | None) -> None:
    from app.assets.ton_nft.metadata import normalize_metadata_uri

    assert normalize_metadata_uri(uri) == expected


def test_ipfs_gateway_is_configurable_and_validated() -> None:
    from app.assets.ton_nft.metadata import normalize_metadata_uri

    uri = "ipfs://bafybeigdyrzt5sfp7udm7hu76uh2yltop2wyklgdnzbz3u7zvy3gq/item.json"
    assert normalize_metadata_uri(
        uri, ipfs_gateway_url="https://gateway.example/ipfs"
    ) == (
        "https://gateway.example/ipfs/"
        "bafybeigdyrzt5sfp7udm7hu76uh2yltop2wyklgdnzbz3u7zvy3gq/item.json"
    )
    with pytest.raises(ValueError):
        TONCenterV3Config(
            base_url="https://ton.example",
            ipfs_gateway_url="http://127.0.0.1/ipfs",
        )


def test_dns_results_must_all_be_public() -> None:
    from app.assets.ton_nft.metadata import _select_public_ip

    assert _select_public_ip(["93.184.216.34"]) == "93.184.216.34"
    assert _select_public_ip(["93.184.216.34", "127.0.0.1"]) is None
    assert _select_public_ip(["10.0.0.1"]) is None
    assert _select_public_ip(["169.254.169.254"]) is None
    assert _select_public_ip(["::1"]) is None
    assert _select_public_ip([]) is None


class _FakeMetadataWriter:
    def __init__(self) -> None:
        self.request = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.request.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _metadata_http_response(
    body: bytes,
    *,
    status: int = 200,
    headers: str = "Content-Type: application/json\r\n",
) -> bytes:
    return (
        f"HTTP/1.1 {status} Test\r\n"
        f"{headers}"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body


@pytest.mark.asyncio
async def test_metadata_request_pins_public_ip_and_keeps_tls_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.assets.ton_nft import metadata as metadata_module

    calls: list[dict[str, object]] = []
    writers: list[_FakeMetadataWriter] = []
    response = _metadata_http_response(b'{"name":"Pinned"}')

    async def resolve(host: str, port: int) -> str:
        assert host == "metadata.example"
        assert port == 443
        return "93.184.216.34"

    async def open_connection(**kwargs: object) -> tuple[asyncio.StreamReader, _FakeMetadataWriter]:
        calls.append(kwargs)
        reader = asyncio.StreamReader()
        reader.feed_data(response)
        reader.feed_eof()
        writer = _FakeMetadataWriter()
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(metadata_module, "_resolve_public_ip", resolve)
    monkeypatch.setattr(metadata_module.asyncio, "open_connection", open_connection)

    result = await metadata_module.fetch_metadata_json("https://metadata.example/item.json")

    assert result == {"name": "Pinned"}
    assert len(calls) == 1
    assert calls[0]["host"] == "93.184.216.34"
    assert calls[0]["server_hostname"] == "metadata.example"
    assert b"X-API-Key" not in writers[0].request
    assert b"Connection: close" in writers[0].request
    assert writers[0].closed


@pytest.mark.asyncio
async def test_redirect_destination_is_resolved_and_pinned_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.assets.ton_nft import metadata as metadata_module

    resolved: list[str] = []
    connected: list[str] = []
    responses = [
        _metadata_http_response(
            b"", status=302, headers="Location: https://cdn.example/item.json\r\n"
        ),
        _metadata_http_response(b'{"name":"Redirected"}'),
    ]

    async def resolve(host: str, _port: int) -> str:
        resolved.append(host)
        return "93.184.216.34" if host == "metadata.example" else "93.184.216.35"

    async def open_connection(**kwargs: object) -> tuple[asyncio.StreamReader, _FakeMetadataWriter]:
        connected.append(str(kwargs["host"]))
        reader = asyncio.StreamReader()
        reader.feed_data(responses.pop(0))
        reader.feed_eof()
        return reader, _FakeMetadataWriter()

    monkeypatch.setattr(metadata_module, "_resolve_public_ip", resolve)
    monkeypatch.setattr(metadata_module.asyncio, "open_connection", open_connection)

    result = await metadata_module.fetch_metadata_json("https://metadata.example/item.json")

    assert result == {"name": "Redirected"}
    assert resolved == ["metadata.example", "cdn.example"]
    assert connected == ["93.184.216.34", "93.184.216.35"]


@pytest.mark.asyncio
async def test_redirect_to_private_dns_destination_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.assets.ton_nft import metadata as metadata_module

    connected: list[str] = []

    async def resolve(host: str, _port: int) -> str:
        if host == "metadata.example":
            return "93.184.216.34"
        raise metadata_module.UnsafeMetadataURI("private destination")

    async def open_connection(**kwargs: object) -> tuple[asyncio.StreamReader, _FakeMetadataWriter]:
        connected.append(str(kwargs["host"]))
        reader = asyncio.StreamReader()
        reader.feed_data(
            _metadata_http_response(
                b"", status=302, headers="Location: https://internal.example/admin\r\n"
            )
        )
        reader.feed_eof()
        return reader, _FakeMetadataWriter()

    monkeypatch.setattr(metadata_module, "_resolve_public_ip", resolve)
    monkeypatch.setattr(metadata_module.asyncio, "open_connection", open_connection)

    result = await metadata_module.fetch_metadata_json("https://metadata.example/item.json")

    assert result is None
    assert connected == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_metadata_fetch_rejects_oversize_and_non_json_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.assets.ton_nft import metadata as metadata_module

    responses = [
        (
            "HTTP/1.1 200 Test\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {metadata_module.MAX_METADATA_RESPONSE_BYTES + 1}\r\n\r\n"
        ).encode("ascii"),
        _metadata_http_response(b"<html>not json</html>", headers="Content-Type: text/html\r\n"),
        _metadata_http_response(b"{broken"),
    ]

    async def resolve(_host: str, _port: int) -> str:
        return "93.184.216.34"

    async def open_connection(**kwargs: object) -> tuple[asyncio.StreamReader, _FakeMetadataWriter]:
        reader = asyncio.StreamReader()
        reader.feed_data(responses.pop(0))
        reader.feed_eof()
        return reader, _FakeMetadataWriter()

    monkeypatch.setattr(metadata_module, "_resolve_public_ip", resolve)
    monkeypatch.setattr(metadata_module.asyncio, "open_connection", open_connection)

    for _ in range(3):
        assert (
            await metadata_module.fetch_metadata_json("https://metadata.example/item.json")
            is None
        )


@pytest.mark.asyncio
async def test_metadata_fetch_timeout_is_nonfatal(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.assets.ton_nft import metadata as metadata_module

    async def slow_resolve(_host: str, _port: int) -> str:
        import asyncio

        await asyncio.sleep(0.05)
        return "93.184.216.34"

    monkeypatch.setattr(metadata_module, "_resolve_public_ip", slow_resolve)

    assert await metadata_module.fetch_metadata_json(
        "https://metadata.example/item.json", timeout_seconds=0.001
    ) is None


@pytest.mark.asyncio
async def test_owner_inventory_enriches_metadata_and_verification_reuses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.assets.ton_nft import provider as provider_module

    row = {
        "address": ITEM,
        "owner_address": OWNER,
        "collection_address": None,
        "index": "7",
        "init": True,
        "content": {
            "uri": "https://metadata.example/item.json",
            "metadata": {"name": "On-chain name"},
        },
    }
    requests: list[httpx.Request] = []

    def ton_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"nft_items": [row]})

    async def fetch(uri: str, *, ipfs_gateway_url: str) -> dict[str, object]:
        assert uri == "https://metadata.example/item.json"
        assert ipfs_gateway_url == "https://ipfs.io/ipfs"
        return {
            "name": "Off-chain name",
            "description": "Off-chain description",
            "image": "ipfs://bafybeigdyrzt5sfp7udm7hu76uh2yltop2wyklgdnzbz3u7zvy3gq/image.png",
            "attributes": [{"trait_type": "Rarity", "value": "Rare"}],
        }

    fetch_calls: list[str] = []

    async def counted_fetch(uri: str, *, ipfs_gateway_url: str) -> dict[str, object]:
        fetch_calls.append(uri)
        return await fetch(uri, ipfs_gateway_url=ipfs_gateway_url)

    monkeypatch.setattr(provider_module, "_fetch_metadata_json", counted_fetch)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(ton_handler),
        base_url="https://mock.toncenter.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.toncenter.test/api/v3"),
        client=client,
    )

    page = await provider.get_items_by_owner(OWNER, limit=1, offset=0)
    verified_snapshot = await provider.get_item(ITEM)

    assert page.items[0].metadata.name == "On-chain name"
    assert page.items[0].metadata.description == "Off-chain description"
    assert page.items[0].metadata.image == (
        "https://ipfs.io/ipfs/"
        "bafybeigdyrzt5sfp7udm7hu76uh2yltop2wyklgdnzbz3u7zvy3gq/image.png"
    )
    assert verified_snapshot is not None
    assert verified_snapshot.metadata == page.items[0].metadata
    assert fetch_calls == ["https://metadata.example/item.json"]
    assert requests[0].url.params["owner_address"] == OWNER
    assert requests[1].url.params["address"] == ITEM
    await client.aclose()


@pytest.mark.asyncio
async def test_exact_item_metadata_lookup_uses_requested_item_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.assets.ton_nft import provider as provider_module

    row = {
        "address": ITEM,
        "owner_address": OWNER,
        "collection_address": None,
        "index": "7",
        "init": True,
        "content": {"uri": "https://metadata.example/exact.json"},
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"nft_items": [row]})

    async def fetch(uri: str, *, ipfs_gateway_url: str) -> dict[str, object]:
        assert uri == "https://metadata.example/exact.json"
        return {"name": "Exact NFT"}

    monkeypatch.setattr(provider_module, "_fetch_metadata_json", fetch)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mock.toncenter.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.toncenter.test/api/v3"),
        client=client,
    )

    item = await provider.get_item_with_metadata(ITEM)

    assert item is not None and item.metadata.name == "Exact NFT"
    assert requests[0].url.params["address"] == ITEM
    await client.aclose()


@pytest.mark.asyncio
async def test_metadata_failure_does_not_fail_item_or_ownership_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.assets.ton_nft import provider as provider_module

    row = {
        "address": ITEM,
        "owner_address": OWNER,
        "collection_address": None,
        "index": "7",
        "init": True,
        "content": {"uri": "https://metadata.example/unavailable.json"},
    }

    def ton_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nft_items": [row]})

    async def unavailable(_uri: str, *, ipfs_gateway_url: str) -> None:
        return None

    monkeypatch.setattr(provider_module, "_fetch_metadata_json", unavailable)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(ton_handler),
        base_url="https://mock.toncenter.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.toncenter.test/api/v3"),
        client=client,
    )

    item = await provider.get_item_with_metadata(ITEM)
    assert item is not None
    assert item.owner_address == OWNER
    assert item.metadata.name is None
    await client.aclose()


@pytest.mark.asyncio
async def test_offchain_metadata_merges_onchain_values_over_remote_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.assets.ton_nft import provider as provider_module

    async def fetch(_uri: str, *, ipfs_gateway_url: str) -> dict[str, object]:
        return {
            "name": "Remote name",
            "description": "Remote description",
            "attributes": [{"trait_type": "Remote trait", "value": "Remote"}],
        }

    monkeypatch.setattr(provider_module, "_fetch_metadata_json", fetch)
    provider = TONCenterV3Provider(TONCenterV3Config(base_url="https://ton.example"))
    snapshot_with_metadata = await provider._parse_item_with_metadata(
        {
            "address": ITEM,
            "owner_address": OWNER,
            "collection_address": None,
            "index": "7",
            "init": True,
            "content": {
                "uri": "https://metadata.example/item.json",
                "metadata": {
                    "name": "On-chain name",
                    "attributes": [{"trait_type": "On-chain trait", "value": "On-chain"}],
                },
            },
        }
    )

    assert snapshot_with_metadata.metadata.name == "On-chain name"
    assert snapshot_with_metadata.metadata.description == "Remote description"
    assert snapshot_with_metadata.metadata.attributes == (
        {"trait_type": "On-chain trait", "value": "On-chain"},
    )
    await provider.aclose()


@pytest.mark.asyncio
async def test_malformed_offchain_json_is_optional_display_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.assets.ton_nft import provider as provider_module

    async def malformed(_uri: str, *, ipfs_gateway_url: str) -> None:
        return None

    monkeypatch.setattr(provider_module, "_fetch_metadata_json", malformed)
    provider = TONCenterV3Provider(TONCenterV3Config(base_url="https://ton.example"))
    item = await provider._parse_item_with_metadata(
        {
            "address": ITEM,
            "owner_address": OWNER,
            "collection_address": None,
            "index": "7",
            "init": True,
            "content": {"uri": "https://metadata.example/malformed.json"},
        }
    )
    assert item.owner_address == OWNER
    assert item.metadata.name is None
    await provider.aclose()


@pytest.mark.asyncio
async def test_dns_resolver_fails_closed_for_mixed_public_and_private_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import socket

    from app.assets.ton_nft.metadata import UnsafeMetadataURI, _resolve_public_ip

    async def mixed_getaddrinfo(
        self: asyncio.AbstractEventLoop,
        host: str,
        port: int,
        **_kwargs: object,
    ) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.8", port)),
        ]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", mixed_getaddrinfo)
    with pytest.raises(UnsafeMetadataURI):
        await _resolve_public_ip("metadata.example", 443)


@pytest.mark.asyncio
async def test_metadata_timeout_covers_a_slow_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.assets.ton_nft import metadata as metadata_module

    async def slow_response(_url: str) -> tuple[int, dict[str, str], bytes]:
        await asyncio.sleep(0.05)
        return 200, {"content-type": "application/json"}, b'{"name":"late"}'

    monkeypatch.setattr(metadata_module, "_request_pinned", slow_response)
    assert await metadata_module.fetch_metadata_json(
        "https://metadata.example/item.json", timeout_seconds=0.001
    ) is None


def test_metadata_fields_support_image_url_and_ipfs_media() -> None:
    from app.assets.ton_nft.provider import _metadata_fields

    metadata = _metadata_fields(
        {
            "image_url": (
                "ipfs://bafybeigdyrzt5sfp7udm7hu76uh2yltop2wyklgdnzbz3u7zvy3gq/cover.png"
            )
        }
    )
    assert metadata.image == (
        "https://ipfs.io/ipfs/"
        "bafybeigdyrzt5sfp7udm7hu76uh2yltop2wyklgdnzbz3u7zvy3gq/cover.png"
    )


@pytest.mark.asyncio
async def test_verifier_still_proves_owner_when_metadata_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.assets.ton_nft.provider import TONCenterV3Provider
    from app.assets.ton_nft.verifier import TONNFTVerifier

    rows = {
        "address": ITEM,
        "owner_address": OWNER,
        "collection_address": COLLECTION,
        "index": "7",
        "init": True,
        "content": {"uri": "https://metadata.example/offline.json"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("collection_address") == COLLECTION:
            return httpx.Response(200, json={"nft_items": [rows]})
        return httpx.Response(200, json={"nft_items": [rows]})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mock.toncenter.test/api/v3",
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(base_url="https://mock.toncenter.test/api/v3"),
        client=client,
    )
    result = await TONNFTVerifier(provider).verify(ITEM, OWNER)

    assert result.status is VerificationStatus.VERIFIED
    assert result.metadata.name is None
    await client.aclose()
