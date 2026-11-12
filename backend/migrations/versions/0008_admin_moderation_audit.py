"""Add listing moderation state and immutable moderation audit log."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_admin_moderation_audit"
down_revision: str | None = "0007_delivery_prepare_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "moderation_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=32), server_default="listing", nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=False),
        sa.Column("after_snapshot", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("target_type = 'listing'", name="ck_moderation_audit_target_type"),
        sa.CheckConstraint(
            "action IN ('approved', 'rejected', 'suspended', 'restored')",
            name="ck_moderation_audit_action",
        ),
        sa.CheckConstraint(
            "reason_code IN ('policy_violation', 'ownership_unverified', "
            "'misleading_metadata', 'duplicate_listing', 'other')",
            name="ck_moderation_audit_reason_code",
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 5 AND 500",
            name="ck_moderation_audit_reason_length",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 8 AND 128",
            name="ck_moderation_audit_idempotency_key_length",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_id"], ["listings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id", "idempotency_key", name="uq_moderation_audit_actor_idempotency"
        ),
    )
    op.create_index("ix_moderation_audit_target_time", "moderation_audit_log",
                    ["target_type", "target_id", "occurred_at"])
    op.create_index("ix_moderation_audit_actor_time", "moderation_audit_log",
                    ["actor_id", "occurred_at"])
    op.execute("""
        CREATE FUNCTION reject_moderation_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'moderation audit log is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_moderation_audit_immutable
        BEFORE UPDATE OR DELETE ON moderation_audit_log
        FOR EACH ROW EXECUTE FUNCTION reject_moderation_audit_mutation()
    """)


def downgrade() -> None:
    bind = op.get_bind()
    suspended = bind.execute(
        sa.text("SELECT count(*) FROM listings WHERE status = 'suspended'")
    ).scalar_one()
    if suspended:
        raise RuntimeError(
            "Cannot downgrade while suspended listings exist; restore or reconcile them first."
        )
    count = bind.execute(sa.text("SELECT count(*) FROM moderation_audit_log")).scalar_one()
    if count:
        raise RuntimeError(
            "Cannot downgrade while moderation audit records exist; preserve the audit trail."
        )
    op.execute("DROP TRIGGER IF EXISTS trg_moderation_audit_immutable ON moderation_audit_log")
    op.execute("DROP FUNCTION IF EXISTS reject_moderation_audit_mutation()")
    op.drop_index("ix_moderation_audit_actor_time", table_name="moderation_audit_log")
    op.drop_index("ix_moderation_audit_target_time", table_name="moderation_audit_log")
    op.drop_table("moderation_audit_log")
