"""Add immutable NFT delivery attempts and post-reservation order states.

Existing pending_payment rows/events are reservations, not payments. They are
renamed in place to reserved; all historical IDs, snapshots and event rows stay.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_order_delivery_attempts"
down_revision: str | None = "0004_tg_notif_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OPEN_ORDER_STATUSES = "('reserved', 'awaiting_transfer', 'observing_transfer')"
_ALL_ORDER_STATUSES = (
    "('reserved', 'awaiting_transfer', 'observing_transfer', "
    "'completed', 'cancelled', 'expired')"
)


def upgrade() -> None:
    # Remove legacy constraints/index while preserving the rows that they protect.
    # 0003 created the partial unique index as "uq_orders_pending_listing";
    # the model and the recreated index use "uq_orders_open_listing". Drop the
    # name that actually exists in the database, not the name the model uses.
    op.drop_index("uq_orders_pending_listing", table_name="orders")
    op.alter_column(
        "orders",
        "status",
        existing_type=sa.String(length=32),
        server_default="reserved",
    )
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.drop_constraint("ck_order_events_statuses", "order_events", type_="check")
    op.drop_constraint("ck_order_events_actor_type", "order_events", type_="check")

    # pending_payment was only a reservation label. Preserve every historical row.
    op.execute(
        sa.text("UPDATE orders SET status = 'reserved' WHERE status = 'pending_payment'")
    )
    op.execute(
        sa.text(
            "UPDATE order_events SET from_status = 'reserved' "
            "WHERE from_status = 'pending_payment'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE order_events SET to_status = 'reserved' "
            "WHERE to_status = 'pending_payment'"
        )
    )

    op.create_check_constraint(
        "ck_orders_status",
        "orders",
        f"status IN {_ALL_ORDER_STATUSES}",
    )
    op.create_check_constraint(
        "ck_order_events_statuses",
        "order_events",
        f"(from_status IS NULL OR from_status IN {_ALL_ORDER_STATUSES}) "
        f"AND to_status IN {_ALL_ORDER_STATUSES}",
    )
    op.create_check_constraint(
        "ck_order_events_actor_type",
        "order_events",
        "actor_type IN ('buyer', 'seller', 'system')",
    )
    op.create_index(
        "uq_orders_open_listing",
        "orders",
        ["listing_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN {_OPEN_ORDER_STATUSES}"),
    )

    op.create_table(
        "order_delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="prepared", nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("item_address", sa.String(length=128), nullable=False),
        sa.Column("seller_wallet_id", sa.Uuid(), nullable=True),
        sa.Column("seller_address_snapshot", sa.String(length=128), nullable=False),
        sa.Column("buyer_wallet_id", sa.Uuid(), nullable=True),
        sa.Column("buyer_address_snapshot", sa.String(length=128), nullable=False),
        sa.Column("query_id", sa.Numeric(precision=20, scale=0), nullable=False),
        sa.Column("candidate_transaction_hash", sa.String(length=128), nullable=True),
        sa.Column("transaction_hash", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("masterchain_seqno", sa.BigInteger(), nullable=True),
        sa.Column("provider_source", sa.String(length=32), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_order_delivery_attempt_number_positive",
        ),
        sa.CheckConstraint(
            "query_id >= 0 AND query_id <= 18446744073709551615",
            name="ck_order_delivery_attempt_query_id_uint64",
        ),
        sa.CheckConstraint(
            "deadline > prepared_at",
            name="ck_order_delivery_attempt_deadline",
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'observing', 'verified', 'failed', "
            "'manual_review', 'cancelled')",
            name="ck_order_delivery_attempt_status",
        ),
        sa.CheckConstraint(
            "masterchain_seqno IS NULL OR masterchain_seqno > 0",
            name="ck_order_delivery_attempt_masterchain_seqno",
        ),
        sa.CheckConstraint(
            "status != 'verified' OR (transaction_hash IS NOT NULL AND verified_at IS NOT NULL)",
            name="ck_order_delivery_attempt_verified_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["seller_wallet_id"], ["wallets.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["buyer_wallet_id"], ["wallets.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id", "attempt_number",
            name="uq_order_delivery_attempt_order_number",
        ),
        sa.UniqueConstraint(
            "network", "item_address", "query_id",
            name="uq_order_delivery_attempt_item_query",
        ),
    )
    op.create_index(
        "uq_order_delivery_attempt_active_order",
        "order_delivery_attempts",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('prepared', 'observing', 'manual_review')"
        ),
    )
    op.create_index(
        "uq_order_delivery_attempt_verified_transfer",
        "order_delivery_attempts",
        ["network", "item_address", "transaction_hash"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'verified' AND transaction_hash IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_order_delivery_attempts_observer",
        "order_delivery_attempts",
        ["status", "next_check_at"],
    )
    op.create_index(
        "ix_order_delivery_attempts_order_created",
        "order_delivery_attempts",
        ["order_id", "created_at"],
    )

    # Snapshotted addresses/identity cannot be rewritten after a seller is
    # authorized to deliver. Wallet row IDs may still be nulled by ON DELETE SET NULL.
    op.execute(
        """
        CREATE FUNCTION prevent_order_delivery_attempt_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.order_id IS DISTINCT FROM OLD.order_id
                OR NEW.attempt_number IS DISTINCT FROM OLD.attempt_number
                OR NEW.network IS DISTINCT FROM OLD.network
                OR NEW.item_address IS DISTINCT FROM OLD.item_address
                OR NEW.seller_address_snapshot IS DISTINCT FROM OLD.seller_address_snapshot
                OR NEW.buyer_address_snapshot IS DISTINCT FROM OLD.buyer_address_snapshot
                OR NEW.query_id IS DISTINCT FROM OLD.query_id
                OR NEW.prepared_at IS DISTINCT FROM OLD.prepared_at
                OR NEW.deadline IS DISTINCT FROM OLD.deadline
            THEN
                RAISE EXCEPTION 'order delivery attempt snapshots are immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_order_delivery_attempt_snapshots_immutable
        BEFORE UPDATE ON order_delivery_attempts
        FOR EACH ROW
        EXECUTE FUNCTION prevent_order_delivery_attempt_snapshot_mutation()
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    active_orders = bind.execute(
        sa.text(
            "SELECT count(*) FROM orders "
            "WHERE status NOT IN ('reserved', 'cancelled', 'expired')"
        )
    ).scalar_one()
    attempts = bind.execute(
        sa.text("SELECT count(*) FROM order_delivery_attempts")
    ).scalar_one()
    delivery_events = bind.execute(
        sa.text(
            "SELECT count(*) FROM order_events WHERE "
            "from_status IN ('awaiting_transfer', 'observing_transfer', 'completed') "
            "OR to_status IN ('awaiting_transfer', 'observing_transfer', 'completed') "
            "OR actor_type = 'seller'"
        )
    ).scalar_one()
    if active_orders or attempts or delivery_events:
        raise RuntimeError(
            "Cannot downgrade delivery lifecycle after non-reservation states, "
            "delivery events, or attempts have been recorded; preserve the evidence."
        )

    op.drop_index(
        "ix_order_delivery_attempts_order_created",
        table_name="order_delivery_attempts",
    )
    op.drop_index(
        "ix_order_delivery_attempts_observer",
        table_name="order_delivery_attempts",
    )
    op.drop_index(
        "uq_order_delivery_attempt_verified_transfer",
        table_name="order_delivery_attempts",
    )
    op.drop_index(
        "uq_order_delivery_attempt_active_order",
        table_name="order_delivery_attempts",
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_order_delivery_attempt_snapshots_immutable "
        "ON order_delivery_attempts"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS prevent_order_delivery_attempt_snapshot_mutation()"
    )
    op.drop_table("order_delivery_attempts")

    op.drop_index("uq_orders_open_listing", table_name="orders")
    op.alter_column(
        "orders",
        "status",
        existing_type=sa.String(length=32),
        server_default="pending_payment",
    )
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.drop_constraint("ck_order_events_statuses", "order_events", type_="check")
    op.drop_constraint("ck_order_events_actor_type", "order_events", type_="check")

    op.execute(sa.text("UPDATE orders SET status = 'pending_payment' WHERE status = 'reserved'"))
    op.execute(
        sa.text(
            "UPDATE order_events SET from_status = 'pending_payment' "
            "WHERE from_status = 'reserved'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE order_events SET to_status = 'pending_payment' "
            "WHERE to_status = 'reserved'"
        )
    )

    op.create_check_constraint(
        "ck_orders_status",
        "orders",
        "status IN ('pending_payment', 'cancelled', 'expired')",
    )
    op.create_check_constraint(
        "ck_order_events_statuses",
        "order_events",
        "(from_status IS NULL OR from_status IN "
        "('pending_payment', 'cancelled', 'expired')) "
        "AND to_status IN ('pending_payment', 'cancelled', 'expired')",
    )
    op.create_check_constraint(
        "ck_order_events_actor_type",
        "order_events",
        "actor_type IN ('buyer', 'system')",
    )
    op.create_index(
        "uq_orders_pending_listing",
        "orders",
        ["listing_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending_payment'"),
    )
