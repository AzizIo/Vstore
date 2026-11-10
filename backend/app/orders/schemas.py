from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.db.models import AssetType, OrderStatus


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
    title: str | None
    asset_name: str | None
    asset_type: AssetType
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    events: list[OrderEventResponse]


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
