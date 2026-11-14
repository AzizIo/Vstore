"""Typed TON escrow contract boundary.

The actual contract ABI is not approved. No opcodes, cells or message layouts are
implemented here; the default adapter refuses to fabricate a wallet transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.db.models import Wallet


class EscrowContractABIUnavailable(RuntimeError):
    """Raised until maintainers and smart-contract owners approve a versioned ABI."""


class EscrowWalletAction(StrEnum):
    DEPLOY_LISTING = "deploy_listing"
    FUND_DEAL = "fund_deal"
    ACCEPT_RECEIPT = "accept_receipt"
    OPEN_DISPUTE = "open_dispute"
    PREPARE_WITHDRAWAL = "prepare_withdrawal"


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
    """A future adapter must create unsigned requests only; it never signs them."""

    @property
    def abi_version(self) -> str | None: ...

    async def prepare_transaction(
        self,
        action: EscrowWalletAction,
        *,
        actor_wallet: Wallet,
        resource_id: str,
    ) -> TONConnectTransactionPayload: ...


class UnconfiguredTONEscrowContractAdapter:
    """Safe default while contract ABI, code hash and message layouts are unapproved."""

    @property
    def abi_version(self) -> str | None:
        return None

    async def prepare_transaction(
        self,
        action: EscrowWalletAction,
        *,
        actor_wallet: Wallet,
        resource_id: str,
    ) -> TONConnectTransactionPayload:
        del action, actor_wallet, resource_id
        raise EscrowContractABIUnavailable(
            "TON escrow transaction construction is disabled until the contract ABI is approved"
        )
