"""Typed transport contracts shared with the isolated frontend escrow workspace."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EscrowListingIntentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID
    seller_wallet_id: UUID
    price_nano: str = Field(pattern=r"^[1-9][0-9]*$", min_length=1, max_length=30)


class EscrowDealCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    listing_id: UUID
    buyer_wallet_id: UUID


class EscrowDisputeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: Literal["not_received", "wrong_asset", "payment_mismatch", "other"]
    reason: str = Field(min_length=5, max_length=2000)


class EscrowWithdrawalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wallet_id: UUID


class EscrowNftProjection(BaseModel):
    asset_id: UUID | None
    title: str
    image_url: str | None
    item_address: str
    collection_address: str | None


class EscrowListingIntentResponse(BaseModel):
    id: UUID
    listing_key: str | None
    seller_id: UUID
    state: Literal["intent_only", "active", "reserved", "cancelled", "manual_review"]
    network: Literal["testnet"]
    nft: EscrowNftProjection
    seller_wallet_address: str
    price_nano: str
    fee_bps: Literal[0] = 0
    available_actions: list[Literal["create_deal_intent", "cancel_listing_intent"]]
    created_at: datetime
    updated_at: datetime


class EscrowDealResponse(BaseModel):
    id: UUID
    listing_id: UUID
    listing_key: str
    buyer_id: UUID
    seller_id: UUID
    state: Literal[
        "intent_created", "awaiting_nft", "awaiting_buyer_funds", "funded_review",
        "nft_release_pending", "delivered_dispute_window", "disputed",
        "nft_return_pending", "seller_payout_pending", "buyer_refund_pending",
        "settled", "refunded", "expired", "manual_review"
    ]
    network: Literal["testnet"]
    nft: EscrowNftProjection
    escrow_address: str | None
    seller_wallet_address: str
    buyer_wallet_address: str
    price_nano: str
    fee_bps: Literal[0] = 0
    buyer_review_deadline: datetime | None
    dispute_deadline: datetime | None
    available_actions: list[Literal[
        "create_deal_escrow", "deposit_nft", "fund_deal", "accept_deal",
        "open_dispute", "return_nft_to_escrow", "withdraw_unsold_nft"
    ]]
    created_at: datetime
    updated_at: datetime
    dispute: dict | None = None


class EscrowPageResponse(BaseModel):
    items: list
    total: int
    next_cursor: str | None = None


class EscrowTransactionPreparationResponse(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    network: Literal["testnet"] = "testnet"
    payload: None = None
    reason_code: Literal["contract_abi_pending"] = "contract_abi_pending"
    detail: str = "Unsigned TON Connect payload is unavailable until ABI/API review is approved."


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
    deal_id: UUID
    kind: Literal["unsold_nft"] = "unsold_nft"
    status: Literal["prepared", "submitted", "observing", "confirmed", "failed", "manual_review"]
    destination_address: str | None
    transaction_hash: str | None
    created_at: datetime
    updated_at: datetime


class EscrowWalletReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: UUID
    action: Literal[
        "create_deal_escrow", "deposit_nft", "fund_deal", "accept_deal",
        "open_dispute", "return_nft_to_escrow", "withdraw_unsold_nft"
    ]
    reference: str = Field(min_length=1, max_length=512)
