"""Add order reservation lifecycle."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_orders"
down_revision: str | None = "0001_initial_marketplace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("seller_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending_payment", nullable=False),
        sa.Column("price_amount", sa.Numeric(precision=24, scale=9), nullable=False),
        sa.Column("price_currency", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("price_amount > 0", name="ck_orders_price_positive"),
        sa.CheckConstraint(
            "status IN ('pending_payment', 'cancelled', 'expired')",
            name="ck_orders_status",
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("buyer_id", "idempotency_key", name="uq_orders_buyer_idempotency"),
    )
    op.create_index(
        "uq_orders_pending_listing",
        "orders",
        ["listing_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending_payment'"),
    )
    op.create_index("ix_orders_buyer_created_at", "orders", ["buyer_id", "created_at"])
    op.create_index("ix_orders_seller_created_at", "orders", ["seller_id", "created_at"])
    op.create_index("ix_orders_status_expires_at", "orders", ["status", "expires_at"])

    op.create_table(
        "order_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("actor_type IN ('buyer', 'system')", name="ck_order_events_actor_type"),
        sa.CheckConstraint(
            "(from_status IS NULL OR from_status IN ('pending_payment', 'cancelled', 'expired')) "
            "AND to_status IN ('pending_payment', 'cancelled', 'expired')",
            name="ck_order_events_statuses",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_events_order_id", "order_events", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_order_events_order_id", table_name="order_events")
    op.drop_table("order_events")
    op.drop_index("ix_orders_status_expires_at", table_name="orders")
    op.drop_index("ix_orders_seller_created_at", table_name="orders")
    op.drop_index("ix_orders_buyer_created_at", table_name="orders")
    op.drop_index("uq_orders_pending_listing", table_name="orders")
    op.drop_table("orders")
