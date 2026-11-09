from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    JSON,
    Index,
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


class PriceCurrency(str, enum.Enum):
    TON = "TON"
    XTR = "XTR"


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
        UniqueConstraint("asset_type", "external_id", name="uq_nft_assets_type_external_id"),
        CheckConstraint("length(external_id) > 0", name="ck_nft_assets_external_id_nonempty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_type: Mapped[AssetType] = mapped_column(
        enum_column(AssetType, "asset_type"), nullable=False
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
