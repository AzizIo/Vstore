"""SQLAlchemy projection models for the isolated TON escrow domain.

These rows are durable intents and indexed evidence, not proof of chain ownership
or balances. Chain-derived states are advanced only by the escrow observer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.models import Listing, NFTAsset, TimestampMixin, User, Wallet


class EscrowBase(DeclarativeBase):
    """Keep escrow table metadata isolated from the marketplace model registry."""


class EscrowListingIntent(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_listing_intents"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_listing_network_testnet"),
        CheckConstraint("price_currency = 'TON'", name="ck_escrow_listing_currency_ton"),
        CheckConstraint("price_amount > 0", name="ck_escrow_listing_price_positive"),
        CheckConstraint(
            "status IN ('intent_only', 'active', 'reserved', 'cancelled', 'manual_review')",
            name="ck_escrow_listing_status",
        ),
        UniqueConstraint("seller_id", "idempotency_key", name="uq_escrow_listing_seller_idem"),
        Index(
            "uq_escrow_listing_open_market_listing",
            "marketplace_listing_id",
            unique=True,
            postgresql_where=text(
                "status IN ('intent_only', 'active', 'reserved', 'manual_review')"
            ),
        ),
        Index("ix_escrow_listing_seller_created", "seller_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    marketplace_listing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(Listing.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(NFTAsset.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    seller_wallet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(Wallet.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    item_address: Mapped[str] = mapped_column(String(128), nullable=False)
    listing_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    seller_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(24, 9), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(8), server_default="TON", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), server_default="intent_only", nullable=False
    )
    contract_address: Mapped[str | None] = mapped_column(String(128))
    contract_abi_version: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)


class EscrowDeal(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_deals"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_deal_network_testnet"),
        CheckConstraint("price_currency = 'TON'", name="ck_escrow_deal_currency_ton"),
        CheckConstraint("price_amount > 0", name="ck_escrow_deal_price_positive"),
        CheckConstraint("principal_nanotons > 0", name="ck_escrow_deal_principal_positive"),
        CheckConstraint(
            "status IN ('intent_created', 'awaiting_nft', 'awaiting_buyer_funds', "
            "'funded_review', 'nft_release_pending', 'delivered_dispute_window', 'disputed', "
            "'nft_return_pending', 'seller_payout_pending', 'buyer_refund_pending', "
            "'settled', 'refunded', 'expired', 'manual_review')",
            name="ck_escrow_deal_status",
        ),
        CheckConstraint("buyer_id <> seller_id", name="ck_escrow_deal_not_self_trade"),
        UniqueConstraint("buyer_id", "idempotency_key", name="uq_escrow_deal_buyer_idem"),
        Index(
            "uq_escrow_deal_open_listing_intent",
            "listing_intent_id",
            unique=True,
            postgresql_where=text(
                "status IN ('intent_created', 'awaiting_nft', 'awaiting_buyer_funds', "
                "'funded_review', 'nft_release_pending', 'delivered_dispute_window', "
                "'disputed', 'nft_return_pending', 'seller_payout_pending', "
                "'buyer_refund_pending', 'manual_review')"
            ),
        ),
        Index("ix_escrow_deal_buyer_created", "buyer_id", "created_at"),
        Index("ix_escrow_deal_seller_created", "seller_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("escrow_listing_intents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    marketplace_listing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    buyer_wallet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    deal_salt: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_address: Mapped[str | None] = mapped_column(String(128))
    contract_abi_version: Mapped[str | None] = mapped_column(String(64))
    item_address: Mapped[str] = mapped_column(String(128), nullable=False)
    seller_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    buyer_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(24, 9), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(8), server_default="TON", nullable=False)
    principal_nanotons: Mapped[Decimal] = mapped_column(Numeric(30, 0), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), server_default="intent_created", nullable=False
    )
    last_chain_seqno: Mapped[int | None] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)


class EscrowChainEvent(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_chain_events"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_event_network_testnet"),
        CheckConstraint("event_index >= 0", name="ck_escrow_event_index_nonnegative"),
        CheckConstraint(
            "status IN ('pending', 'applied', 'duplicate', 'rejected', 'manual_review', 'unmatched')",
            name="ck_escrow_event_status",
        ),
        CheckConstraint(
            "length(evidence_sha256) = 64", name="ck_escrow_event_evidence_hash"
        ),
        UniqueConstraint("network", "event_key", name="uq_escrow_chain_event_key"),
        Index("ix_escrow_chain_event_deal_created", "deal_id", "created_at"),
        Index("ix_escrow_chain_event_seqno", "network", "masterchain_seqno"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    event_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_hash: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[str | None] = mapped_column(String(128))
    logical_time: Mapped[int | None] = mapped_column(BigInteger)
    phase: Mapped[str | None] = mapped_column(String(32))
    attempt_id: Mapped[str | None] = mapped_column(String(128))
    query_id: Mapped[str | None] = mapped_column(String(128))
    operation_id: Mapped[str | None] = mapped_column(String(128))
    deal_salt: Mapped[str | None] = mapped_column(String(128))
    account_address: Mapped[str | None] = mapped_column(String(128))
    observed_contract_state: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_address: Mapped[str] = mapped_column(String(128), nullable=False)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("escrow_deals.id", ondelete="RESTRICT")
    )
    source_address: Mapped[str | None] = mapped_column(String(128))
    destination_address: Mapped[str | None] = mapped_column(String(128))
    item_address: Mapped[str | None] = mapped_column(String(128))
    amount_nanotons: Mapped[Decimal | None] = mapped_column(Numeric(30, 0))
    masterchain_seqno: Mapped[int] = mapped_column(BigInteger, nullable=False)
    finalized: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))


class EscrowDispute(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_disputes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'confirmed', 'resolved_buyer', 'resolved_seller', "
            "'rejected', 'manual_review')",
            name="ck_escrow_dispute_status",
        ),
        CheckConstraint("length(reason) BETWEEN 5 AND 2000", name="ck_escrow_dispute_reason"),
        CheckConstraint(
            "reason_code IN ('not_received', 'wrong_asset', 'payment_mismatch', 'other')",
            name="ck_escrow_dispute_reason_code",
        ),
        Index(
            "uq_escrow_dispute_open_deal",
            "deal_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'confirmed', 'manual_review')"),
        ),
        Index("ix_escrow_dispute_opened_by", "opened_by", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("escrow_deals.id", ondelete="RESTRICT"), nullable=False
    )
    opened_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), server_default="requested", nullable=False)
    contract_confirmation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("escrow_chain_events.id", ondelete="RESTRICT")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EscrowWithdrawal(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_withdrawals"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_withdrawal_network_testnet"),
        CheckConstraint(
            "status IN ('blocked_abi_unavailable', 'prepared', 'submitted', 'confirmed', "
            "'failed', 'manual_review')",
            name="ck_escrow_withdrawal_status",
        ),
        CheckConstraint(
            "amount_nanotons IS NULL OR amount_nanotons > 0",
            name="ck_escrow_withdrawal_amount_positive",
        ),
        Index("ix_escrow_withdrawal_seller_created", "seller_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    recipient_address: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_nanotons: Mapped[Decimal | None] = mapped_column(Numeric(30, 0))
    status: Mapped[str] = mapped_column(
        String(32), server_default="blocked_abi_unavailable", nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_hash: Mapped[str | None] = mapped_column(String(128))


class EscrowIdempotencyRecord(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_idempotency_records"
    __table_args__ = (
        CheckConstraint(
            "length(idempotency_key) BETWEEN 8 AND 128",
            name="ck_escrow_idem_key_length",
        ),
        CheckConstraint("length(request_sha256) = 64", name="ck_escrow_idem_request_hash"),
        UniqueConstraint(
            "actor_id", "operation", "idempotency_key", name="uq_escrow_idempotency_actor_operation"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))


class EscrowObserverCheckpoint(EscrowBase):
    __tablename__ = "escrow_observer_checkpoints"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_checkpoint_network_testnet"),
    )

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    cursor: Mapped[str | None] = mapped_column(String(512))
    last_masterchain_seqno: Mapped[int | None] = mapped_column(BigInteger)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
