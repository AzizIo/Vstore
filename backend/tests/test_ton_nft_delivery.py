from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.assets.ton_nft.delivery import (
    DeliveryEvidenceStatus,
    TONCenterDeliveryConfig,
    TONCenterDeliveryEvidenceProvider,
    TEP62TransferIntent,
)
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable

ITEM = "0:" + "11" * 32
SELLER = "0:" + "22" * 32
BUYER = "0:" + "33" * 32
OTHER = "0:" + "44" * 32
TX_HASH = "ab" * 32
TRACE_ID = "cd" * 32
QUERY_ID = 42
NETWORK = "mainnet"


def intent(**changes: Any) -> TEP62TransferIntent:
    values: dict[str, Any] = {
        "item_address": ITEM,
        "network": NETWORK,
        "seller_wallet_address": SELLER,
        "buyer_wallet_address": BUYER,
        "query_id": QUERY_ID,
    }
    values.update(changes)
    return TEP62TransferIntent(**values)


def transfer_row(**changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "nft_address": ITEM,
        "old_owner": SELLER,
        "new_owner": BUYER,
        "query_id": str(QUERY_ID),
        "transaction_aborted": False,
        "transaction_hash": TX_HASH,
        "trace_id": TRACE_ID,
    }
    row.update(changes)
    return row


def item_transaction(**changes: Any) -> dict[str, Any]:
    transaction: dict[str, Any] = {
        "account": ITEM,
        "hash": TX_HASH,
        "in_msg": {
            "source": SELLER,
            "destination": ITEM,
            "opcode": 0x5FCC3D14,
        },
        "description": {
            "aborted": False,
            "compute_ph": {"success": True},
            "action": {"success": True},
        },
    }
    transaction.update(changes)
    return transaction


def trace_payload(**changes: Any) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "trace_id": TRACE_ID,
        "is_incomplete": False,
        "mc_seqno_end": "123456",
        "actions": [
            {
                "success": True,
                "transactions_full": [item_transaction()],
            }
        ],
    }
    trace.update(changes)
    return {"traces": [trace]}


def provider_for(handler) -> tuple[TONCenterDeliveryEvidenceProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://mock.toncenter.test/api/v3",
    )
    provider = TONCenterDeliveryEvidenceProvider(
        TONCenterDeliveryConfig(
            base_url="https://mock.toncenter.test/api/v3",
            network=NETWORK,
        ),
        client=client,
    )
    return provider, client


@pytest.mark.asyncio
async def test_verifies_exact_finalized_tep62_transfer_from_seller_to_buyer() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/nft/transfers"):
            return httpx.Response(200, json={"nft_transfers": [transfer_row()]})
        if request.url.path.endswith("/traces"):
            return httpx.Response(200, json=trace_payload())
        return httpx.Response(404)

    provider, client = provider_for(handler)
    try:
        result = await provider.verify_transfer(intent())
    finally:
        await client.aclose()

    assert result.status is DeliveryEvidenceStatus.VERIFIED_FINALIZED
    assert result.item_address == ITEM
    assert result.seller_wallet_address == SELLER
    assert result.buyer_wallet_address == BUYER
    assert result.query_id == QUERY_ID
    assert result.transaction_hash == TX_HASH
    assert result.trace_id == TRACE_ID
    assert result.masterchain_seqno == 123456
    assert result.evidence_source == "toncenter_v3_indexer"
    assert [request.url.path for request in requests] == [
        "/api/v3/nft/transfers",
        "/api/v3/traces",
    ]
    assert requests[0].url.params["item_address"] == ITEM
    assert requests[1].url.params["trace_id"] == TRACE_ID
    assert requests[1].url.params["include_actions"] == "true"


@pytest.mark.asyncio
async def test_returns_not_found_when_query_id_has_no_matching_transfer() -> None:
    provider, client = provider_for(
        lambda _: httpx.Response(200, json={"nft_transfers": [transfer_row(query_id="41")]})
    )
    try:
        result = await provider.verify_transfer(intent())
    finally:
        await client.aclose()

    assert result.status is DeliveryEvidenceStatus.NOT_FOUND
    assert result.transaction_hash is None


@pytest.mark.asyncio
async def test_returns_inconclusive_when_trace_is_not_indexed_yet() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/nft/transfers"):
            return httpx.Response(200, json={"nft_transfers": [transfer_row()]})
        return httpx.Response(200, json={"traces": []})

    provider, client = provider_for(handler)
    try:
        result = await provider.verify_transfer(intent())
    finally:
        await client.aclose()

    assert result.status is DeliveryEvidenceStatus.INCONCLUSIVE
    assert "not indexed yet" in (result.reason or "")


@pytest.mark.asyncio
async def test_incomplete_trace_is_never_treated_as_finalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/nft/transfers"):
            return httpx.Response(200, json={"nft_transfers": [transfer_row()]})
        return httpx.Response(200, json=trace_payload(is_incomplete=True))

    provider, client = provider_for(handler)
    try:
        result = await provider.verify_transfer(intent())
    finally:
        await client.aclose()

    assert result.status is DeliveryEvidenceStatus.INCONCLUSIVE
    assert result.masterchain_seqno is None


@pytest.mark.asyncio
async def test_transfer_to_wrong_buyer_is_failed_not_successful() -> None:
    provider, client = provider_for(
        lambda _: httpx.Response(200, json={"nft_transfers": [transfer_row(new_owner=OTHER)]})
    )
    try:
        result = await provider.verify_transfer(intent())
    finally:
        await client.aclose()

    assert result.status is DeliveryEvidenceStatus.FAILED
    assert "recipient" in (result.reason or "")


@pytest.mark.asyncio
async def test_item_transaction_must_be_the_seller_signed_tep62_transfer() -> None:
    bad_transaction = item_transaction(
        in_msg={"source": OTHER, "destination": ITEM, "opcode": 0x5FCC3D14}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/nft/transfers"):
            return httpx.Response(200, json={"nft_transfers": [transfer_row()]})
        payload = trace_payload(
            actions=[{"success": True, "transactions_full": [bad_transaction]}]
        )
        return httpx.Response(200, json=payload)

    provider, client = provider_for(handler)
    try:
        result = await provider.verify_transfer(intent())
    finally:
        await client.aclose()

    assert result.status is DeliveryEvidenceStatus.FAILED
    assert "seller-signed TEP-62" in (result.reason or "")


@pytest.mark.asyncio
async def test_aborted_transfer_transaction_is_failed() -> None:
    provider, client = provider_for(
        lambda _: httpx.Response(
            200,
            json={"nft_transfers": [transfer_row(transaction_aborted=True)]},
        )
    )
    try:
        result = await provider.verify_transfer(intent())
    finally:
        await client.aclose()

    assert result.status is DeliveryEvidenceStatus.FAILED
    assert "aborted" in (result.reason or "")


@pytest.mark.asyncio
async def test_aborted_item_transaction_is_failed() -> None:
    failed_transaction = item_transaction(
        description={
            "aborted": True,
            "compute_ph": {"success": False},
            "action": {"success": False},
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/nft/transfers"):
            return httpx.Response(200, json={"nft_transfers": [transfer_row()]})
        return httpx.Response(
            200,
            json=trace_payload(
                actions=[{"success": True, "transactions_full": [failed_transaction]}]
            ),
        )

    provider, client = provider_for(handler)
    try:
        result = await provider.verify_transfer(intent())
    finally:
        await client.aclose()

    assert result.status is DeliveryEvidenceStatus.FAILED
    assert "aborted" in (result.reason or "")


@pytest.mark.asyncio
async def test_provider_outage_raises_typed_unavailable_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    provider, client = provider_for(handler)
    try:
        with pytest.raises(ProviderUnavailable):
            await provider.verify_transfer(intent())
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_malformed_transfer_payload_fails_closed() -> None:
    provider, client = provider_for(lambda _: httpx.Response(200, json={"transfers": []}))
    try:
        with pytest.raises(InvalidProviderData, match="nft_transfers"):
            await provider.verify_transfer(intent())
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_wrong_network_is_rejected_before_provider_request() -> None:
    requested: list[httpx.Request] = []
    provider, client = provider_for(
        lambda request: requested.append(request) or httpx.Response(200, json={})
    )
    try:
        with pytest.raises(InvalidProviderData, match="network"):
            await provider.verify_transfer(intent(network="testnet"))
    finally:
        await client.aclose()

    assert requested == []


@pytest.mark.asyncio
async def test_invalid_query_id_is_rejected_before_provider_request() -> None:
    requested: list[httpx.Request] = []
    provider, client = provider_for(
        lambda request: requested.append(request) or httpx.Response(200, json={})
    )
    try:
        with pytest.raises(InvalidProviderData, match="query_id"):
            await provider.verify_transfer(intent(query_id=-1))
    finally:
        await client.aclose()

    assert requested == []

@pytest.mark.asyncio
async def test_case_sensitive_base64_hashes_are_preserved_for_transfer_and_trace_lookup() -> None:
    transaction_hash = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
    trace_id = "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8="

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/nft/transfers"):
            return httpx.Response(
                200,
                json={
                    "nft_transfers": [
                        transfer_row(
                            transaction_hash=transaction_hash,
                            trace_id=trace_id,
                        )
                    ]
                },
            )
        return httpx.Response(
            200,
            json=trace_payload(
                trace_id=trace_id,
                actions=[
                    {
                        "success": True,
                        "transactions_full": [item_transaction(hash=transaction_hash)],
                    }
                ],
            ),
        )

    provider, client = provider_for(handler)
    try:
        result = await provider.verify_transfer(intent())
    finally:
        await client.aclose()

    assert result.status is DeliveryEvidenceStatus.VERIFIED_FINALIZED
    assert result.transaction_hash == transaction_hash
    assert result.trace_id == trace_id
