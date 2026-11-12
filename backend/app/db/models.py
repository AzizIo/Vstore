from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AssetType(str, enum.Enum):
    TON_NFT = "ton_nft"
    TELEGRAM_GIFT = "telegram_gift"


class AssetVerificationStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    STALE = "stale"


class ListingStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RESERVED = "reserved"
    SOLD = "sold"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUSPENDED = "suspended"


class PriceCurrency(str, enum.Enum):
    TON = "TON"
    XTR = "XTR"


class OrderStatus(str, enum.Enum):
    RESERVED = "reserved"
    AWAITING_TRANSFER = "awaiting_transfer"
    OBSERVING_TRANSFER = "observing_transfer"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# Statuses that still hold the listing reservation; a wallet involved in any of
# them must not be unlinked. Defined outside the enum body: a member inside the
# class becomes an enum value, which breaks enum_column's member iteration.
OrderStatus.LIVE_STATUSES = frozenset(  # type: ignore[attr-defined]
    {
        OrderStatus.RESERVED,
        OrderStatus.AWAITING_TRANSFER,
        OrderStatus.OBSERVING_TRANSFER,
    }
)


class OrderDeliveryAttemptStatus(str, enum.Enum):
    PREPARED = "prepared"
    OBSERVING = "observing"
    VERIFIED = "verified"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"
    CANCELLED = "cancelled"


def enum_column(enum_type: type[enum.Enum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
        length=32,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("telegram_id > 0", name="ck_users_telegram_id_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(16))
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    wallets: Mapped[list[Wallet]] = relationship(back_populates="user")
    assets: Mapped[list[NFTAsset]] = relationship(back_populates="owner")
    listings: Mapped[list[Listing]] = relationship(back_populates="seller")
    purchases: Mapped[list[Order]] = relationship(
        back_populates="buyer", foreign_keys="Order.buyer_id"
    )
    sales: Mapped[list[Order]] = relationship(
        back_populates="seller", foreign_keys="Order.seller_id"
    )


class Wallet(TimestampMixin, Base):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("network", "address", name="uq_wallets_network_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    network: Mapped[str] = mapped_column(
        String(16), default="mainnet", server_default="mainnet", nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="wallets")


class NFTCollection(TimestampMixin, Base):
    __tablename__ = "nft_collections"
    __table_args__ = (
        UniqueConstraint("network", "address", name="uq_nft_collections_network_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    network: Mapped[str] = mapped_column(
        String(16), default="mainnet", server_default="mainnet", nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(160))
    marketplace_name: Mapped[str | None] = mapped_column(String(160))
    metadata_json: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON)

    assets: Mapped[list[NFTAsset]] = relationship(back_populates="collection")


class NFTAsset(TimestampMixin, Base):
    __tablename__ = "nft_assets"
    __table_args__ = (
        UniqueConstraint(
            "asset_type",
            "network",
            "external_id",
            name="uq_nft_assets_type_network_external_id",
        ),
        CheckConstraint(
            "length(external_id) > 0", name="ck_nft_assets_external_id_nonempty"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_type: Mapped[AssetType] = mapped_column(
        enum_column(AssetType, "asset_type"), nullable=False
    )
    network: Mapped[str] = mapped_column(
        String(16), default="mainnet", server_default="mainnet", nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    item_address: Mapped[str | None] = mapped_column(String(128), index=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("nft_collections.id", ondelete="SET NULL"), index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON)
    verification_status: Mapped[AssetVerificationStatus] = mapped_column(
        enum_column(AssetVerificationStatus, "asset_verification_status"),
        default=AssetVerificationStatus.PENDING,
        server_default=AssetVerificationStatus.PENDING.value,
        nullable=False,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    collection: Mapped[NFTCollection | None] = relationship(back_populates="assets")
    owner: Mapped[User | None] = relationship(back_populates="assets")
    listings: Mapped[list[Listing]] = relationship(back_populates="asset")


class Listing(TimestampMixin, Base):
    __tablename__ = "listings"
    __table_args__ = (
        CheckConstraint("price_amount > 0", name="ck_listings_price_positive"),
        Index(
            "uq_listings_open_asset",
            "asset_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'reserved')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("nft_assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[ListingStatus] = mapped_column(
        enum_column(ListingStatus, "listing_status"),
        default=ListingStatus.DRAFT,
        server_default=ListingStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    price_amount: Mapped[Decimal] = mapped_column(Numeric(24, 9), nullable=False)
    price_currency: Mapped[PriceCurrency] = mapped_column(
        enum_column(PriceCurrency, "price_currency"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    asset: Mapped[NFTAsset] = relationship(back_populates="listings")
    seller: Mapped[User] = relationship(back_populates="listings")
    orders: Mapped[list[Order]] = relationship(back_populates="listing")


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("price_amount > 0", name="ck_orders_price_positive"),
        CheckConstraint(
            "status IN ('reserved', 'awaiting_transfer', 'observing_transfer', "
            "'completed', 'cancelled', 'expired')",
            name="ck_orders_status",
        ),
        UniqueConstraint("buyer_id", "idempotency_key", name="uq_orders_buyer_idempotency"),
        Index(
            "uq_orders_open_listing",
            "listing_id",
            unique=True,
            postgresql_where=text(
                "status IN ('reserved', 'awaiting_transfer', 'observing_transfer')"
            ),
        ),
        Index("ix_orders_buyer_created_at", "buyer_id", "created_at"),
        Index("ix_orders_seller_created_at", "seller_id", "created_at"),
        Index("ix_orders_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus, "order_status"),
        default=OrderStatus.RESERVED,
        server_default=OrderStatus.RESERVED.value,
        nullable=False,
    )
    price_amount: Mapped[Decimal] = mapped_column(Numeric(24, 9), nullable=False)
    price_currency: Mapped[PriceCurrency] = mapped_column(
        enum_column(PriceCurrency, "price_currency"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    listing: Mapped[Listing] = relationship(back_populates="orders")
    buyer: Mapped[User] = relationship(back_populates="purchases", foreign_keys=[buyer_id])
    seller: Mapped[User] = relationship(back_populates="sales", foreign_keys=[seller_id])
    events: Mapped[list[OrderEvent]] = relationship(
        back_populates="order", order_by="OrderEvent.created_at"
    )
    delivery_attempts: Mapped[list[OrderDeliveryAttempt]] = relationship(
        back_populates="order", order_by="OrderDeliveryAttempt.attempt_number"
    )


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('buyer', 'seller', 'system')",
            name="ck_order_events_actor_type",
        ),
        CheckConstraint(
            "(from_status IS NULL OR from_status IN "
            "('reserved', 'awaiting_transfer', 'observing_transfer', "
            "'completed', 'cancelled', 'expired')) "
            "AND to_status IN ('reserved', 'awaiting_transfer', 'observing_transfer', "
            "'completed', 'cancelled', 'expired')",
            name="ck_order_events_statuses",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    from_status: Mapped[OrderStatus | None] = mapped_column(
        enum_column(OrderStatus, "order_event_from_status")
    )
    to_status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus, "order_event_to_status"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped[Order] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship()



class OrderDeliveryAttempt(TimestampMixin, Base):
    """Immutable source/destination snapshot and one candidate transfer attempt."""

    __tablename__ = "order_delivery_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="ck_order_delivery_attempt_number_positive"),
        CheckConstraint(
            "query_id >= 0 AND query_id <= 18446744073709551615",
            name="ck_order_delivery_attempt_query_id_uint64",
        ),
        CheckConstraint(
            "deadline > prepared_at",
            name="ck_order_delivery_attempt_deadline",
        ),
        CheckConstraint(
            "status IN ('prepared', 'observing', 'verified', 'failed', "
            "'manual_review', 'cancelled')",
            name="ck_order_delivery_attempt_status",
        ),
        CheckConstraint(
            "masterchain_seqno IS NULL OR masterchain_seqno > 0",
            name="ck_order_delivery_attempt_masterchain_seqno",
        ),
        CheckConstraint(
            "status != 'verified' OR (transaction_hash IS NOT NULL AND verified_at IS NOT NULL)",
            name="ck_order_delivery_attempt_verified_evidence",
        ),
        CheckConstraint(
            "observer_attempt_count >= 0",
            name="ck_order_delivery_attempt_observer_attempt_count",
        ),
        UniqueConstraint(
            "order_id", "attempt_number", name="uq_order_delivery_attempt_order_number"
        ),
        UniqueConstraint(
            "network", "item_address", "query_id",
            name="uq_order_delivery_attempt_item_query",
        ),
        UniqueConstraint(
            "order_id",
            "prepare_idempotency_key",
            name="uq_order_delivery_attempt_prepare_idempotency",
        ),
        CheckConstraint(
            "prepare_idempotency_key IS NULL OR length(prepare_idempotency_key) > 0",
            name="ck_order_delivery_attempt_prepare_key_nonempty",
        ),
        Index(
            "uq_order_delivery_attempt_active_order",
            "order_id",
            unique=True,
            postgresql_where=text("status IN ('prepared', 'observing', 'manual_review')"),
        ),
        Index(
            "uq_order_delivery_attempt_verified_transfer",
            "network",
            "item_address",
            "transaction_hash",
            unique=True,
            postgresql_where=text("status = 'verified' AND transaction_hash IS NOT NULL"),
        ),
        Index("ix_order_delivery_attempts_observer", "status", "next_check_at"),
        Index(
            "ix_order_delivery_attempts_observer_lease",
            "status",
            "observer_lease_until",
            "next_check_at",
        ),
        Index("ix_order_delivery_attempts_order_created", "order_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderDeliveryAttemptStatus] = mapped_column(
        enum_column(OrderDeliveryAttemptStatus, "order_delivery_attempt_status"),
        default=OrderDeliveryAttemptStatus.PREPARED,
        server_default=OrderDeliveryAttemptStatus.PREPARED.value,
        nullable=False,
    )
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    item_address: Mapped[str] = mapped_column(String(128), nullable=False)
    seller_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wallets.id", ondelete="SET NULL")
    )
    seller_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    buyer_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wallets.id", ondelete="SET NULL")
    )
    buyer_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    query_id: Mapped[Decimal] = mapped_column(Numeric(20, 0), nullable=False)
    candidate_transaction_hash: Mapped[str | None] = mapped_column(String(128))
    transaction_hash: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[str | None] = mapped_column(String(128))
    masterchain_seqno: Mapped[int | None] = mapped_column(BigInteger)
    provider_source: Mapped[str | None] = mapped_column(String(32))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observer_attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    observer_lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    observer_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prepare_idempotency_key: Mapped[str | None] = mapped_column(String(128))

    order: Mapped[Order] = relationship(back_populates="delivery_attempts")


class TelegramNotificationOutbox(Base):
    __tablename__ = "telegram_notification_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'delivered', 'failed')",
            name="ck_telegram_notification_outbox_status",
        ),
        CheckConstraint(
            "recipient_role IN ('buyer', 'seller')",
            name="ck_telegram_notification_outbox_recipient_role",
        ),
        CheckConstraint(
            "event_type IN ('order_created', 'order_cancelled', 'order_expired', "
            "'delivery_prepared', 'delivery_submitted', 'delivery_confirmed', "
            "'delivery_manual_review')",
            name="ck_telegram_notification_outbox_event_type",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_telegram_notification_outbox_attempt_count",
        ),
        UniqueConstraint("dedupe_key", name="uq_telegram_notification_outbox_dedupe_key"),
        Index("ix_telegram_notification_outbox_due", "status", "next_attempt_at"),
        Index("ix_telegram_notification_outbox_order", "order_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dedupe_key: Mapped[str] = mapped_column(String(192), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    recipient_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recipient_role: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModerationAuditLog(Base):
    """Append-only, privacy-safe record of administrative listing decisions."""

    __tablename__ = "moderation_audit_log"
    __table_args__ = (
        CheckConstraint("target_type = 'listing'", name="ck_moderation_audit_target_type"),
        CheckConstraint(
            "action IN ('approved', 'rejected', 'suspended', 'restored')",
            name="ck_moderation_audit_action",
        ),
        CheckConstraint(
            "reason_code IN ('policy_violation', 'ownership_unverified', "
            "'misleading_metadata', 'duplicate_listing', 'other')",
            name="ck_moderation_audit_reason_code",
        ),
        CheckConstraint("length(reason) BETWEEN 5 AND 500", name="ck_moderation_audit_reason_length"),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 8 AND 128",
            name="ck_moderation_audit_idempotency_key_length",
        ),
        UniqueConstraint("actor_id", "idempotency_key", name="uq_moderation_audit_actor_idempotency"),
        Index("ix_moderation_audit_target_time", "target_type", "target_id", "occurred_at"),
        Index("ix_moderation_audit_actor_time", "actor_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="listing")
    target_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    before_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    after_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
