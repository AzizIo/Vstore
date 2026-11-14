from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from app.escrow.contracts import (
    DealEscrowDeploymentSnapshot,
    EscrowContractABIUnavailable,
    EscrowWalletAction,
    PinnedTONEscrowContractAdapter,
    UnconfiguredTONEscrowContractAdapter,
)
from app.escrow.ton_abi import (
    TONABIError,
    derive_deployment,
    load_pinned_code_boc,
    verify_compiled_code,
)


def snapshot(**changes: object) -> DealEscrowDeploymentSnapshot:
    values: dict[str, object] = {
        "network": "testnet",
        "network_id": -3,
        "protocol_version": 1,
        "listing_key": "aa" * 32,
        "seller_address": "0:" + "11" * 32,
        "buyer_address": "0:" + "22" * 32,
        "collection_address": "0:" + "33" * 32,
        "item_address": "0:" + "44" * 32,
        "principal_nanotons": 1_000_000_000,
        "execution_reserve_nanotons": 500_000_000,
        "seller_deployment_refund_nanotons": 50_000_000,
        "nft_transfer_value_nanotons": 80_000_000,
        "deal_salt": "01" * 32,
        "activation_query_id": 1000,
        "fund_query_id": 1001,
        "nft_deposit_query_id": 1002,
        "nft_release_query_id": 1003,
        "nft_return_to_escrow_query_id": 1004,
        "oracle_key_a": 1,
        "oracle_key_b": 2,
        "oracle_key_c": 3,
        "resolver_key_a": 4,
        "resolver_key_b": 5,
        "resolver_key_c": 6,
        "deployment_value_nanotons": 200_000_000,
        "activation_value_nanotons": 30_000_000,
        "action_value_nanotons": 30_000_000,
        "nft_deposit_value_nanotons": 50_000_000,
        "nft_return_value_nanotons": 50_000_000,
        "contract_state": 0,
        "deadline_unix": 0,
        "observed_chain_time_unix": 1_700_000_000,
        "dispute_phase": 0,
        "nft_in_escrow": False,
        "principal_locked": False,
        "recovery_previous_owner": None,
        "recovery_item_address": None,
    }
    values.update(changes)
    return DealEscrowDeploymentSnapshot(**values)  # type: ignore[arg-type]


def wallet(address: str) -> SimpleNamespace:
    return SimpleNamespace(address=address, network="testnet", is_verified=True)


def test_pinned_abi_and_code_boc_are_verified() -> None:
    artifacts = verify_compiled_code(load_pinned_code_boc())
    assert artifacts.abi_version == "1.0.0"
    assert artifacts.code_hash == (
        "E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548"
    )
    assert len(artifacts.code_boc_sha256) == 64


def test_state_init_is_deterministic_and_address_is_state_init_hash() -> None:
    deal = snapshot()
    first = derive_deployment(load_pinned_code_boc(), deal)
    second = derive_deployment(load_pinned_code_boc(), deal)
    assert first == second
    assert first.address == "0:" + first.state_init_hash
    assert first.code_hash == (
        "E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548"
    )
    # Expected values were independently produced by the generated Acton
    # TypeScript wrapper and @ton/core 0.63.1 in TON Contract CI.
    assert first.address == (
        "0:91ba23ed193de18a2e77484ad8bbe734df8bed085bc19521aeeb4aba1849f7dd"
    )
    assert first.state_init_hash == (
        "91ba23ed193de18a2e77484ad8bbe734df8bed085bc19521aeeb4aba1849f7dd"
    )
    assert first.data_hash == (
        "535adf460ca6ecb6e043e0655244e3c67bfee186263287655306b1b648027acd"
    )
    assert first.code_hash == (
        "E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548"
    )
    assert first.state_init_boc
    assert first.data_boc


def test_snapshot_is_immutable_and_testnet_only() -> None:
    deal = snapshot()
    with pytest.raises(FrozenInstanceError):
        deal.deal_salt = "02" * 32  # type: ignore[misc]
    with pytest.raises(TONABIError, match="testnet"):
        derive_deployment(load_pinned_code_boc(), replace(deal, network="mainnet"))


def test_snapshot_rejects_duplicate_authority_keys_and_invalid_reserve() -> None:
    deal = snapshot()
    with pytest.raises(TONABIError, match="globally unique"):
        derive_deployment(
            load_pinned_code_boc(),
            replace(deal, resolver_key_a=deal.oracle_key_a),
        )
    with pytest.raises(TONABIError, match="reserve formula"):
        derive_deployment(
            load_pinned_code_boc(),
            replace(deal, execution_reserve_nanotons=400_000_000),
        )
    with pytest.raises(TONABIError, match="deployment value cannot fund activation"):
        derive_deployment(
            load_pinned_code_boc(),
            replace(deal, deployment_value_nanotons=60_000_000),
        )
    with pytest.raises(TONABIError, match="state is not defined"):
        derive_deployment(
            load_pinned_code_boc(),
            replace(deal, contract_state=14),
        )


@pytest.mark.asyncio
async def test_deploy_and_activate_are_distinct_ton_connect_actions() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    assert adapter.abi_version == "1.0.0"
    deal = snapshot()

    deploy = await adapter.prepare_transaction(
        EscrowWalletAction.CREATE_DEAL_ESCROW,
        actor_wallet=wallet(deal.seller_address),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=deal,
        valid_until=1_800_000_000,
    )
    assert deploy.network == "-3"
    assert deploy.messages[0].address == derive_deployment(load_pinned_code_boc(), deal).address
    assert deploy.messages[0].amount == "200000000"
    assert deploy.messages[0].state_init is not None
    assert deploy.messages[0].payload is None
    assert deploy.to_tonconnect_dict()["validUntil"] == 1_800_000_000

    activate = await adapter.prepare_transaction(
        EscrowWalletAction.ACTIVATE_DEAL,
        actor_wallet=wallet(deal.seller_address),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=deal,
        valid_until=1_800_000_000,
    )
    assert activate.messages[0].address == deploy.messages[0].address
    assert activate.messages[0].amount == "30000000"
    assert activate.messages[0].payload is not None
    assert activate.messages[0].state_init is None


@pytest.mark.asyncio
async def test_buyer_funding_is_exact_principal_plus_execution_reserve() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot(
        contract_state=2,
        deadline_unix=1_800_000_000,
        nft_in_escrow=True,
    )
    payload = await adapter.prepare_transaction(
        EscrowWalletAction.FUND_DEAL,
        actor_wallet=wallet(deal.buyer_address),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=deal,
        valid_until=1_800_000_000,
    )
    assert payload.messages[0].address == derive_deployment(load_pinned_code_boc(), deal).address
    assert payload.messages[0].amount == "1500000000"
    assert payload.messages[0].payload


@pytest.mark.asyncio
async def test_only_verified_participant_wallet_can_prepare_actions() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot()
    with pytest.raises(EscrowContractABIUnavailable, match="participant"):
        await adapter.prepare_transaction(
            EscrowWalletAction.CREATE_DEAL_ESCROW,
            actor_wallet=wallet("0:" + "55" * 32),  # type: ignore[arg-type]
            resource_id="deal-1",
            deal_snapshot=deal,
        )
    unverified = SimpleNamespace(
        address=deal.seller_address, network="testnet", is_verified=False
    )
    with pytest.raises(EscrowContractABIUnavailable, match="verified"):
        await adapter.prepare_transaction(
            EscrowWalletAction.CREATE_DEAL_ESCROW,
            actor_wallet=unverified,  # type: ignore[arg-type]
            resource_id="deal-1",
            deal_snapshot=deal,
        )


@pytest.mark.asyncio
async def test_post_delivery_nft_return_is_buyer_only_and_state_bound() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot(
        contract_state=6,
        deadline_unix=1_800_000_000,
        observed_chain_time_unix=1_700_000_000,
        dispute_phase=2,
        nft_in_escrow=False,
        principal_locked=True,
    )
    payload = await adapter.prepare_transaction(
        EscrowWalletAction.RETURN_NFT_TO_ESCROW,
        actor_wallet=wallet(deal.buyer_address),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=deal,
        valid_until=1_800_000_000,
    )
    assert payload.messages[0].address == deal.item_address
    assert payload.messages[0].amount == "50000000"
    assert payload.messages[0].payload


@pytest.mark.asyncio
async def test_contract_initiated_payout_and_refund_are_never_wallet_actions() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot()
    for action in (EscrowWalletAction.PAYOUT, EscrowWalletAction.REFUND):
        with pytest.raises(EscrowContractABIUnavailable, match="contract-initiated"):
            await adapter.prepare_transaction(
                action,
                actor_wallet=wallet(deal.seller_address),  # type: ignore[arg-type]
                resource_id="deal-1",
                deal_snapshot=deal,
            )


@pytest.mark.asyncio
async def test_unconfigured_adapter_remains_fail_closed() -> None:
    adapter = UnconfiguredTONEscrowContractAdapter()
    assert adapter.abi_version is None
    with pytest.raises(EscrowContractABIUnavailable, match="disabled"):
        await adapter.prepare_transaction(
            EscrowWalletAction.FUND_DEAL,
            actor_wallet=object(),  # type: ignore[arg-type]
            resource_id="deal-id",
            deal_snapshot=snapshot(),
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
