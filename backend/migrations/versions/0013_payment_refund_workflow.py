"""Add durable Telegram Stars refund work, leases, and reconciliation state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_payment_refund_workflow"
down_revision: str | None = "0012_telegram_stars_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_transaction_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="queued", nullable=False
        ),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reconciliation_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'retry_wait', "
            "'reconciliation_required', 'succeeded', 'manual_review')",
            name="ck_payment_refunds_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_payment_refunds_attempts_nonnegative"
        ),
        sa.CheckConstraint(
            "reconciliation_count >= 0",
            name="ck_payment_refunds_reconciliations_nonnegative",
        ),
        sa.CheckConstraint(
            "((status = 'processing' AND lease_token IS NOT NULL "
            "AND locked_until IS NOT NULL) OR "
            "(status <> 'processing' AND lease_token IS NULL AND locked_until IS NULL))",
            name="ck_payment_refunds_processing_lease",
        ),
        sa.ForeignKeyConstraint(
            ["payment_transaction_id"],
            ["payment_transactions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payment_transaction_id", name="uq_payment_refunds_transaction"
        ),
    )
    op.create_index(
        "ix_payment_refunds_due",
        "payment_refunds",
        ["status", "next_attempt_at"],
    )

    # Existing refund_pending charges must not be stranded by adding the worker.
    # The new table is a durable queue, so enqueue legacy rows as pending work.
    op.execute(
        sa.text(
            """
            INSERT INTO payment_refunds
                (id, payment_transaction_id, status, reason_code)
            SELECT
                gen_random_uuid(),
                id,
                'queued',
                COALESCE(last_error_code, 'legacy_refund_pending')
            FROM payment_transactions
            WHERE status = 'refund_pending'
            ON CONFLICT (payment_transaction_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_refund_work = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM payment_refunds)")
    ).scalar_one()
    if has_refund_work:
        raise RuntimeError(
            "Cannot downgrade payment refund workflow while refund records exist; "
            "preserve refund audit and retry state."
        )

    op.drop_index("ix_payment_refunds_due", table_name="payment_refunds")
    op.drop_table("payment_refunds")
