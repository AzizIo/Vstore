"""Add append-only audit events for administrative user access changes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_admin_user_management"
down_revision: str | None = "0013_payment_refund_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index("ix_users_created_at_id", "users", ["created_at", "id"])
    op.create_index("ix_orders_created_at_id", "orders", ["created_at", "id"])
    op.create_table(
        "admin_user_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=False),
        sa.Column("after_snapshot", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('blocked', 'unblocked')",
            name="ck_admin_user_audit_action",
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 5 AND 500",
            name="ck_admin_user_audit_reason_length",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 8 AND 128",
            name="ck_admin_user_audit_idempotency_key_length",
        ),
        sa.CheckConstraint(
            "actor_id <> target_user_id",
            name="ck_admin_user_audit_not_self",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id",
            "idempotency_key",
            name="uq_admin_user_audit_actor_idempotency",
        ),
    )
    op.create_index(
        "ix_admin_user_audit_target_time",
        "admin_user_audit_log",
        ["target_user_id", "occurred_at"],
    )
    op.create_index(
        "ix_admin_user_audit_actor_time",
        "admin_user_audit_log",
        ["actor_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_admin_user_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'admin user audit log is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admin_user_audit_immutable
        BEFORE UPDATE OR DELETE ON admin_user_audit_log
        FOR EACH ROW EXECUTE FUNCTION reject_admin_user_audit_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admin_user_audit_no_truncate
        BEFORE TRUNCATE ON admin_user_audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION reject_admin_user_audit_mutation()
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text("SELECT count(*) FROM admin_user_audit_log")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Cannot downgrade while user-management audit records exist; preserve the audit trail."
        )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admin_user_audit_no_truncate ON admin_user_audit_log"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admin_user_audit_immutable ON admin_user_audit_log"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_admin_user_audit_mutation()")
    op.drop_index("ix_admin_user_audit_actor_time", table_name="admin_user_audit_log")
    op.drop_index("ix_admin_user_audit_target_time", table_name="admin_user_audit_log")
    op.drop_table("admin_user_audit_log")
    op.drop_index("ix_orders_created_at_id", table_name="orders")
    op.drop_index("ix_users_created_at_id", table_name="users")
