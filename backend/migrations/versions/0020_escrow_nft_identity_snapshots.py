"""Persist proof-anchored TEP-62 identity snapshots for escrow listings and deals.

Identity evidence is immutable and contains no signing material. A downgrade must
not discard evidence already used to authorize marketplace reservation or observer
terminal-owner reconciliation.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_escrow_nft_identity"
down_revision: str | None = "0019_escrow_deployment_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "escrow_listing_intents",
        sa.Column("nft_identity_snapshot_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "escrow_listing_intents",
        sa.Column("nft_identity_snapshot_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("nft_identity_snapshot_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "escrow_deals",
        sa.Column("nft_identity_snapshot_sha256", sa.String(length=64), nullable=True),
    )

    for table, prefix in (
        ("escrow_listing_intents", "ck_escrow_listing_nft_identity_snapshot_pair"),
        ("escrow_deals", "ck_escrow_deal_nft_identity_snapshot_pair"),
    ):
        op.create_check_constraint(
            prefix,
            table,
            "("
            "nft_identity_snapshot_json IS NULL AND nft_identity_snapshot_sha256 IS NULL"
            ") OR ("
            "nft_identity_snapshot_json IS NOT NULL "
            "AND nft_identity_snapshot_sha256 IS NOT NULL "
            "AND nft_identity_snapshot_sha256 ~ '^[0-9a-f]{64}$' "
            "AND nft_identity_snapshot_json::jsonb ? 'evidence_sha256' "
            "AND nft_identity_snapshot_json::jsonb ->> 'evidence_sha256' "
            "= nft_identity_snapshot_sha256"
            ")",
        )

    # Keep PL/pgSQL bodies dollar-quoted; a lone "$" is invalid syntax.
    op.get_bind().exec_driver_sql(
        """
        CREATE FUNCTION guard_escrow_nft_identity_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $escrow_deal_guard$$
        BEGIN
            IF (
                NEW.nft_identity_snapshot_json::jsonb
                    IS DISTINCT FROM OLD.nft_identity_snapshot_json::jsonb
                OR NEW.nft_identity_snapshot_sha256
                    IS DISTINCT FROM OLD.nft_identity_snapshot_sha256
                OR NEW.network IS DISTINCT FROM OLD.network
                OR NEW.marketplace_listing_id IS DISTINCT FROM OLD.marketplace_listing_id
                OR NEW.seller_id IS DISTINCT FROM OLD.seller_id
                OR NEW.item_address IS DISTINCT FROM OLD.item_address
                OR NEW.collection_address_snapshot
                    IS DISTINCT FROM OLD.collection_address_snapshot
                OR NEW.seller_address_snapshot
                    IS DISTINCT FROM OLD.seller_address_snapshot
                OR NEW.price_amount IS DISTINCT FROM OLD.price_amount
                OR NEW.price_currency IS DISTINCT FROM OLD.price_currency
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
            ) THEN
                RAISE EXCEPTION 'Persisted escrow NFT identity and bound terms are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.get_bind().exec_driver_sql(
        """
        CREATE FUNCTION guard_escrow_listing_nft_identity_terms()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF (
                NEW.asset_id IS DISTINCT FROM OLD.asset_id
                OR NEW.seller_wallet_id IS DISTINCT FROM OLD.seller_wallet_id
                OR NEW.listing_key IS DISTINCT FROM OLD.listing_key
            ) THEN
                RAISE EXCEPTION 'Persisted escrow listing NFT identity binding is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_escrow_listing_nft_identity_binding_immutable
        BEFORE UPDATE ON escrow_listing_intents
        FOR EACH ROW EXECUTE FUNCTION guard_escrow_listing_nft_identity_terms()
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_escrow_listing_nft_identity_immutable
        BEFORE UPDATE ON escrow_listing_intents
        FOR EACH ROW EXECUTE FUNCTION guard_escrow_nft_identity_snapshot()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_escrow_deal_nft_identity_immutable
        BEFORE UPDATE ON escrow_deals
        FOR EACH ROW EXECUTE FUNCTION guard_escrow_nft_identity_snapshot()
        """
    )

    op.get_bind().exec_driver_sql(
        """
        CREATE FUNCTION guard_escrow_deal_nft_identity_terms()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $
        BEGIN
            IF (
                NEW.listing_intent_id IS DISTINCT FROM OLD.listing_intent_id
                OR NEW.listing_key_snapshot IS DISTINCT FROM OLD.listing_key_snapshot
                OR NEW.buyer_id IS DISTINCT FROM OLD.buyer_id
                OR NEW.buyer_wallet_id IS DISTINCT FROM OLD.buyer_wallet_id
                OR NEW.buyer_address_snapshot IS DISTINCT FROM OLD.buyer_address_snapshot
                OR NEW.deal_salt IS DISTINCT FROM OLD.deal_salt
                OR NEW.principal_nanotons IS DISTINCT FROM OLD.principal_nanotons
                OR (
                    OLD.contract_address IS NOT NULL
                    AND NEW.contract_address IS DISTINCT FROM OLD.contract_address
                )
                OR (
                    OLD.contract_abi_version IS NOT NULL
                    AND NEW.contract_abi_version IS DISTINCT FROM OLD.contract_abi_version
                )
            ) THEN
                RAISE EXCEPTION 'Persisted escrow deal NFT identity and bound terms are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_escrow_deal_nft_identity_terms_immutable
        BEFORE UPDATE ON escrow_deals
        FOR EACH ROW EXECUTE FUNCTION guard_escrow_deal_nft_identity_terms()
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_identity_snapshots = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM escrow_listing_intents "
            "WHERE nft_identity_snapshot_json IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM escrow_deals "
            "WHERE nft_identity_snapshot_json IS NOT NULL)"
        )
    ).scalar_one()
    if has_identity_snapshots:
        raise RuntimeError(
            "Cannot downgrade while escrow NFT identity evidence is referenced by intents or deals"
        )

    op.execute(
        "DROP TRIGGER IF EXISTS trg_escrow_listing_nft_identity_binding_immutable "
        "ON escrow_listing_intents"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_escrow_listing_nft_identity_terms()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_escrow_listing_nft_identity_immutable ON escrow_listing_intents"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_escrow_deal_nft_identity_immutable ON escrow_deals"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_escrow_deal_nft_identity_terms_immutable ON escrow_deals"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_escrow_deal_nft_identity_terms()")
    op.execute("DROP FUNCTION IF EXISTS guard_escrow_nft_identity_snapshot()")
    op.drop_constraint(
        "ck_escrow_deal_nft_identity_snapshot_pair", "escrow_deals", type_="check"
    )
    op.drop_constraint(
        "ck_escrow_listing_nft_identity_snapshot_pair",
        "escrow_listing_intents",
        type_="check",
    )
    op.drop_column("escrow_deals", "nft_identity_snapshot_sha256")
    op.drop_column("escrow_deals", "nft_identity_snapshot_json")
    op.drop_column("escrow_listing_intents", "nft_identity_snapshot_sha256")
    op.drop_column("escrow_listing_intents", "nft_identity_snapshot_json")
