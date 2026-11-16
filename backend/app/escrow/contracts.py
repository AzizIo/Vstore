"""TON escrow wallet payloads, backed by the pinned DealEscrow ABI."""
from __future__ import annotations

import re
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
    load_pinned_code_boc,
    parse_basechain_address,
    validate_snapshot,
    verify_compiled_code,
)


class EscrowContractABIUnavailable(RuntimeError):
    """Pinned ABI/code artifact is absent or a requested action is not safe."""


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
    RETRY_FAILED_OUTBOUND_ACTION = "retry_failed_outbound_action"
    # Kept for backwards compatibility, but these are not user wallet actions.
    REFUND = "refund"
    PAYOUT = "payout"
    WITHDRAW_UNSOLD_NFT = "withdraw_unsold_nft"


@dataclass(frozen=True, slots=True)
class DealEscrowDeploymentSnapshot:
    """Immutable ABI terms plus getter state observed at a finalized chain position."""

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
    observed_chain_time_unix: int
    dispute_phase: int
    nft_in_escrow: bool
    principal_locked: bool
    recovery_previous_owner: str | None = None
    recovery_item_address: str | None = None


@dataclass(frozen=True, slots=True)
class ProofBoundOutboundAction:
    slot: str
    kind: int
    query_id: int
    deal_salt: str
    attempt_id: int
    amount_nanotons: int
    message_value_nanotons: int
    expected_state: int
    expected_pending_action: int
    retry_window_seconds: int
    message_body_hash: str
    status: int
    bounce_phase: int
    exit_code: int
    item_address: str
    destination_address: str
    recipient_address: str
    response_address: str


@dataclass(frozen=True, slots=True)
class OutboundRetryProof:
    action: ProofBoundOutboundAction
    masterchain_seqno: int
    masterchain_block_hash: str
    state_data_hash: str
    provider_id: str


@dataclass(frozen=True, slots=True)
class TONConnectMessage:
    address: str
    amount: str
    payload: str | None = None
    state_init: str | None = None

    def to_tonconnect_dict(self) -> dict[str, str]:
        value = {"address": self.address, "amount": self.amount}
        if self.payload is not None:
            value["payload"] = self.payload
        if self.state_init is not None:
            value["stateInit"] = self.state_init
        return value


@dataclass(frozen=True, slots=True)
class TONConnectTransactionPayload:
    network: str
    valid_until: int
    messages: tuple[TONConnectMessage, ...]
    abi_version: str

    def to_tonconnect_dict(self) -> dict[str, object]:
        return {
            "network": self.network,
            "validUntil": self.valid_until,
            "messages": [message.to_tonconnect_dict() for message in self.messages],
        }


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
        retry_proof: OutboundRetryProof | None = None,
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
        retry_proof: OutboundRetryProof | None = None,
    ) -> TONConnectTransactionPayload:
        del action, actor_wallet, resource_id, deal_snapshot, reason_hash, query_id, valid_until, retry_proof
        raise EscrowContractABIUnavailable(
            "TON escrow transaction construction is disabled until ABI/code artifacts "
            "are configured"
        )


class PinnedTONEscrowContractAdapter:
    """Build unsigned TON Connect testnet messages; never signs or submits them."""

    def __init__(self, *, compiled_code_boc_base64: str | None = None) -> None:
        try:
            self._compiled_code_boc_base64 = compiled_code_boc_base64 or load_pinned_code_boc()
            self._artifacts = verify_compiled_code(self._compiled_code_boc_base64)
        except TONABIError as exc:
            raise EscrowContractABIUnavailable(str(exc)) from exc

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
        retry_proof: OutboundRetryProof | None = None,
    ) -> TONConnectTransactionPayload:
        if not resource_id or len(resource_id) > 128:
            raise EscrowContractABIUnavailable("resource_id is required and must be bounded")
        try:
            seller, buyer, _collection, item, salt = validate_snapshot(deal_snapshot)
            deployment = derive_deployment(self._compiled_code_boc_base64, deal_snapshot)
            wallet_address = parse_basechain_address(actor_wallet.address, "actor_wallet.address")
        except (TONABIError, AttributeError) as exc:
            raise EscrowContractABIUnavailable(str(exc)) from exc
        if actor_wallet.network != "testnet" or not actor_wallet.is_verified:
            raise EscrowContractABIUnavailable("a verified TON testnet wallet is required")
        if wallet_address != seller and wallet_address != buyer:
            raise EscrowContractABIUnavailable("wallet is not a snapshotted deal participant")

        state = deal_snapshot.contract_state
        deadline = deal_snapshot.deadline_unix
        chain_time = deal_snapshot.observed_chain_time_unix
        if isinstance(state, bool) or not isinstance(state, int) or not 0 <= state <= 13:
            raise EscrowContractABIUnavailable("contract_state must be a known DealEscrow state")
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0
               for v in (deadline, chain_time)):
            raise EscrowContractABIUnavailable("chain deadline/time snapshot is invalid")
        if valid_until is None:
            valid_until = int(time.time()) + 300
        if (
            isinstance(valid_until, bool)
            or not isinstance(valid_until, int)
            or valid_until <= int(time.time())
        ):
            raise EscrowContractABIUnavailable(
                "valid_until must be a future Unix timestamp"
            )
        escrow_address = deployment.address
        is_seller = wallet_address == seller
        is_buyer = wallet_address == buyer
        target: str
        amount: int
        body: str | None = None
        state_init: str | None = None

        def require_query_id() -> int:
            if query_id is None:
                raise TONABIError("query_id is required for this operation")
            if (
                isinstance(query_id, bool)
                or not isinstance(query_id, int)
                or not 0 < query_id < (1 << 64)
            ):
                raise TONABIError("query_id must be a non-zero uint64")
            return query_id

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
                body = encode_simple_action(
                    "activate_deal", deal_snapshot.activation_query_id, salt
                )
            elif action is EscrowWalletAction.DEPOSIT_NFT:
                if not is_seller or state != 1 or deal_snapshot.nft_in_escrow:
                    raise TONABIError("NFT deposit is available only to the seller in awaiting_nft")
                if chain_time > deadline:
                    raise TONABIError("seller NFT deposit window has expired")
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
                    raise TONABIError("funding requires the bound buyer and accepted NFT deposit")
                if chain_time > deadline or deal_snapshot.principal_locked:
                    raise TONABIError("funding window expired or principal is already locked")
                target = escrow_address
                amount = deal_snapshot.principal_nanotons + deal_snapshot.execution_reserve_nanotons
                body = encode_simple_action("fund_deal", deal_snapshot.fund_query_id, salt)
            elif action is EscrowWalletAction.ACCEPT_DEAL:
                if (
                    not is_buyer or state != 3 or not deal_snapshot.nft_in_escrow
                    or not deal_snapshot.principal_locked or chain_time > deadline
                ):
                    raise TONABIError("acceptance requires the live funded buyer-review state")
                target = escrow_address
                amount = deal_snapshot.action_value_nanotons
                body = encode_simple_action("accept_deal", deal_snapshot.nft_release_query_id, salt)
            elif action is EscrowWalletAction.OPEN_DISPUTE:
                if not is_buyer or state not in {3, 5} or chain_time > deadline:
                    raise TONABIError(
                    "only the buyer may dispute a live funded-review or post-delivery state"
                )
                if reason_hash is None:
                    raise TONABIError("reason_hash is required for an on-chain dispute")
                target = escrow_address
                amount = deal_snapshot.action_value_nanotons
                body = encode_dispute_action(require_query_id(), salt, reason_hash)
            elif action is EscrowWalletAction.RETURN_NFT_TO_ESCROW:
                if (
                    not is_buyer or state != 6 or deal_snapshot.dispute_phase != 2
                    or deal_snapshot.nft_in_escrow or chain_time > deadline
                ):
                    raise TONABIError(
                        "NFT return requires a live post-delivery dispute and buyer ownership"
                    )
                target = item.to_str(is_user_friendly=False)
                amount = deal_snapshot.nft_return_value_nanotons
                body = encode_nft_transfer(
                    query_id=deal_snapshot.nft_return_to_escrow_query_id,
                    new_owner=escrow_address,
                    response_destination=deal_snapshot.buyer_address,
                    deal_salt=salt,
                )
            elif action is EscrowWalletAction.TIMEOUT_DEAL:
                if (
                    not (is_buyer or is_seller)
                    or state not in {1, 2, 3, 5}
                    or deadline == 0
                    or chain_time <= deadline
                ):
                    raise TONABIError(
                        "timeout requires a participant and an expired supported state"
                    )
                target = escrow_address
                amount = deal_snapshot.action_value_nanotons
                body = encode_simple_action("timeout_deal", require_query_id(), salt)
            elif action is EscrowWalletAction.RECOVER_UNEXPECTED_NFT:
                if (
                    state != 13 or not deal_snapshot.nft_in_escrow
                    or not deal_snapshot.recovery_previous_owner
                    or not deal_snapshot.recovery_item_address
                ):
                    raise TONABIError(
                        "unexpected NFT recovery requires a manual-review recovery record"
                    )
                previous_owner = parse_basechain_address(
                    deal_snapshot.recovery_previous_owner, "recovery_previous_owner"
                )
                if wallet_address != previous_owner:
                    raise TONABIError("only the recorded previous NFT owner may recover this item")
                # RecoverUnexpectedNft is handled by DealEscrow itself. The
                # contract then sends the unexpected NFT to the snapshotted
                # previous owner; sending this opcode to the NFT item is invalid.
                target = escrow_address
                amount = deal_snapshot.action_value_nanotons
                body = encode_simple_action("recover_unexpected_nft", require_query_id(), salt)
            elif action is EscrowWalletAction.RETRY_FAILED_OUTBOUND_ACTION:
                if retry_proof is None:
                    raise TONABIError("a current trust-level-0 outbound retry proof is required")
                descriptor = retry_proof.action
                retry_query_id = require_query_id()
                if (
                    retry_proof.provider_id != "pytoniq-trust0-testnet-v1"
                    or isinstance(retry_proof.masterchain_seqno, bool)
                    or not isinstance(retry_proof.masterchain_seqno, int)
                    or retry_proof.masterchain_seqno <= 0
                    or not re.fullmatch(r"[0-9a-f]{64}", retry_proof.masterchain_block_hash)
                    or not re.fullmatch(r"[0-9a-f]{64}", retry_proof.state_data_hash)
                ):
                    raise TONABIError("outbound retry proof anchor is invalid")
                valid_retry_window = (
                    descriptor.kind in {1, 2, 3, 4, 5}
                    and descriptor.retry_window_seconds == 1800
                ) or (
                    descriptor.kind in {6, 7}
                    and descriptor.retry_window_seconds == 0
                )
                valid_amounts = (
                    descriptor.kind == 7
                    and descriptor.amount_nanotons == 0
                    and descriptor.message_value_nanotons == 0
                ) or (
                    descriptor.kind in {1, 2, 3, 4, 5, 6}
                    and descriptor.amount_nanotons > 0
                    and descriptor.message_value_nanotons > 0
                )
                if (
                    descriptor.slot not in {"first", "second"}
                    or descriptor.kind not in {1, 2, 3, 4, 5, 6, 7}
                    or descriptor.query_id != retry_query_id
                    or descriptor.deal_salt != f"{salt:064x}"
                    or descriptor.attempt_id <= 0
                    or descriptor.status != 1
                    or not valid_retry_window
                    or not valid_amounts
                    or not re.fullmatch(r"[0-9a-f]{64}", descriptor.message_body_hash)
                    or not 0 <= descriptor.expected_state <= 13
                    or not 0 <= descriptor.expected_pending_action <= 255
                    or descriptor.bounce_phase not in {1, 2}
                ):
                    raise TONABIError("outbound descriptor is not uniquely retryable")
                recipient = parse_basechain_address(
                    descriptor.recipient_address, "outbound recipient_address"
                )
                if recipient.to_str(is_user_friendly=False) != wallet_address.to_str(is_user_friendly=False):
                    raise TONABIError("only the exact snapshotted outbound recipient may retry")
                if deal_snapshot.action_value_nanotons <= 0:
                    raise TONABIError("retry action value must be positive")
                target = escrow_address
                amount = deal_snapshot.action_value_nanotons
                body = encode_simple_action(
                    "retry_failed_outbound_action", retry_query_id, salt
                )
            else:
                raise TONABIError(
                    "refund/payout are contract-initiated; this wallet action is not supported"
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
