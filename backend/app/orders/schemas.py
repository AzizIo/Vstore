from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    AssetType,
    OrderDeliveryAttemptStatus,
    OrderStatus,
    PriceCurrency,
)


class OrderEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: OrderStatus | None
    to_status: OrderStatus
    actor_type: str
    created_at: datetime


class OrderCreateRequest(BaseModel):
    listing_id: UUID


class OrderResponse(BaseModel):
    id: UUID
    listing_id: UUID
    buyer_id: UUID
    seller_id: UUID
    status: OrderStatus
    price_amount: Decimal
    price_currency: PriceCurrency
    title: str | None
    asset_name: str | None
    asset_type: AssetType
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    events: list[OrderEventResponse]


class OrderListResponse(BaseModel):
    items: list[OrderResponse]


class DeliveryPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seller_wallet_id: UUID


class DeliverySubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_hash: str = Field(min_length=1, max_length=128)


class DeliveryAttemptResponse(BaseModel):
    id: UUID
    status: OrderDeliveryAttemptStatus
    network: str
    item_address: str
    seller_address: str
    buyer_address: str
    query_id: str
    prepared_at: datetime
    deadline: datetime
    submitted_at: datetime | None
    candidate_transaction_hash: str | None
    transaction_hash: str | None
    trace_id: str | None
    masterchain_seqno: int | None
    verified_at: datetime | None


class OrderDeliveryStateResponse(BaseModel):
    order_id: UUID
    order_status: OrderStatus
    attempt: DeliveryAttemptResponse | None
