"""TON escrow wallet payloads, backed by the pinned DealEscrow ABI."""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.db.models import Wallet
from app.escrow.ton_abi import (
    TONABIError,
    derive_deployment,
    encode_dispute_action,
    encode_nft_transfer,
    encode_simple_action,
    parse_basechain_address,
    validate_snapshot,
    verify_compiled_code,
)


class EscrowContractABIUnavailable(RuntimeError):
    """Pinned ABI/code artifact is absent or cannot be verified."""


class EscrowWalletAction(StrEnum):
    CREATE_DEAL_ESCROW = "create_deal_escrow"
    ACTIVATE_DEAL = "activate_deal"
    DEPOSIT_NFT = "deposit_nft"
    FUND_DEAL = "fund_deal"
    ACCEPT_DEAL = "accept_deal"
    OPEN_DISPUTE = "open_dispute"
    RETURN_NFT_TO_ESCROW = "return_nft_to_escrow"
    TIMEOUT_DEAL = "timeout_deal"
    RECOVER_UNEXPECTED_NFT = "recover_unexpected_nft"
    # These are contract-initiated or not part of the wallet ABI. They remain
    # here only to make old callers fail explicitly instead of guessing.
    REFUND = "refund"
    PAYOUT = "payout"
    WITHDRAW_UNSOLD_NFT = "withdraw_unsold_nft"


@dataclass(frozen=True, slots=True)
class DealEscrowDeploymentSnapshot:
    """Immutable deployment terms plus separately observed current getter state."""

    network: str
    network_id: int
    protocol_version: int
    listing_key: str
    seller_address: str
    buyer_address: str
    collection_address: str
    item_address: str
    principal_nanotons: int
    execution_reserve_nanotons: int
    seller_deployment_refund_nanotons: int
    nft_transfer_value_nanotons: int
    deal_salt: str
    activation_query_id: int
    fund_query_id: int
    nft_deposit_query_id: int
    nft_release_query_id: int
    nft_return_to_escrow_query_id: int
    oracle_key_a: int
    oracle_key_b: int
    oracle_key_c: int
    resolver_key_a: int
    resolver_key_b: int
    resolver_key_c: int
    deployment_value_nanotons: int
    activation_value_nanotons: int
    action_value_nanotons: int
    nft_deposit_value_nanotons: int
    nft_return_value_nanotons: int
    contract_state: int
    deadline_unix: int
    dispute_phase: int
    nft_in_escrow: bool
    principal_locked: bool
    recovery_previous_owner: str | None = None


@dataclass(frozen=True, slots=True)
class TONConnectMessage:
    address: str
    amount: str
    payload: str | None = None
    state_init: str | None = None


@dataclass(frozen=True, slots=True)
class TONConnectTransactionPayload:
    network: str
    valid_until: int
    messages: tuple[TONConnectMessage, ...]
    abi_version: str


class TONEscrowContractAdapter(Protocol):
    @property
    def abi_version(self) -> str | None: ...
    async def prepare_transaction(
        self,
        action: EscrowWalletAction,
        *,
        actor_wallet: Wallet,
        resource_id: str,
        deal_snapshot: DealEscrowDeploymentSnapshot,
        reason_hash: int | None = None,
        query_id: int | None = None,
        valid_until: int | None = None,
    ) -> TONConnectTransactionPayload: ...


class UnconfiguredTONEscrowContractAdapter:
    @property
    def abi_version(self) -> str | None:
        return None

    async def prepare_transaction(
        self,
        action: EscrowWalletAction,
        *,
        actor_wallet: Wallet,
        resource_id: str,
        deal_snapshot: DealEscrowDeploymentSnapshot,
        reason_hash: int | None = None,
        query_id: int | None = None,
        valid_until: int | None = None,
    ) -> TONConnectTransactionPayload:
        del action, actor_wallet, resource_id, deal_snapshot, reason_hash, query_id, valid_until
        raise EscrowContractABIUnavailable(
            "TON escrow transaction construction is disabled until ABI/code artifacts are configured"
        )


class PinnedTONEscrowContractAdapter:
    """Build unsigned TON Connect testnet messages; never signs or submits them."""

    def __init__(self, *, compiled_code_boc_base64: str) -> None:
        try:
            self._artifacts = verify_compiled_code(compiled_code_boc_base64)
        except TONABIError as exc:
            raise EscrowContractABIUnavailable(str(exc)) from exc
        self._code_boc_base64 = compiled_code_boc_base64

    @property
    def abi_version(self) -> str | None:
        return self._artifacts.abi_version

    async def prepare_transaction(
        self,
        action: EscrowWalletAction,
        *,
        actor_wallet: Wallet,
        resource_id: str,
        deal_snapshot: DealEscrowDeploymentSnapshot,
        reason_hash: int | None = None,
        query_id: int | None = None,
        valid_until: int | None = None,
    ) -> TONConnectTransactionPayload:
        if not resource_id or len(resource_id) > 128:
            raise EscrowContractABIUnavailable("resource_id is required and must be bounded")
        try:
            seller, buyer, _collection, item, salt = validate_snapshot(deal_snapshot)
            deployment = derive_deployment(self._code_boc_base64, deal_snapshot)
            wallet_address = parse_basechain_address(actor_wallet.address, "actor_wallet.address")
        except (TONABIError, AttributeError) as exc:
            raise EscrowContractABIUnavailable(str(exc)) from exc
        if actor_wallet.network != "testnet" or not actor_wallet.is_verified:
            raise EscrowContractABIUnavailable("a verified TON testnet wallet is required")
        if wallet_address != seller and wallet_address != buyer:
            raise EscrowContractABIUnavailable("wallet is not a snapshotted deal participant")

        state = deal_snapshot.contract_state
        deadline = deal_snapshot.deadline_unix
        if isinstance(state, bool) or not isinstance(state, int) or not 0 <= state <= 13:
            raise EscrowContractABIUnavailable("contract_state must be a known DealEscrow state")
        if isinstance(deadline, bool) or not isinstance(deadline, int) or deadline < 0:
            raise EscrowContractABIUnavailable("deadline_unix is invalid")
        if valid_until is None:
            valid_until = int(time.time()) + 300
        if isinstance(valid_until, bool) or not isinstance(valid_until, int) or valid_until <= int(time.time()):
            raise EscrowContractABIUnavailable("valid_until must be a future Unix timestamp")
        escrow_address = deployment.address
        is_seller = wallet_address == seller
        is_buyer = wallet_address == buyer
        target: str
        amount: int
        body: str | None = None
        state_init: str | None = None

        try:
            if action is EscrowWalletAction.CREATE_DEAL_ESCROW:
                if not is_seller or state != 0:
                    raise TONABIError("only the seller may deploy a new intent-created deal")
                target = escrow_address
                amount = deal_snapshot.deployment_value_nanotons
                state_init = deployment.state_init_boc
            elif action is EscrowWalletAction.ACTIVATE_DEAL:
                if not is_seller or state != 0:
                    raise TONABIError("only the seller may activate an intent-created deal")
                target = escrow_address
                amount = deal_snapshot.activation_value_nanotons
                body = encode_simple_action("activate_deal", deal_snapshot.activation_query_id, salt)
            elif action is EscrowWalletAction.DEPOSIT_NFT:
                if not is_seller or state != 1 or deal_snapshot.nft_in_escrow:
                    raise TONABIError("NFT deposit is available only to the seller in awaiting_nft")
                target = item.to_str(is_user_friendly=False)
                amount = deal_snapshot.nft_deposit_value_nanotons
                body = encode_nft_transfer(
                    query_id=deal_snapshot.nft_deposit_query_id,
                    new_owner=escrow_address,
                    response_destination=deal_snapshot.seller_address,
                    deal_salt=salt,
                )
            elif action is EscrowWalletAction.FUND_DEAL:
                if not is_buyer or state != 2 or not deal_snapshot.nft_in_escrow:
                    raise TONABIError("funding requires the bound buyer and an accepted NFT deposit")
                target = escrow_address
                amount = deal_snapshot.principal_nanotons + deal_snapshot.execution_reserve_nanotons
                body = encode_simple_action("fund_deal", deal_snapshot.fund_query_id, salt)
            elif action is EscrowWalletAction.ACCEPT_DEAL:
                if (
                    not is_buyer or state != 3 or not deal_snapshot.nft_in_escrow
                    or not deal_snapshot.principal_locked
                ):
                    raise TONABIError("acceptance requires the funded buyer-review state")
                target = escrow_address
                amount = deal_snapshot.action_value_nanotons
                body = encode_simple_action("accept_deal", deal_snapshot.nft_release_query_id, salt)
            elif action is EscrowWalletAction.OPEN_DISPUTE:
                if not is_buyer or state not in {3, 5}:
                    raise TONABIError("only the buyer may dispute funded-review or post-delivery state")
                if reason_hash is None:
                    raise TONABIError("reason_hash is required for an on-chain dispute")
                target = escrow_address
                amount = deal_snapshot.action_value_nanotons
                body = encode_dispute_action(
                    query_id or deal_snapshot.action_value_nanotons, salt, reason_hash
                )
            elif action is EscrowWalletAction.RETURN_NFT_TO_ESCROW:
                if (
                    not is_buyer or state != 6 or deal_snapshot.dispute_phase != 2
                    or deal_snapshot.nft_in_escrow
                ):
                    raise TONABIError("NFT return requires a post-delivery dispute and buyer ownership")
                target = item.to_str(is_user_friendly=False)
                amount = deal_snapshot.nft_return_value_nanotons
                body = encode_nft_transfer(
                    query_id=deal_snapshot.nft_return_to_escrow_query_id,
                    new_owner=escrow_address,
                    response_destination=deal_snapshot.buyer_address,
                    deal_salt=salt,
                )
            else:
                raise TONABIError(
                    "this operation is contract-initiated, unsupported by the frozen wallet ABI, or awaiting audit"
                )
        except TONABIError as exc:
            raise EscrowContractABIUnavailable(str(exc)) from exc

        if amount <= 0:
            raise EscrowContractABIUnavailable("wallet message amount must be positive")
        message = TONConnectMessage(
            address=target,
            amount=str(amount),
            payload=body,
            state_init=state_init,
        )
        return TONConnectTransactionPayload(
            network="-3",
            valid_until=valid_until,
            messages=(message,),
            abi_version=self.abi_version or "1.0.0",
        )
