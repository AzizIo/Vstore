"""Harden payment ledger snapshot immutability and retention.

Payment status fields remain mutable through the domain state machine, but the
provider evidence and order snapshot that explain each charge are immutable.
Financial evidence rows cannot be deleted or truncated through ordinary SQL.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_payment_ledger_guards"
down_revision: str | None = "e20261114_ton_escrow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_payment_evidence_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'payment evidence is retained and cannot be deleted'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_payment_evidence_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'payment evidence is retained and cannot be truncated'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_payment_intent_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF ROW(
                NEW.order_id, NEW.provider, NEW.amount, NEW.currency,
                NEW.payer_telegram_id, NEW.invoice_payload, NEW.expires_at,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.order_id, OLD.provider, OLD.amount, OLD.currency,
                OLD.payer_telegram_id, OLD.invoice_payload, OLD.expires_at,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'payment intent snapshot is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_payment_transaction_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF ROW(
                NEW.payment_intent_id, NEW.provider,
                NEW.telegram_payment_charge_id, NEW.provider_payment_charge_id,
                NEW.amount, NEW.currency, NEW.payer_telegram_id,
                NEW.captured_at, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.payment_intent_id, OLD.provider,
                OLD.telegram_payment_charge_id, OLD.provider_payment_charge_id,
                OLD.amount, OLD.currency, OLD.payer_telegram_id,
                OLD.captured_at, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'payment transaction evidence is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_payment_intent_snapshot_immutable
        BEFORE UPDATE ON payment_intents
        FOR EACH ROW EXECUTE FUNCTION guard_payment_intent_snapshot()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payment_transaction_evidence_immutable
        BEFORE UPDATE ON payment_transactions
        FOR EACH ROW EXECUTE FUNCTION guard_payment_transaction_evidence()
        """
    )

    for table in ("payment_intents", "payment_transactions", "payment_events", "payment_refunds"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_payment_evidence_delete()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_payment_evidence_truncate()
            """
        )


def downgrade() -> None:
    # Removing these guards does not rewrite evidence. The downgrade is safe but
    # intentionally leaves all ledger rows untouched.
    for table in ("payment_intents", "payment_transactions", "payment_events", "payment_refunds"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete ON {table}")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_payment_transaction_evidence_immutable ON payment_transactions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_payment_intent_snapshot_immutable ON payment_intents"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_payment_transaction_evidence()")
    op.execute("DROP FUNCTION IF EXISTS guard_payment_intent_snapshot()")
    op.execute("DROP FUNCTION IF EXISTS reject_payment_evidence_truncate()")
    op.execute("DROP FUNCTION IF EXISTS reject_payment_evidence_delete()")
