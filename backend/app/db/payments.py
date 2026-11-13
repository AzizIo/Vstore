from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.models import Base, TimestampMixin


class PaymentIntent(TimestampMixin, Base):
    """One immutable-price Telegram Stars payment attempt for an order."""

    __tablename__ = "payment_intents"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_intents_amount_positive"),
        CheckConstraint("currency = 'XTR'", name="ck_payment_intents_currency_stars"),
        CheckConstraint(
            "provider = 'telegram_stars'", name="ck_payment_intents_provider"
        ),
        CheckConstraint(
            "status IN ('pending', 'paid', 'refund_pending', 'refunded', 'failed', 'expired')",
            name="ck_payment_intents_status",
        ),
        CheckConstraint(
            "payer_telegram_id > 0", name="ck_payment_intents_payer_positive"
        ),
        UniqueConstraint("order_id", name="uq_payment_intents_order"),
        UniqueConstraint("invoice_payload", name="uq_payment_intents_invoice_payload"),
        UniqueConstraint(
            "telegram_payment_charge_id",
            name="uq_payment_intents_telegram_charge",
        ),
        UniqueConstraint(
            "provider_payment_charge_id",
            name="uq_payment_intents_provider_charge",
        ),
        Index("ix_payment_intents_status_expires", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="telegram_stars", server_default="telegram_stars"
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 9), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="XTR", server_default="XTR"
    )
    payer_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invoice_payload: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(String(128))
    provider_payment_charge_id: Mapped[str | None] = mapped_column(String(128))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))


class PaymentEvent(Base):
    """Append-only, deduplicated record of provider events; never stores raw updates."""

    __tablename__ = "payment_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('intent_created', 'pre_checkout_accepted', "
            "'payment_succeeded', 'payment_rejected', 'refund_requested', "
            "'refund_succeeded', 'refund_failed')",
            name="ck_payment_events_event_type",
        ),
        CheckConstraint(
            "length(provider_event_id) BETWEEN 1 AND 128",
            name="ck_payment_events_provider_event_id",
        ),
        CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_payment_events_payload_sha256",
        ),
        UniqueConstraint(
            "provider", "provider_event_id", name="uq_payment_events_provider_event"
        ),
        Index("ix_payment_events_intent_created", "payment_intent_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payment_intents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="telegram_stars", server_default="telegram_stars"
    )
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
