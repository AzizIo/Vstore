"""Add durable Telegram notification outbox."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_tg_notif_outbox"
down_revision: str | None = "0003_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_notification_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=192), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=True),
        sa.Column("recipient_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("recipient_role", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'delivered', 'failed')",
            name="ck_telegram_notification_outbox_status",
        ),
        sa.CheckConstraint(
            "recipient_role IN ('buyer', 'seller')",
            name="ck_telegram_notification_outbox_recipient_role",
        ),
        sa.CheckConstraint(
            "event_type IN ('order_created', 'order_cancelled', 'order_expired')",
            name="ck_telegram_notification_outbox_event_type",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_telegram_notification_outbox_attempt_count",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_telegram_notification_outbox_dedupe_key"),
    )
    op.create_index(
        "ix_telegram_notification_outbox_due",
        "telegram_notification_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_telegram_notification_outbox_order",
        "telegram_notification_outbox",
        ["order_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_notification_outbox_order", table_name="telegram_notification_outbox"
    )
    op.drop_index("ix_telegram_notification_outbox_due", table_name="telegram_notification_outbox")
    op.drop_table("telegram_notification_outbox")
