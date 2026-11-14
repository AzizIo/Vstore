"""Prevent row-level deletion of durable refund evidence.

Refund workflow rows are reconciliation/audit evidence. Their lifecycle fields
remain mutable for retries, leases and reconciliation, but the row itself must
not be deleted by application or ordinary maintenance code. Disposable test
databases are cleaned up by dropping the database, not by deleting ledger rows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_refund_evidence"
down_revision: str | None = "0015_payment_ledger_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_payment_refund_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'payment refund evidence is retained and cannot be deleted'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payment_refunds_no_delete
        BEFORE DELETE ON payment_refunds
        FOR EACH ROW EXECUTE FUNCTION reject_payment_refund_delete()
        """
    )


def downgrade() -> None:
    # Downgrade removes only the guard. It never deletes or rewrites evidence.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_payment_refunds_no_delete ON payment_refunds"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_payment_refund_delete()")
