import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

class PriceCurrency(str, enum.Enum):
    """Currency options reserved for a separately approved future payment phase."""

    TON = "TON"
    XTR = "XTR"


@dataclass(frozen=True)
class PaymentIntent:
    order_id: UUID
    amount: Decimal
    currency: PriceCurrency
    expires_at: datetime
    provider_reference: str


@dataclass(frozen=True)
class VerifiedPayment:
    order_id: UUID
    amount: Decimal
    currency: PriceCurrency
    provider_reference: str


class PaymentAdapter(Protocol):
    """Trusted server-side payment boundary; not wired to an active provider."""

    async def create_intent(self, order_id: UUID) -> PaymentIntent: ...

    async def verify_notification(self, payload: bytes, signature: str) -> VerifiedPayment: ...
