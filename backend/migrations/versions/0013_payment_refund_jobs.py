"""Add durable, leased Telegram Stars refund jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_payment_refund_jobs"
down_revision: str | None = "0012_telegram_stars_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "payment_refund_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_refund_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'reconciling', 'succeeded', 'manual_review')",
            name="ck_payment_refund_jobs_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_payment_refund_jobs_attempt_count"
        ),
        sa.CheckConstraint(
            "(status = 'processing' AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'processing' AND claim_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_payment_refund_jobs_lease",
        ),
        sa.ForeignKeyConstraint(
            ["payment_transaction_id"],
            ["payment_transactions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payment_transaction_id", name="uq_payment_refund_jobs_transaction"
        ),
    )
    op.create_index(
        "ix_payment_refund_jobs_status_next",
        "payment_refund_jobs",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_payment_refund_jobs_status_lease",
        "payment_refund_jobs",
        ["status", "lease_expires_at"],
    )

    # Recover refund_pending charges created before this worker was deployed.
    op.execute(
        """
        INSERT INTO payment_refund_jobs (
            id, payment_transaction_id, status, attempt_count,
            next_attempt_at, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), id, 'pending', 0, now(), now(), now()
        FROM payment_transactions
        WHERE status = 'refund_pending'
        ON CONFLICT (payment_transaction_id) DO NOTHING
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_jobs = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM payment_refund_jobs)")
    ).scalar_one()
    if has_jobs:
        raise RuntimeError(
            "Cannot downgrade payment refund jobs after refund processing evidence "
            "has been recorded; preserve the refund audit trail."
        )

    op.drop_index("ix_payment_refund_jobs_status_lease", table_name="payment_refund_jobs")
    op.drop_index("ix_payment_refund_jobs_status_next", table_name="payment_refund_jobs")
    op.drop_table("payment_refund_jobs")
