"""Add durable, idempotent escrow wallet action records.

This migration stores testnet-only action intents and untrusted submission hints.
It does not enable signing, broadcast transactions, or advance deal state.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e20261115_escrow_actions"
# 0016_refund_evidence already descends from e20261114_ton_escrow. Using both
# revisions here would create a redundant ancestor edge and an ambiguous
# downgrade walk; this migration follows the actual latest predecessor.
down_revision: str = "0016_refund_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "escrow_wallet_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("network", sa.String(16), server_default="testnet", nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt_id", sa.String(128), nullable=True),
        sa.Column("query_id", sa.String(128), nullable=True),
        sa.Column("unsigned_boc_sha256", sa.String(64), nullable=True),
        sa.Column("unsigned_boc_ref", sa.String(512), nullable=True),
        sa.Column("submission_reference", sa.String(512), nullable=True),
        sa.Column("submission_reference_sha256", sa.String(64), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.CheckConstraint("network = 'testnet'", name="ck_escrow_action_network_testnet"),
        sa.CheckConstraint(
            "status IN ('pending', 'prepared', 'submitted', 'ambiguous', 'finalized', "
            "'failed', 'manual_review', 'blocked_abi')",
            name="ck_escrow_action_status",
        ),
        sa.CheckConstraint("length(idempotency_key) BETWEEN 8 AND 128",
            name="ck_escrow_action_idempotency_length"),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_escrow_action_request_hash"),
        sa.CheckConstraint(
            "unsigned_boc_sha256 IS NULL OR length(unsigned_boc_sha256) = 64",
            name="ck_escrow_action_boc_hash"),
        sa.CheckConstraint(
            "(unsigned_boc_sha256 IS NULL AND unsigned_boc_ref IS NULL) OR "
            "(unsigned_boc_sha256 IS NOT NULL AND unsigned_boc_ref IS NOT NULL)",
            name="ck_escrow_action_boc_pair"),
        sa.CheckConstraint(
            "submission_reference_sha256 IS NULL OR length(submission_reference_sha256) = 64",
            name="ck_escrow_action_submission_hash"),
        sa.CheckConstraint(
            "(submission_reference IS NULL AND submission_reference_sha256 IS NULL) OR "
            "(submission_reference IS NOT NULL AND submission_reference_sha256 IS NOT NULL "
            "AND length(submission_reference) BETWEEN 1 AND 512)",
            name="ck_escrow_action_submission_pair"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_escrow_action_attempt_count"),
        sa.ForeignKeyConstraint(["deal_id"], ["escrow_deals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", "action_type", "idempotency_key",
            name="uq_escrow_action_actor_type_idem"),
    )
    op.create_index("ix_escrow_action_deal_status", "escrow_wallet_actions",
        ["deal_id", "status"])
    op.create_index("ix_escrow_action_retry", "escrow_wallet_actions",
        ["status", "next_retry_at"])
    op.create_index(
        "uq_escrow_action_submission_reference", "escrow_wallet_actions",
        ["network", "submission_reference_sha256"], unique=True,
        postgresql_where=sa.text("submission_reference_sha256 IS NOT NULL"),
    )
    op.execute("""
        CREATE FUNCTION prevent_escrow_action_identity_mutation()
        RETURNS trigger AS $action$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.deal_id IS DISTINCT FROM OLD.deal_id
                OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
                OR NEW.action_type IS DISTINCT FROM OLD.action_type
                OR NEW.network IS DISTINCT FROM OLD.network
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256
            THEN
                RAISE EXCEPTION 'Escrow action request identity is immutable';
            END IF;
            IF OLD.attempt_id IS NOT NULL
                AND NEW.attempt_id IS DISTINCT FROM OLD.attempt_id
            THEN
                RAISE EXCEPTION 'Escrow action attempt id cannot be replaced';
            END IF;
            IF OLD.query_id IS NOT NULL
                AND NEW.query_id IS DISTINCT FROM OLD.query_id
            THEN
                RAISE EXCEPTION 'Escrow action query id cannot be replaced';
            END IF;
            IF OLD.unsigned_boc_sha256 IS NOT NULL
                AND (
                    NEW.unsigned_boc_sha256 IS DISTINCT FROM OLD.unsigned_boc_sha256
                    OR NEW.unsigned_boc_ref IS DISTINCT FROM OLD.unsigned_boc_ref
                )
            THEN
                RAISE EXCEPTION 'Escrow action unsigned BOC cannot be replaced';
            END IF;
            IF OLD.submission_reference_sha256 IS NOT NULL
                AND (
                    NEW.submission_reference_sha256 IS DISTINCT FROM OLD.submission_reference_sha256
                    OR NEW.submission_reference IS DISTINCT FROM OLD.submission_reference
                )
            THEN
                RAISE EXCEPTION 'Escrow action submission reference cannot be replaced';
            END IF;
            RETURN NEW;
        END;
        $action$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER escrow_action_identity_immutable
        BEFORE UPDATE ON escrow_wallet_actions
        FOR EACH ROW EXECUTE FUNCTION prevent_escrow_action_identity_mutation()
    """)


def downgrade() -> None:
    # A schema rollback must never silently erase durable wallet-action history.
    # The CI migration drill uses an empty disposable database; populated action
    # tables require an explicit data-retention/export plan before downgrade.
    has_actions = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM escrow_wallet_actions)")
    ).scalar_one()
    if has_actions:
        raise RuntimeError(
            "Cannot downgrade escrow wallet actions while durable action records exist"
        )

    op.execute(
        "DROP TRIGGER IF EXISTS escrow_action_identity_immutable ON escrow_wallet_actions"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_escrow_action_identity_mutation()")
    op.drop_table("escrow_wallet_actions")
