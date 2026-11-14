from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.escrow.contracts import (
    DealEscrowDeploymentSnapshot,
    EscrowContractABIUnavailable,
    EscrowWalletAction,
    UnconfiguredTONEscrowContractAdapter,
)


@pytest.mark.asyncio
async def test_abi_unconfigured_adapter_never_builds_a_fake_payload() -> None:
    adapter = UnconfiguredTONEscrowContractAdapter()
    assert adapter.abi_version is None
    snapshot = DealEscrowDeploymentSnapshot(
        network="testnet", listing_key="l" * 64,
        seller_address="0:" + "a" * 64, buyer_address="0:" + "b" * 64,
        collection_address="0:" + "c" * 64, item_address="0:" + "d" * 64,
        principal_nanotons=2_500_000_000, deal_salt="s" * 64,
    )
    with pytest.raises(FrozenInstanceError):
        snapshot.deal_salt = "changed"  # type: ignore[misc]
    with pytest.raises(EscrowContractABIUnavailable, match="ABI is approved"):
        await adapter.prepare_transaction(
            EscrowWalletAction.FUND_DEAL,
            actor_wallet=object(),  # type: ignore[arg-type]
            resource_id="deal-id",
            deal_snapshot=snapshot,
        )


@pytest.mark.asyncio
async def test_unconfigured_testnet_provider_fails_closed() -> None:
    from app.escrow.provider import (
        EscrowProviderUnavailable,
        UnconfiguredTONTestnetEscrowProvider,
    )

    provider = UnconfiguredTONTestnetEscrowProvider()
    with pytest.raises(EscrowProviderUnavailable):
        await provider.scan_events(cursor=None, limit=10)
