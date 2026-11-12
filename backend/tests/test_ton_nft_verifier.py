*** Begin Patch
*** Update File: backend/tests/test_ton_nft_verifier.py
@@
 from __future__ import annotations
 
+import ipaddress
+
 import ipaddress

import httpx
 import pytest
@@
 from app.assets.ton_nft.provider import (
     MAX_PROVIDER_RESPONSE_BYTES,
     TONCenterV3Config,
     TONCenterV3Provider,
    _metadata_fields,
    _normalize_uri,
+    _metadata_fields,
+    _normalize_uri,
 )
@@
-    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.test/api/v3")
+    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.test/api/v3")
+    provider_module_resolver = None
@@
     await client.aclose()
+
+
+def test_offchain_uri_and_ipfs_are_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setattr("app.assets.ton_nft.provider._resolve_public_host", lambda *_: True)
+    assert _normalize_uri("https://metadata.example/nft.json") == "https://metadata.example/nft.json"
+    assert _normalize_uri("ipfs://bafybeigdyrzt/example.json") == (
+        "https://ipfs.io/ipfs/bafybeigdyrzt/example.json"
+    )
+    assert _normalize_uri("ipfs://../secret") is None
+    assert _normalize_uri("http://metadata.example/nft.json") is None
+
+
+def test_private_ip_and_invalid_image_urls_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setattr(
+        "app.assets.ton_nft.provider._resolve_public_host",
+        lambda *_: ipaddress.ip_address("127.0.0.1").is_global,
+    )
+    assert _normalize_uri("https://127.0.0.1/private") is None
+    assert _metadata_fields({"image": "http://127.0.0.1/image.png"}).image is None
+
+
+@pytest.mark.asyncio
+async def test_offchain_metadata_is_resolved_and_onchain_values_win(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    monkeypatch.setattr("app.assets.ton_nft.provider._resolve_public_host", lambda *_: True)
+    provider = TONCenterV3Provider(TONCenterV3Config(base_url="https://ton.example"))
+
+    async def fetch(uri: str) -> dict[str, object]:
+        assert uri == "https://metadata.example/item.json"
+        return {
+            "name": "Off-chain name", "description": "Description",
+            "image": "https://cdn.example/image.png",
+            "attributes": [{"trait_type": "Rarity", "value": "Rare"}],
+        }
+
+    monkeypatch.setattr(provider, "_fetch_metadata_json", fetch)
+    metadata = await provider._metadata({
+        "content": {"uri": "https://metadata.example/item.json", "name": "On-chain name"}
+    })
+    assert metadata.name == "On-chain name"
+    assert metadata.description == "Description"
+    assert metadata.image == "https://cdn.example/image.png"
+    assert metadata.attributes == ({"trait_type": "Rarity", "value": "Rare"},)
+    await provider.aclose()
+
+
+@pytest.mark.asyncio
+async def test_metadata_fetch_failure_does_not_break_item_or_owner_verification(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    monkeypatch.setattr("app.assets.ton_nft.provider._resolve_public_host", lambda *_: True)
+    provider = TONCenterV3Provider(TONCenterV3Config(base_url="https://ton.example"))
+
+    async def unavailable(_: str) -> None:
+        return None
+
+    monkeypatch.setattr(provider, "_fetch_metadata_json", unavailable)
+    item = {
+        "address": ITEM, "owner_address": OWNER, "collection_address": COLLECTION,
+        "index": "7", "init": True,
+        "content": {"uri": "https://metadata.example/missing.json"},
+    }
+    snapshot_with_metadata = await provider._parse_item_with_metadata(item)
+    assert snapshot_with_metadata.owner_address == OWNER
+    assert snapshot_with_metadata.metadata.name is None
+    await provider.aclose()
+
+
+@pytest.mark.asyncio
+async def test_offchain_malformed_json_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setattr("app.assets.ton_nft.provider._resolve_public_host", lambda *_: True)
+    provider = TONCenterV3Provider(TONCenterV3Config(base_url="https://ton.example"))
+
+    async def malformed(_: str) -> None:
+        return None
+
+    monkeypatch.setattr(provider, "_fetch_metadata_json", malformed)
+    metadata = await provider._metadata({"content": {"uri": "https://metadata.example/bad.json"}})
+    assert metadata.name is None and metadata.image is None
+    await provider.aclose()
*** End Patch


def test_offchain_uri_and_ipfs_are_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.assets.ton_nft.provider._resolve_public_host", lambda *_: True)
    assert _normalize_uri("https://metadata.example/nft.json") == "https://metadata.example/nft.json"
    assert _normalize_uri("ipfs://bafybeigdyrzt/example.json") == (
        "https://ipfs.io/ipfs/bafybeigdyrzt/example.json"
    )
    assert _normalize_uri("ipfs://../secret") is None
    assert _normalize_uri("http://metadata.example/nft.json") is None


def test_private_ip_and_invalid_image_urls_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.assets.ton_nft.provider._resolve_public_host",
        lambda *_: ipaddress.ip_address("127.0.0.1").is_global,
    )
    assert _normalize_uri("https://127.0.0.1/private") is None
    assert _metadata_fields({"image": "http://127.0.0.1/image.png"}).image is None


@pytest.mark.asyncio
async def test_offchain_metadata_is_resolved_and_onchain_values_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.assets.ton_nft.provider._resolve_public_host", lambda *_: True)
    provider = TONCenterV3Provider(TONCenterV3Config(base_url="https://ton.example"))

    async def fetch(uri: str) -> dict[str, object] | None:
        assert uri == "https://metadata.example/item.json"
        return {
            "name": "Off-chain name", "description": "Description",
            "image": "https://cdn.example/image.png",
            "attributes": [{"trait_type": "Rarity", "value": "Rare"}],
        }

    monkeypatch.setattr(provider, "_fetch_metadata_json", fetch)
    metadata = await provider._metadata({
        "content": {"uri": "https://metadata.example/item.json", "name": "On-chain name"}
    })
    assert metadata.name == "On-chain name"
    assert metadata.description == "Description"
    assert metadata.image == "https://cdn.example/image.png"
    assert metadata.attributes == ({"trait_type": "Rarity", "value": "Rare"},)
    await provider.aclose()


@pytest.mark.asyncio
async def test_metadata_fetch_failure_is_non_fatal_to_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.assets.ton_nft.provider._resolve_public_host", lambda *_: True)
    provider = TONCenterV3Provider(TONCenterV3Config(base_url="https://ton.example"))

    async def unavailable(_: str) -> dict[str, object] | None:
        return None

    monkeypatch.setattr(provider, "_fetch_metadata_json", unavailable)
    item = {
        "address": ITEM, "owner_address": OWNER, "collection_address": COLLECTION,
        "index": "7", "init": True,
        "content": {"uri": "https://metadata.example/missing.json"},
    }
    snapshot_with_metadata = await provider._parse_item_with_metadata(item)
    assert snapshot_with_metadata.owner_address == OWNER
    assert snapshot_with_metadata.metadata.name is None
    await provider.aclose()


@pytest.mark.asyncio
async def test_offchain_malformed_json_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.assets.ton_nft.provider._resolve_public_host", lambda *_: True)
    provider = TONCenterV3Provider(TONCenterV3Config(base_url="https://ton.example"))

    async def malformed(_: str) -> dict[str, object] | None:
        return None

    monkeypatch.setattr(provider, "_fetch_metadata_json", malformed)
    metadata = await provider._metadata({"content": {"uri": "https://metadata.example/bad.json"}})
    assert metadata.name is None and metadata.image is None
    await provider.aclose()
