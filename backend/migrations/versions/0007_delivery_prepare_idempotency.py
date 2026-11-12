"""Persist idempotency keys for seller delivery preparation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_delivery_prepare_key"
down_revision: str | None = "0006_delivery_observer_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_delivery_attempts",
        sa.Column("prepare_idempotency_key", sa.String(length=128), nullable=True),
    )
    op.create_check_constraint(
        "ck_order_delivery_attempt_prepare_key_nonempty",
        "order_delivery_attempts",
        "prepare_idempotency_key IS NULL OR length(prepare_idempotency_key) > 0",
    )
    op.create_unique_constraint(
        "uq_order_delivery_attempt_prepare_idempotency",
        "order_delivery_attempts",
        ["order_id", "prepare_idempotency_key"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_order_delivery_attempt_snapshot_mutation()
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
                OR NEW.prepare_idempotency_key IS DISTINCT FROM OLD.prepare_idempotency_key
            THEN
                RAISE EXCEPTION 'order delivery attempt snapshots are immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    keyed_attempts = bind.execute(
        sa.text(
            "SELECT count(*) FROM order_delivery_attempts "
            "WHERE prepare_idempotency_key IS NOT NULL"
        )
    ).scalar_one()
    if keyed_attempts:
        raise RuntimeError(
            "Cannot downgrade delivery preparation after idempotency keys have been recorded"
        )
    op.drop_constraint(
        "uq_order_delivery_attempt_prepare_idempotency",
        "order_delivery_attempts",
        type_="unique",
    )
    op.drop_constraint(
        "ck_order_delivery_attempt_prepare_key_nonempty",
        "order_delivery_attempts",
        type_="check",
    )
    op.drop_column("order_delivery_attempts", "prepare_idempotency_key")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_order_delivery_attempt_snapshot_mutation()
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
