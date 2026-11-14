"""Typed API schemas for escrow intents and verified chain projections."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EscrowListingIntentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_id: UUID
    seller_wallet_id: UUID


class EscrowDealCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_intent_id: UUID
    buyer_wallet_id: UUID


class EscrowDisputeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: Literal["not_received", "wrong_asset", "payment_mismatch", "other"]
    reason: str = Field(min_length=5, max_length=2000)


class EscrowWithdrawalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wallet_id: UUID


class EscrowListingIntentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    marketplace_listing_id: UUID
    seller_id: UUID
    network: str
    item_address: str
    seller_address_snapshot: str
    price_amount: Decimal
    price_currency: str
    status: str
    contract_address: str | None
    contract_abi_version: str | None
    created_at: datetime
    updated_at: datetime


class EscrowDealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    listing_intent_id: UUID
    marketplace_listing_id: UUID
    seller_id: UUID
    buyer_id: UUID
    network: str
    contract_address: str | None
    contract_abi_version: str | None
    item_address: str
    seller_address_snapshot: str
    buyer_address_snapshot: str
    price_amount: Decimal
    price_currency: str
    principal_nanotons: Decimal
    status: str
    last_chain_seqno: int | None
    created_at: datetime
    updated_at: datetime


class EscrowTransactionPreparationResponse(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    network: Literal["testnet"] = "testnet"
    payload: None = None
    reason_code: Literal["contract_abi_pending"] = "contract_abi_pending"
    detail: str = (
        "Unsigned transaction construction is disabled until contract ABI, "
        "code hash and message layouts are approved."
    )


class EscrowSellerBalanceResponse(BaseModel):
    network: Literal["testnet"] = "testnet"
    currency: Literal["TON"] = "TON"
    available_balance_nanotons: None = None
    available: Literal[False] = False
    reason_code: Literal["settlement_model_not_approved"] = "settlement_model_not_approved"


class EscrowDisputeResponse(BaseModel):
    id: UUID
    deal_id: UUID
    opened_by: UUID
    reason_code: str
    status: str
    onchain_confirmation_required: bool = True
    created_at: datetime


class EscrowWithdrawalResponse(BaseModel):
    id: UUID
    network: Literal["testnet"] = "testnet"
    recipient_address: str
    amount_nanotons: None = None
    status: Literal["blocked_abi_unavailable"] = "blocked_abi_unavailable"
    reason_code: Literal["contract_abi_pending"] = "contract_abi_pending"
    transaction_payload: None = None
    created_at: datetime
