"""Create initial marketplace tables."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_marketplace"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=False),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("telegram_id > 0", name="ck_users_telegram_id_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "wallets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(length=128), nullable=False),
        sa.Column("network", sa.String(length=16), server_default="mainnet", nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network", "address", name="uq_wallets_network_address"),
    )
    op.create_index("ix_wallets_user_id", "wallets", ["user_id"])

    op.create_table(
        "nft_collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(length=128), nullable=False),
        sa.Column("network", sa.String(length=16), server_default="mainnet", nullable=False),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("marketplace_name", sa.String(length=160), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network", "address", name="uq_nft_collections_network_address"),
    )

    op.create_table(
        "nft_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=False),
        sa.Column("item_address", sa.String(length=128), nullable=True),
        sa.Column("collection_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "verification_status", sa.String(length=32), server_default="pending", nullable=False
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(external_id) > 0", name="ck_nft_assets_external_id_nonempty"),
        sa.ForeignKeyConstraint(["collection_id"], ["nft_collections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_type", "external_id", name="uq_nft_assets_type_external_id"),
    )
    op.create_index("ix_nft_assets_item_address", "nft_assets", ["item_address"])
    op.create_index("ix_nft_assets_collection_id", "nft_assets", ["collection_id"])
    op.create_index("ix_nft_assets_owner_id", "nft_assets", ["owner_id"])

    op.create_table(
        "listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("seller_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("price_amount", sa.Numeric(precision=24, scale=9), nullable=False),
        sa.Column("price_currency", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("price_amount > 0", name="ck_listings_price_positive"),
        sa.ForeignKeyConstraint(["asset_id"], ["nft_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_listings_asset_id", "listings", ["asset_id"])
    op.create_index("ix_listings_seller_id", "listings", ["seller_id"])
    op.create_index("ix_listings_status", "listings", ["status"])
    op.create_index(
        "uq_listings_open_asset",
        "listings",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'reserved')"),
    )


def downgrade() -> None:
    op.drop_index("uq_listings_open_asset", table_name="listings")
    op.drop_index("ix_listings_status", table_name="listings")
    op.drop_index("ix_listings_seller_id", table_name="listings")
    op.drop_index("ix_listings_asset_id", table_name="listings")
    op.drop_table("listings")
    op.drop_index("ix_nft_assets_owner_id", table_name="nft_assets")
    op.drop_index("ix_nft_assets_collection_id", table_name="nft_assets")
    op.drop_index("ix_nft_assets_item_address", table_name="nft_assets")
    op.drop_table("nft_assets")
    op.drop_table("nft_collections")
    op.drop_index("ix_wallets_user_id", table_name="wallets")
    op.drop_table("wallets")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
