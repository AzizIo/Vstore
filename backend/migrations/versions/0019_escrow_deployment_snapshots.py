"""Persist immutable DealEscrow deployment/getter snapshots and exact unsigned BOCs.

No wallet signing or transaction broadcast is enabled by this migration. The snapshot
and action payloads are durable preparation evidence and are immutable after capture.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_escrow_deployment_snapshots"
down_revision: str | None = "0018_payment_intent_api_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "escrow_deals",
        sa.Column("deployment_snapshot_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("deployment_snapshot_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("deployment_snapshot_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("deployment_snapshot_source", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("deployment_snapshot_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("getter_snapshot_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("getter_snapshot_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("getter_snapshot_masterchain_seqno", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("getter_snapshot_block_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("getter_snapshot_provider", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("getter_snapshot_observed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "escrow_wallet_actions",
        sa.Column("unsigned_payload_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "escrow_wallet_actions",
        sa.Column("unsigned_payload_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "escrow_wallet_actions",
        sa.Column("unsigned_bocs_json", sa.JSON(), nullable=True),
    )

    op.create_check_constraint(
        "ck_escrow_deal_deployment_snapshot_pair",
        "escrow_deals",
        "("
        "deployment_snapshot_json IS NULL AND deployment_snapshot_sha256 IS NULL "
        "AND deployment_snapshot_version IS NULL AND deployment_snapshot_source IS NULL"
        ") OR ("
        "deployment_snapshot_json IS NOT NULL AND length(deployment_snapshot_sha256) = 64 "
        "AND deployment_snapshot_version > 0 "
        "AND length(deployment_snapshot_source) BETWEEN 1 AND 128"
        ")",
    )
    op.create_check_constraint(
        "ck_escrow_deal_getter_snapshot_pair",
        "escrow_deals",
        "("
        "getter_snapshot_json IS NULL AND getter_snapshot_sha256 IS NULL "
        "AND getter_snapshot_masterchain_seqno IS NULL AND getter_snapshot_block_hash IS NULL "
        "AND getter_snapshot_provider IS NULL AND getter_snapshot_observed_at IS NULL"
        ") OR ("
        "getter_snapshot_json IS NOT NULL AND length(getter_snapshot_sha256) = 64 "
        "AND getter_snapshot_masterchain_seqno > 0 "
        "AND length(getter_snapshot_block_hash) = 64 "
        "AND length(getter_snapshot_provider) BETWEEN 1 AND 128 "
        "AND getter_snapshot_observed_at IS NOT NULL"
        ")",
    )
    op.create_check_constraint(
        "ck_escrow_action_unsigned_payload_pair",
        "escrow_wallet_actions",
        "("
        "unsigned_payload_json IS NULL AND unsigned_payload_sha256 IS NULL"
        ") OR ("
        "unsigned_payload_json IS NOT NULL AND length(unsigned_payload_sha256) = 64"
        ")",
    )
    op.create_check_constraint(
        "ck_escrow_action_unsigned_bocs_pair",
        "escrow_wallet_actions",
        "("
        "unsigned_bocs_json IS NULL AND unsigned_boc_sha256 IS NULL AND unsigned_boc_ref IS NULL"
        ") OR ("
        "unsigned_bocs_json IS NOT NULL AND length(unsigned_boc_sha256) = 64 "
        "AND length(unsigned_boc_ref) BETWEEN 1 AND 512"
        ")",
    )

    op.execute(
        """
        CREATE FUNCTION guard_escrow_deployment_and_getter_snapshots()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.deployment_snapshot_json IS NOT NULL AND ROW(
                NEW.deployment_snapshot_json,
                NEW.deployment_snapshot_sha256,
                NEW.deployment_snapshot_version,
                NEW.deployment_snapshot_source
            ) IS DISTINCT FROM ROW(
                OLD.deployment_snapshot_json,
                OLD.deployment_snapshot_sha256,
                OLD.deployment_snapshot_version,
                OLD.deployment_snapshot_source
            ) THEN
                RAISE EXCEPTION 'DealEscrow deployment snapshot is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF OLD.getter_snapshot_masterchain_seqno IS NOT NULL
                AND NEW.getter_snapshot_masterchain_seqno
                    < OLD.getter_snapshot_masterchain_seqno
            THEN
                RAISE EXCEPTION 'DealEscrow getter snapshot cannot move backwards'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF OLD.getter_snapshot_masterchain_seqno IS NOT NULL
                AND NEW.getter_snapshot_masterchain_seqno
                    = OLD.getter_snapshot_masterchain_seqno
                AND ROW(
                    NEW.getter_snapshot_json,
                    NEW.getter_snapshot_sha256,
                    NEW.getter_snapshot_block_hash,
                    NEW.getter_snapshot_provider
                ) IS DISTINCT FROM ROW(
                    OLD.getter_snapshot_json,
                    OLD.getter_snapshot_sha256,
                    OLD.getter_snapshot_block_hash,
                    OLD.getter_snapshot_provider
                )
            THEN
                RAISE EXCEPTION 'DealEscrow getter snapshot conflicts at the same masterchain block'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_escrow_deployment_getter_snapshot_guard
        BEFORE UPDATE ON escrow_deals
        FOR EACH ROW EXECUTE FUNCTION guard_escrow_deployment_and_getter_snapshots()
        """
    )

    op.execute(
        """
        CREATE FUNCTION guard_escrow_unsigned_action_payload()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.unsigned_payload_json IS NOT NULL AND ROW(
                NEW.unsigned_payload_json,
                NEW.unsigned_payload_sha256,
                NEW.unsigned_bocs_json,
                NEW.unsigned_boc_sha256,
                NEW.unsigned_boc_ref
            ) IS DISTINCT FROM ROW(
                OLD.unsigned_payload_json,
                OLD.unsigned_payload_sha256,
                OLD.unsigned_bocs_json,
                OLD.unsigned_boc_sha256,
                OLD.unsigned_boc_ref
            ) THEN
                RAISE EXCEPTION 'Persisted unsigned escrow payload and BOCs cannot be replaced'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_escrow_unsigned_action_payload_guard
        BEFORE UPDATE ON escrow_wallet_actions
        FOR EACH ROW EXECUTE FUNCTION guard_escrow_unsigned_action_payload()
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_snapshots = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM escrow_deals "
            "WHERE deployment_snapshot_json IS NOT NULL OR getter_snapshot_json IS NOT NULL)"
        )
    ).scalar_one()
    has_payloads = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM escrow_wallet_actions "
            "WHERE unsigned_payload_json IS NOT NULL OR unsigned_bocs_json IS NOT NULL)"
        )
    ).scalar_one()
    if has_snapshots or has_payloads:
        raise RuntimeError(
            "Cannot downgrade while immutable escrow snapshots or unsigned BOC evidence exists"
        )

    op.execute(
        "DROP TRIGGER IF EXISTS trg_escrow_unsigned_action_payload_guard ON escrow_wallet_actions"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_escrow_unsigned_action_payload()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_escrow_deployment_getter_snapshot_guard ON escrow_deals"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_escrow_deployment_and_getter_snapshots()")
    op.drop_constraint(
        "ck_escrow_action_unsigned_bocs_pair", "escrow_wallet_actions", type_="check"
    )
    op.drop_constraint(
        "ck_escrow_action_unsigned_payload_pair", "escrow_wallet_actions", type_="check"
    )
    op.drop_constraint(
        "ck_escrow_deal_getter_snapshot_pair", "escrow_deals", type_="check"
    )
    op.drop_constraint(
        "ck_escrow_deal_deployment_snapshot_pair", "escrow_deals", type_="check"
    )
    for column in (
        "unsigned_bocs_json",
        "unsigned_payload_sha256",
        "unsigned_payload_json",
    ):
        op.drop_column("escrow_wallet_actions", column)
    for column in (
        "getter_snapshot_observed_at",
        "getter_snapshot_provider",
        "getter_snapshot_block_hash",
        "getter_snapshot_masterchain_seqno",
        "getter_snapshot_sha256",
        "getter_snapshot_json",
        "deployment_snapshot_error_code",
        "deployment_snapshot_source",
        "deployment_snapshot_version",
        "deployment_snapshot_sha256",
        "deployment_snapshot_json",
    ):
        op.drop_column("escrow_deals", column)
