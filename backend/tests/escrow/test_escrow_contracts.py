from __future__ import annotations

import pytest

from app.escrow.contracts import (
    EscrowContractABIUnavailable,
    EscrowWalletAction,
    UnconfiguredTONEscrowContractAdapter,
)


@pytest.mark.asyncio
async def test_abi_unconfigured_adapter_never_builds_a_fake_payload() -> None:
    adapter = UnconfiguredTONEscrowContractAdapter()
    assert adapter.abi_version is None
    with pytest.raises(EscrowContractABIUnavailable, match="ABI is approved"):
        await adapter.prepare_transaction(
            EscrowWalletAction.FUND_DEAL,
            actor_wallet=object(),  # type: ignore[arg-type]
            resource_id="intent-only",
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
