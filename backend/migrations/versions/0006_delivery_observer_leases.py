"""Add reclaimable leases and bounded retry counters for delivery observer.

Revision ID: 0006_delivery_observer_leases
Revises: 0005_order_delivery_attempts
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_delivery_observer_leases"
down_revision: str | None = "0005_order_delivery_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_delivery_attempts",
        sa.Column("observer_attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "order_delivery_attempts",
        sa.Column("observer_lease_token", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "order_delivery_attempts",
        sa.Column("observer_lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_order_delivery_attempt_observer_attempt_count",
        "order_delivery_attempts",
        "observer_attempt_count >= 0",
    )
    op.create_index(
        "ix_order_delivery_attempts_observer_lease",
        "order_delivery_attempts",
        ["status", "observer_lease_until", "next_check_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    claimed_or_retried = bind.execute(
        sa.text(
            "SELECT count(*) FROM order_delivery_attempts "
            "WHERE observer_attempt_count > 0 OR observer_lease_token IS NOT NULL "
            "OR observer_lease_until IS NOT NULL"
        )
    ).scalar_one()
    if claimed_or_retried:
        raise RuntimeError(
            "Cannot downgrade delivery observer leases after an attempt was claimed; "
            "preserve observer retry history."
        )
    op.drop_index(
        "ix_order_delivery_attempts_observer_lease",
        table_name="order_delivery_attempts",
    )
    op.drop_constraint(
        "ck_order_delivery_attempt_observer_attempt_count",
        "order_delivery_attempts",
        type_="check",
    )
    op.drop_column("order_delivery_attempts", "observer_lease_until")
    op.drop_column("order_delivery_attempts", "observer_lease_token")
    op.drop_column("order_delivery_attempts", "observer_attempt_count")
