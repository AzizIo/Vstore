"""Add Telegram Stars payment intent, charge ledger and event journal."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_telegram_stars_payments"
down_revision: str | None = "0011_listing_pending_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "payment_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="telegram_stars", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("amount", sa.Numeric(precision=24, scale=9), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="XTR", nullable=False),
        sa.Column("payer_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("invoice_payload", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refund_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_intents_amount_positive"),
        sa.CheckConstraint("currency = 'XTR'", name="ck_payment_intents_currency_stars"),
        sa.CheckConstraint("provider = 'telegram_stars'", name="ck_payment_intents_provider"),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'refund_pending', 'refunded', 'failed', 'expired')",
            name="ck_payment_intents_status",
        ),
        sa.CheckConstraint("payer_telegram_id > 0", name="ck_payment_intents_payer_positive"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_payment_intents_order"),
        sa.UniqueConstraint("invoice_payload", name="uq_payment_intents_invoice_payload"),
    )
    op.create_index(
        "ix_payment_intents_status_expires", "payment_intents", ["status", "expires_at"]
    )

    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_intent_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="telegram_stars", nullable=False),
        sa.Column("telegram_payment_charge_id", sa.String(length=128), nullable=False),
        sa.Column("provider_payment_charge_id", sa.String(length=128), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=9), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="XTR", nullable=False),
        sa.Column("payer_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="captured", nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refund_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_transactions_amount_positive"),
        sa.CheckConstraint("currency = 'XTR'", name="ck_payment_transactions_currency_stars"),
        sa.CheckConstraint(
            "status IN ('captured', 'refund_pending', 'refunded')",
            name="ck_payment_transactions_status",
        ),
        sa.CheckConstraint("payer_telegram_id > 0", name="ck_payment_transactions_payer_positive"),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"], ["payment_intents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "telegram_payment_charge_id", name="uq_payment_transactions_telegram_charge"
        ),
        sa.UniqueConstraint(
            "provider_payment_charge_id", name="uq_payment_transactions_provider_charge"
        ),
    )
    op.create_index(
        "ix_payment_transactions_intent_status",
        "payment_transactions",
        ["payment_intent_id", "status"],
    )

    op.create_table(
        "payment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_intent_id", sa.Uuid(), nullable=False),
        sa.Column("payment_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=32), server_default="telegram_stars", nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('intent_created', 'pre_checkout_accepted', "
            "'payment_succeeded', 'payment_rejected', 'refund_requested', "
            "'refund_succeeded', 'refund_failed')",
            name="ck_payment_events_event_type",
        ),
        sa.CheckConstraint(
            "length(provider_event_id) BETWEEN 1 AND 128",
            name="ck_payment_events_provider_event_id",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64", name="ck_payment_events_payload_sha256"
        ),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"], ["payment_intents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["payment_transaction_id"], ["payment_transactions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_event_id", name="uq_payment_events_provider_event"
        ),
    )
    op.create_index(
        "ix_payment_events_intent_created", "payment_events", ["payment_intent_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_payment_events_intent_created", table_name="payment_events")
    op.drop_table("payment_events")
    op.drop_index("ix_payment_transactions_intent_status", table_name="payment_transactions")
    op.drop_table("payment_transactions")
    op.drop_index("ix_payment_intents_status_expires", table_name="payment_intents")
    op.drop_table("payment_intents")
