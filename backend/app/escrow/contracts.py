"""Semantic TON escrow wallet actions; ABI payload generation remains disabled."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.db.models import Wallet


class EscrowContractABIUnavailable(RuntimeError):
    """ABI is not versioned/approved, so no message may be constructed."""


class EscrowWalletAction(StrEnum):
    CREATE_DEAL_ESCROW = "create_deal_escrow"
    DEPOSIT_NFT = "deposit_nft"
    FUND_DEAL = "fund_deal"
    ACCEPT_DEAL = "accept_deal"
    OPEN_DISPUTE = "open_dispute"
    RETURN_NFT_TO_ESCROW = "return_nft_to_escrow"
    REFUND = "refund"
    PAYOUT = "payout"
    WITHDRAW_UNSOLD_NFT = "withdraw_unsold_nft"


@dataclass(frozen=True, slots=True)
class DealEscrowDeploymentSnapshot:
    """Immutable per-deal inputs; not a TON payload or opcode definition."""

    network: str
    listing_key: str
    seller_address: str
    buyer_address: str
    collection_address: str
    item_address: str
    principal_nanotons: int
    deal_salt: str


@dataclass(frozen=True, slots=True)
class TONConnectMessage:
    address: str
    amount: str
    payload: str | None = None


@dataclass(frozen=True, slots=True)
class TONConnectTransactionPayload:
    network: str
    valid_until: int
    messages: tuple[TONConnectMessage, ...]
    abi_version: str


class TONEscrowContractAdapter(Protocol):
    @property
    def abi_version(self) -> str | None: ...
    async def prepare_transaction(self, action: EscrowWalletAction, *,
        actor_wallet: Wallet, resource_id: str,
        deal_snapshot: DealEscrowDeploymentSnapshot) -> TONConnectTransactionPayload: ...


class UnconfiguredTONEscrowContractAdapter:
    @property
    def abi_version(self) -> str | None:
        return None

    async def prepare_transaction(self, action: EscrowWalletAction, *,
        actor_wallet: Wallet, resource_id: str,
        deal_snapshot: DealEscrowDeploymentSnapshot) -> TONConnectTransactionPayload:
        del action, actor_wallet, resource_id, deal_snapshot
        raise EscrowContractABIUnavailable(
            "TON escrow transaction construction is disabled until the contract ABI is approved"
        )
