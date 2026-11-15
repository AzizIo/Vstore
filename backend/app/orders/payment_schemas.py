# isort: skip_file
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


PaymentPublicStatus = Literal[
    "not_started",
    "pending",
    "paid",
    "refund_pending",
    "refunded",
    "failed",
    "expired",
    "unsupported",
]
RefundPublicStatus = Literal[
    "none",
    "pending",
    "processing",
    "reconciliation_required",
    "manual_review",
    "succeeded",
]


class PaymentIntentCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    payment_intent_id: UUID
    payment_status: Literal[
        "pending", "paid", "refund_pending", "refunded", "failed", "expired"
    ]
    provider: Literal["telegram_stars"] = "telegram_stars"
    amount: Decimal = Field(gt=0)
    currency: Literal["XTR"] = "XTR"
    expires_at: datetime
    checkout_url: str | None = None
    last_error_code: str | None = None


class PaymentStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    payment_intent_id: UUID | None
    payment_status: PaymentPublicStatus
    provider: Literal["telegram_stars"] | None
    amount: Decimal = Field(gt=0)
    currency: str
    expires_at: datetime
    paid_at: datetime | None = None
    refunded_at: datetime | None = None
    refund_status: RefundPublicStatus = "none"
    last_error_code: str | None = None
