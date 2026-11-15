"""Persist immutable idempotency receipts for authenticated Stars intent API calls."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_payment_intent_api_requests"
down_revision: str | None = "0017_payment_xtr_invariants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_intent_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("payment_intent_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 8 AND 128",
            name="ck_payment_intent_requests_idempotency_key_length",
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64",
            name="ck_payment_intent_requests_request_sha256",
        ),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"], ["payment_intents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "buyer_id",
            "idempotency_key",
            name="uq_payment_intent_requests_buyer_key",
        ),
    )
    op.create_index(
        "ix_payment_intent_requests_order_created",
        "payment_intent_requests",
        ["order_id", "created_at"],
    )

    # The receipt is the durable proof of which request claimed an idempotency
    # key. Updating or deleting it would make a later conflicting replay look new.
    op.execute(
        """
        CREATE FUNCTION reject_payment_intent_request_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'payment intent idempotency receipts are immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payment_intent_requests_immutable
        BEFORE UPDATE OR DELETE ON payment_intent_requests
        FOR EACH ROW EXECUTE FUNCTION reject_payment_intent_request_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payment_intent_requests_no_truncate
        BEFORE TRUNCATE ON payment_intent_requests
        FOR EACH STATEMENT EXECUTE FUNCTION reject_payment_intent_request_mutation()
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_receipts = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM payment_intent_requests)")
    ).scalar_one()
    if has_receipts:
        raise RuntimeError(
            "Cannot downgrade payment intent API idempotency while receipt records exist"
        )

    op.drop_index(
        "ix_payment_intent_requests_order_created",
        table_name="payment_intent_requests",
    )
    op.drop_table("payment_intent_requests")
    op.execute(
        "DROP FUNCTION IF EXISTS reject_payment_intent_request_mutation()"
    )
