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
    REFUND = "refund"
    PAYOUT = "payout"
    WITHDRAW_UNSOLD_NFT = "withdraw_unsold_nft"


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
        actor_wallet: Wallet, resource_id: str) -> TONConnectTransactionPayload: ...


class UnconfiguredTONEscrowContractAdapter:
    @property
    def abi_version(self) -> str | None:
        return None

    async def prepare_transaction(self, action: EscrowWalletAction, *,
        actor_wallet: Wallet, resource_id: str) -> TONConnectTransactionPayload:
        del action, actor_wallet, resource_id
        raise EscrowContractABIUnavailable(
            "TON escrow transaction construction is disabled until the contract ABI is approved"
        )
