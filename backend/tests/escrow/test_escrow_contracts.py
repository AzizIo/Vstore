from __future__ import annotations

import base64
import hashlib
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


def boc_sha256(payload: str) -> str:
    raw = base64.b64decode(payload, validate=True)
    return hashlib.sha256(raw).hexdigest()


def test_pinned_abi_and_code_boc_are_verified() -> None:
    artifacts = verify_compiled_code(load_pinned_code_boc())
    assert artifacts.abi_version == "1.0.0"
    assert artifacts.code_hash == (
        "D822B8AFBB37027611A9A9DDC8E67C52F17BBBC45B4352C7F360693BD685CA54"
    )
    assert len(artifacts.code_boc_sha256) == 64


def test_state_init_is_deterministic_and_address_is_state_init_hash() -> None:
    deal = snapshot()
    first = derive_deployment(load_pinned_code_boc(), deal)
    second = derive_deployment(load_pinned_code_boc(), deal)
    assert first == second
    assert first.address == "0:" + first.state_init_hash
    assert first.code_hash == (
        "D822B8AFBB37027611A9A9DDC8E67C52F17BBBC45B4352C7F360693BD685CA54"
    )
    # Expected values were independently produced by the generated Acton
    # TypeScript wrapper and @ton/core 0.63.1 in TON Contract CI.
    assert first.address == (
        "0:29a40423c7e8fa1390782bce7e94e32f2a0e14ceef6cf05bd0f1641d0ba3f423"
    )
    assert first.state_init_hash == (
        "29a40423c7e8fa1390782bce7e94e32f2a0e14ceef6cf05bd0f1641d0ba3f423"
    )
    assert first.data_hash == (
        "faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b"
    )
    assert first.code_hash == (
        "D822B8AFBB37027611A9A9DDC8E67C52F17BBBC45B4352C7F360693BD685CA54"
    )
    assert first.state_init_boc
    assert first.data_boc


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"network_id": -239}, "network_id must be TON testnet"),
        ({"seller_address": "not-an-address"}, "seller_address"),
        ({"item_address": "1:" + "44" * 32}, "item_address must be a basechain"),
        ({"deal_salt": "01" * 31}, "deal_salt must be exactly 32 bytes"),
        ({"deal_salt": "00" * 32}, "deal_salt must be non-zero"),
        ({"principal_nanotons": 0}, "principal_nanotons"),
        ({"seller_deployment_refund_nanotons": 10_000_000}, "seller deployment refund"),
        ({"nft_transfer_value_nanotons": 151_000_000}, "NFT transfer value"),
        ({"activation_query_id": 0}, "activation_query_id"),
        ({"fund_query_id": 1000}, "query IDs must be unique"),
        ({"resolver_key_b": 1}, "globally unique"),
        ({"contract_state": 14}, "contract_state is not defined"),
        ({"dispute_phase": 3}, "dispute_phase is not defined"),
    ],
)
def test_snapshot_rejects_mutated_or_incomplete_chain_terms(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(TONABIError, match=message):
        derive_deployment(load_pinned_code_boc(), replace(snapshot(), **changes))


def test_deployment_snapshot_requires_all_immutable_fields() -> None:
    with pytest.raises(TypeError, match="required positional arguments"):
        DealEscrowDeploymentSnapshot(network="testnet")  # type: ignore[call-arg]


def test_invalid_or_tampered_compiled_code_boc_fails_closed() -> None:
    with pytest.raises(TONABIError, match="DealEscrow code BOC is malformed"):
        verify_compiled_code("not-a-valid-base64-boc")

    valid_boc = load_pinned_code_boc()
    tampered_boc = ("A" if valid_boc[0] != "A" else "B") + valid_boc[1:]
    with pytest.raises(TONABIError, match="DealEscrow code BOC"):
        verify_compiled_code(tampered_boc)


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
            replace(
                deal,
                execution_reserve_nanotons=500_000_000,
                nft_transfer_value_nanotons=150_000_000,
                seller_deployment_refund_nanotons=100_000_000,
            ),
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
    assert boc_sha256(activate.messages[0].payload) == (
        "d277f33218afe7a525da50ecd8d61770c6a21112fe9b529d1f6951a7a5d55476"
    )
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
    assert boc_sha256(payload.messages[0].payload) == (
        "ed4ce8f9f3d78815d72e2ecfbecbc9f38aa6d4863a55b4a777a1459449819db6"
    )

@pytest.mark.asyncio
async def test_wallet_network_and_actor_state_must_match_deal() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot(contract_state=2, nft_in_escrow=True, deadline_unix=1_800_000_000)
    wrong_network = SimpleNamespace(
        address=deal.buyer_address, network="mainnet", is_verified=True
    )
    with pytest.raises(EscrowContractABIUnavailable, match="testnet wallet"):
        await adapter.prepare_transaction(
            EscrowWalletAction.FUND_DEAL,
            actor_wallet=wrong_network,  # type: ignore[arg-type]
            resource_id="deal-1",
            deal_snapshot=deal,
            valid_until=1_800_000_000,
        )

    with pytest.raises(EscrowContractABIUnavailable, match="bound buyer"):
        await adapter.prepare_transaction(
            EscrowWalletAction.FUND_DEAL,
            actor_wallet=wallet(deal.seller_address),  # type: ignore[arg-type]
            resource_id="deal-1",
            deal_snapshot=deal,
            valid_until=1_800_000_000,
        )

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
    assert boc_sha256(payload.messages[0].payload) == (
        "70fd158e2e4b99648fea5a4dbf759274ac35a946538dfd6ba591fb2b2de24ceb"
    )

@pytest.mark.asyncio
async def test_seller_nft_deposit_payload_matches_generated_tep62_abi() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot(contract_state=1, deadline_unix=1_800_000_000)
    payload = await adapter.prepare_transaction(
        EscrowWalletAction.DEPOSIT_NFT,
        actor_wallet=wallet(deal.seller_address),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=deal,
        valid_until=1_800_000_000,
    )
    assert payload.messages[0].address == deal.item_address
    assert payload.messages[0].payload is not None
    assert boc_sha256(payload.messages[0].payload) == (
        "32148753a5d3cd318a3a54f7ff8d9409e8cfbe04d70862a52833632a50362cf7"
    )

@pytest.mark.asyncio
async def test_accept_dispute_timeout_and_recovery_bocs_match_generated_abi() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot(
        contract_state=3,
        deadline_unix=1_800_000_000,
        nft_in_escrow=True,
        principal_locked=True,
    )
    accept = await adapter.prepare_transaction(
        EscrowWalletAction.ACCEPT_DEAL,
        actor_wallet=wallet(deal.buyer_address),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=deal,
        valid_until=1_800_000_000,
    )
    assert accept.messages[0].payload is not None
    assert boc_sha256(accept.messages[0].payload) == (
        "aaebfe6189c5d23bfe5227ce4fbe0b97bf10cf763ac2e092d608730f50e4ce1b"
    )

    dispute = await adapter.prepare_transaction(
        EscrowWalletAction.OPEN_DISPUTE,
        actor_wallet=wallet(deal.buyer_address),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=deal,
        query_id=2001,
        reason_hash=int("ab" * 32, 16),
        valid_until=1_800_000_000,
    )
    assert dispute.messages[0].payload is not None
    assert boc_sha256(dispute.messages[0].payload) == (
        "687c3f5300af7371f946dd9dae1c849eede2887f167f8028aa4d1da228a709cd"
    )

    timeout_deal = replace(
        deal,
        contract_state=1,
        deadline_unix=1_699_999_999,
        observed_chain_time_unix=1_700_000_000,
        nft_in_escrow=False,
        principal_locked=False,
    )
    timeout = await adapter.prepare_transaction(
        EscrowWalletAction.TIMEOUT_DEAL,
        actor_wallet=wallet(timeout_deal.seller_address),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=timeout_deal,
        query_id=2002,
        valid_until=1_800_000_000,
    )
    assert timeout.messages[0].payload is not None
    assert boc_sha256(timeout.messages[0].payload) == (
        "2cc8443c10c2749973e51ce2e051ebfaac6e8bb191e231948104a235dc3e43f3"
    )

    recovery_deal = replace(
        deal,
        contract_state=13,
        recovery_previous_owner=deal.seller_address,
        recovery_item_address="0:" + "55" * 32,
    )
    recovery = await adapter.prepare_transaction(
        EscrowWalletAction.RECOVER_UNEXPECTED_NFT,
        actor_wallet=wallet(recovery_deal.seller_address),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=recovery_deal,
        query_id=2003,
        valid_until=1_800_000_000,
    )
    assert recovery.messages[0].address == derive_deployment(
        load_pinned_code_boc(), recovery_deal
    ).address
    assert recovery.messages[0].payload is not None
    assert boc_sha256(recovery.messages[0].payload) == (
        "296bbfd9ed948575f6e8dfd31d529384e016cbfe321f73d42717b294b8b3ac34"
    )

@pytest.mark.asyncio
async def test_unexpected_nft_recovery_requires_recorded_previous_owner() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot(
        contract_state=13,
        nft_in_escrow=True,
        recovery_previous_owner="0:" + "55" * 32,
        recovery_item_address="0:" + "66" * 32,
    )

    with pytest.raises(
        EscrowContractABIUnavailable,
        match="only the recorded previous NFT owner",
    ):
        await adapter.prepare_transaction(
            EscrowWalletAction.RECOVER_UNEXPECTED_NFT,
            actor_wallet=wallet(deal.seller_address),  # type: ignore[arg-type]
            resource_id="deal-1",
            deal_snapshot=deal,
            query_id=2004,
            valid_until=1_800_000_000,
        )

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

def test_pinned_code_boc_rejects_compressed_artifact_digest_mismatch(
    tmp_path, monkeypatch
) -> None:
    import base64

    import pytest

    from app.escrow import ton_abi

    source_artifacts = ton_abi._ARTIFACTS
    (tmp_path / "DealEscrow.abi.json").write_text(
        (source_artifacts / "DealEscrow.abi.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        (source_artifacts / "manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    compressed = base64.b64decode(
        (source_artifacts / "DealEscrow.code.boc.zlib.b64")
        .read_text(encoding="ascii")
        .strip(),
        validate=True,
    )
    tampered = base64.b64encode(compressed + b"\\x00").decode("ascii")
    (tmp_path / "DealEscrow.code.boc.zlib.b64").write_text(
        tampered, encoding="ascii"
    )

    monkeypatch.setattr(ton_abi, "_ARTIFACTS", tmp_path)
    ton_abi.load_pinned_abi.cache_clear()
    try:
        with pytest.raises(ton_abi.TONABIError, match="compressed code BOC digest mismatch"):
            ton_abi.load_pinned_code_boc()
    finally:
        ton_abi.load_pinned_abi.cache_clear()


def _outbound_retry_proof(
    deal: DealEscrowDeploymentSnapshot,
    *,
    kind: int = 4,
    query_id: int = 42,
    recipient: str | None = None,
    retry_window_seconds: int = 1800,
    status: int = 1,
    amount_nanotons: int = 90_000_000,
):
    from app.escrow.contracts import OutboundRetryProof, ProofBoundOutboundAction

    recipient = recipient or deal.buyer_address
    return OutboundRetryProof(
        action=ProofBoundOutboundAction(
            slot="first",
            kind=kind,
            query_id=query_id,
            deal_salt=deal.deal_salt,
            attempt_id=7,
            amount_nanotons=amount_nanotons,
            message_value_nanotons=amount_nanotons,
            expected_state=10,
            expected_pending_action=0,
            retry_window_seconds=retry_window_seconds,
            message_body_hash="ab" * 32,
            status=status,
            bounce_phase=1,
            exit_code=37,
            item_address=deal.item_address,
            destination_address=recipient,
            recipient_address=recipient,
            response_address=recipient,
        ),
        masterchain_seqno=700,
        masterchain_block_hash="cd" * 32,
        state_data_hash="ef" * 32,
        provider_id="pytoniq-trust0-testnet-v1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "window", "recipient_role"),
    [(1, 1800, "buyer"), (4, 1800, "seller"), (6, 0, "seller"), (7, 0, "buyer")],
)
async def test_retry_failed_outbound_action_encodes_exact_proved_query_and_deal_salt(
    kind: int, window: int, recipient_role: str
) -> None:
    from pytoniq_core import Cell

    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot()
    recipient = deal.buyer_address if recipient_role == "buyer" else deal.seller_address
    proof = _outbound_retry_proof(
        deal, kind=kind, query_id=42, recipient=recipient,
        retry_window_seconds=window,
    )

    prepared = await adapter.prepare_transaction(
        EscrowWalletAction.RETRY_FAILED_OUTBOUND_ACTION,
        actor_wallet=wallet(recipient),  # type: ignore[arg-type]
        resource_id="deal-1",
        deal_snapshot=deal,
        query_id=42,
        retry_proof=proof,
        valid_until=1_800_000_000,
    )

    assert prepared.network == "-3"
    assert prepared.messages[0].address == derive_deployment(load_pinned_code_boc(), deal).address
    assert prepared.messages[0].amount == str(deal.action_value_nanotons)
    assert prepared.messages[0].payload is not None
    body = Cell.one_from_boc(base64.b64decode(prepared.messages[0].payload)).begin_parse()
    assert body.load_uint(32) == 0x56450009
    assert body.load_uint(64) == 42
    assert body.load_uint(256) == int(deal.deal_salt, 16)
    assert body.remaining_bits == 0
    assert body.remaining_refs == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("proof_changes", "query_id", "wallet_address", "message"),
    [
        ({"retry_window_seconds": 0}, 42, None, "not uniquely retryable"),
        ({"kind": 6, "retry_window_seconds": 1800}, 42, None, "not uniquely retryable"),
        ({"kind": 7, "retry_window_seconds": 1}, 42, None, "not uniquely retryable"),
        ({"status": 0}, 42, None, "not uniquely retryable"),
        ({"amount_nanotons": 0}, 42, None, "not uniquely retryable"),
        ({}, 43, None, "not uniquely retryable"),
        ({}, 42, "0:" + "55" * 32, "exact snapshotted outbound recipient"),
    ],
)
async def test_retry_failed_outbound_action_rejects_invalid_descriptor_or_recipient(
    proof_changes: dict[str, object],
    query_id: int,
    wallet_address: str | None,
    message: str,
) -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot()
    proof = _outbound_retry_proof(deal, **proof_changes)
    actor_address = wallet_address or proof.action.recipient_address

    with pytest.raises(EscrowContractABIUnavailable, match=message):
        await adapter.prepare_transaction(
            EscrowWalletAction.RETRY_FAILED_OUTBOUND_ACTION,
            actor_wallet=wallet(actor_address),  # type: ignore[arg-type]
            resource_id="deal-1",
            deal_snapshot=deal,
            query_id=query_id,
            retry_proof=proof,
            valid_until=1_800_000_000,
        )


@pytest.mark.asyncio
async def test_retry_failed_outbound_action_rejects_invalid_proof_anchor() -> None:
    adapter = PinnedTONEscrowContractAdapter()
    deal = snapshot()
    proof = replace(
        _outbound_retry_proof(deal),
        masterchain_block_hash="not-a-hash",
    )

    with pytest.raises(EscrowContractABIUnavailable, match="proof anchor is invalid"):
        await adapter.prepare_transaction(
            EscrowWalletAction.RETRY_FAILED_OUTBOUND_ACTION,
            actor_wallet=wallet(deal.buyer_address),  # type: ignore[arg-type]
            resource_id="deal-1",
            deal_snapshot=deal,
            query_id=42,
            retry_proof=proof,
            valid_until=1_800_000_000,
        )
