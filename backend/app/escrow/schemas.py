"""Typed transport contracts shared with the isolated frontend escrow workspace."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


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
    reason: str = Field(min_length=5, max_length=2000)
    reason_code: Literal["not_received", "wrong_asset", "payment_mismatch", "other"] = "other"


class EscrowRetryFailedOutboundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Decimal string avoids JavaScript Number precision loss for uint64 query IDs.
    query_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$", min_length=1, max_length=20)

    @field_validator("query_id")
    @classmethod
    def validate_uint64_query_id(cls, value: str) -> str:
        if int(value) >= (1 << 64):
            raise ValueError("query_id must fit a non-zero uint64")
        return value


class EscrowRetryableOutboundActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$", min_length=1, max_length=20)
    slot: Literal["first", "second"]
    kind: int = Field(ge=1, le=7)
    recipient_address: str = Field(min_length=1, max_length=128)
    amount_nanotons: str = Field(pattern=r"^[1-9][0-9]*$")
    retry_window_seconds: int = Field(ge=0, le=4_294_967_295)
    proof_masterchain_seqno: int = Field(gt=0)

    @field_validator("query_id")
    @classmethod
    def validate_uint64_query_id(cls, value: str) -> str:
        if int(value) >= (1 << 64):
            raise ValueError("query_id must fit a non-zero uint64")
        return value

    @field_validator("amount_nanotons")
    @classmethod
    def validate_kind_specific_amount(cls, value: str, info: ValidationInfo) -> str:
        kind = info.data.get("kind")
        if kind == 7 and value == "0":
            return value
        if kind in {1, 2, 3, 4, 5, 6} and int(value) > 0:
            return value
        raise ValueError("amount_nanotons does not match the outbound action kind")

    @field_validator("retry_window_seconds")
    @classmethod
    def validate_kind_specific_retry_window(cls, value: int, info: ValidationInfo) -> int:
        kind = info.data.get("kind")
        if kind in {1, 2, 3, 4, 5} and value == 1800:
            return value
        if kind in {6, 7} and value == 0:
            return value
        raise ValueError("retry_window_seconds does not match the outbound action kind")


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


class EscrowDisputeProjection(BaseModel):
    id: UUID
    status: Literal["open", "under_review", "resolved_buyer", "resolved_seller"]
    reason_code: str
    summary: str | None
    opened_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


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
        "create_deal_escrow", "activate_deal", "deposit_nft", "fund_deal", "accept_deal",
        "open_dispute", "return_nft_to_escrow", "withdraw_unsold_nft",
        "retry_failed_outbound_action"
    ]]
    created_at: datetime
    updated_at: datetime
    dispute: EscrowDisputeProjection | None = None


class EscrowPageResponse(BaseModel):
    items: list
    total: int
    next_cursor: str | None = None


class EscrowTransactionPreparationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["prepared", "unavailable"] = "unavailable"
    network: Literal["testnet"] = "testnet"
    action_id: UUID | None = None
    payload: dict[str, object] | None = None
    payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    unsigned_boc_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason_code: str | None = None
    detail: str | None = None


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
        "open_dispute", "return_nft_to_escrow", "withdraw_unsold_nft",
        "retry_failed_outbound_action"
    ]
    reference: str = Field(min_length=1, max_length=512)


class EscrowWalletReferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: UUID
    status: Literal[
        "pending", "prepared", "submitted", "ambiguous",
        "finalized", "failed", "manual_review", "blocked_abi",
    ]
    reference_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconciliation_status: Literal[
        "awaiting_independent_chain_reconciliation",
        "already_finalized",
        "manual_review",
    ]
