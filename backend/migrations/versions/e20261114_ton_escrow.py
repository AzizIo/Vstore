"""Create isolated, testnet-only TON escrow projection tables.

This migration does not modify orders, payment tables, listings, or delivery state.
The schema stores intents and observed evidence only; it is not a balance oracle.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e20261114_ton_escrow"
down_revision: str | None = "0013_payment_refund_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "escrow_listing_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("marketplace_listing_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("seller_id", sa.Uuid(), nullable=False),
        sa.Column("seller_wallet_id", sa.Uuid(), nullable=False),
        sa.Column("network", sa.String(16), server_default="testnet", nullable=False),
        sa.Column("item_address", sa.String(128), nullable=False),
        sa.Column("listing_key", sa.String(64), nullable=False, unique=True),
        sa.Column("collection_address_snapshot", sa.String(128), nullable=True),
        sa.Column("seller_address_snapshot", sa.String(128), nullable=False),
        sa.Column("price_amount", sa.Numeric(24, 9), nullable=False),
        sa.Column("price_currency", sa.String(8), server_default="TON", nullable=False),
        sa.Column("status", sa.String(24), server_default="intent_only", nullable=False),
        sa.Column("contract_address", sa.String(128), nullable=True),
        sa.Column("contract_abi_version", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("network = 'testnet'", name="ck_escrow_listing_network_testnet"),
        sa.CheckConstraint("price_currency = 'TON'", name="ck_escrow_listing_currency_ton"),
        sa.CheckConstraint("price_amount > 0", name="ck_escrow_listing_price_positive"),
        sa.CheckConstraint(
            "status IN ('intent_only', 'active', 'reserved', 'cancelled', 'manual_review')",
            name="ck_escrow_listing_status",
        ),
        sa.ForeignKeyConstraint(["marketplace_listing_id"], ["listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["nft_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seller_wallet_id"], ["wallets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id", "idempotency_key", name="uq_escrow_listing_seller_idem"),
    )
    op.create_index(
        "uq_escrow_listing_open_market_listing",
        "escrow_listing_intents",
        ["marketplace_listing_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('intent_only', 'active', 'reserved', 'manual_review')"
        ),
    )
    op.create_index(
        "ix_escrow_listing_seller_created", "escrow_listing_intents", ["seller_id", "created_at"]
    )

    op.create_table(
        "escrow_deals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("listing_intent_id", sa.Uuid(), nullable=False),
        sa.Column("marketplace_listing_id", sa.Uuid(), nullable=False),
        sa.Column("seller_id", sa.Uuid(), nullable=False),
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("buyer_wallet_id", sa.Uuid(), nullable=False),
        sa.Column("network", sa.String(16), server_default="testnet", nullable=False),
        sa.Column("deal_salt", sa.String(128), nullable=False),
        sa.Column("collection_address_snapshot", sa.String(128), nullable=True),
        sa.Column("contract_address", sa.String(128), nullable=True),
        sa.Column("contract_abi_version", sa.String(64), nullable=True),
        sa.Column("item_address", sa.String(128), nullable=False),
        sa.Column("seller_address_snapshot", sa.String(128), nullable=False),
        sa.Column("buyer_address_snapshot", sa.String(128), nullable=False),
        sa.Column("price_amount", sa.Numeric(24, 9), nullable=False),
        sa.Column("price_currency", sa.String(8), server_default="TON", nullable=False),
        sa.Column("principal_nanotons", sa.Numeric(30, 0), nullable=False),
        sa.Column("status", sa.String(32), server_default="intent_created", nullable=False),
        sa.Column("last_chain_seqno", sa.BigInteger(), nullable=True),
        sa.Column("last_chain_logical_time", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("network = 'testnet'", name="ck_escrow_deal_network_testnet"),
        sa.CheckConstraint("price_currency = 'TON'", name="ck_escrow_deal_currency_ton"),
        sa.CheckConstraint("price_amount > 0", name="ck_escrow_deal_price_positive"),
        sa.CheckConstraint("principal_nanotons > 0", name="ck_escrow_deal_principal_positive"),
        sa.CheckConstraint("buyer_id <> seller_id", name="ck_escrow_deal_not_self_trade"),
        sa.CheckConstraint(
            "status IN ('intent_created', 'awaiting_nft', 'awaiting_buyer_funds', "
            "'funded_review', 'nft_release_pending', 'delivered_dispute_window', 'disputed', "
            "'nft_return_pending', 'seller_payout_pending', 'buyer_refund_pending', "
            "'settled', 'refunded', 'expired', 'manual_review')",
            name="ck_escrow_deal_status",
        ),
        sa.ForeignKeyConstraint(
            ["listing_intent_id"], ["escrow_listing_intents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["marketplace_listing_id"], ["listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["buyer_wallet_id"], ["wallets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("buyer_id", "idempotency_key", name="uq_escrow_deal_buyer_idem"),
        sa.UniqueConstraint("network", "deal_salt", name="uq_escrow_deal_network_salt"),
    )
    op.create_index(
        "uq_escrow_deal_open_listing_intent",
        "escrow_deals",
        ["listing_intent_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('intent_created', 'awaiting_nft', 'awaiting_buyer_funds', "
            "'funded_review', 'nft_release_pending', 'delivered_dispute_window', "
            "'disputed', 'nft_return_pending', 'seller_payout_pending', "
            "'buyer_refund_pending', 'manual_review')"
        ),
    )
    op.create_index("ix_escrow_deal_buyer_created", "escrow_deals", ["buyer_id", "created_at"])
    op.create_index("ix_escrow_deal_seller_created", "escrow_deals", ["seller_id", "created_at"])

    op.create_table(
        "escrow_chain_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("network", sa.String(16), server_default="testnet", nullable=False),
        sa.Column("event_key", sa.String(512), nullable=False),
        sa.Column("transaction_hash", sa.String(128), nullable=False),
        sa.Column("event_index", sa.BigInteger(), nullable=False),
        sa.Column("message_hash", sa.String(128), nullable=True),
        sa.Column("trace_id", sa.String(128), nullable=True),
        sa.Column("logical_time", sa.BigInteger(), nullable=True),
        sa.Column("phase", sa.String(32), nullable=True),
        sa.Column("attempt_id", sa.String(128), nullable=True),
        sa.Column("query_id", sa.String(128), nullable=True),
        sa.Column("operation_id", sa.String(128), nullable=True),
        sa.Column("deal_salt", sa.String(128), nullable=True),
        sa.Column("account_address", sa.String(128), nullable=True),
        sa.Column("observed_contract_state", sa.String(64), nullable=True),
        sa.Column("contract_state_reconciled", sa.Boolean(), server_default=sa.false(),
            nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("contract_address", sa.String(128), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("source_address", sa.String(128), nullable=True),
        sa.Column("destination_address", sa.String(128), nullable=True),
        sa.Column("item_address", sa.String(128), nullable=True),
        sa.Column("amount_nanotons", sa.Numeric(30, 0), nullable=True),
        sa.Column("masterchain_seqno", sa.BigInteger(), nullable=False),
        sa.Column("finalized", sa.Boolean(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.CheckConstraint("network = 'testnet'", name="ck_escrow_event_network_testnet"),
        sa.CheckConstraint("event_index >= 0", name="ck_escrow_event_index_nonnegative"),
        sa.CheckConstraint(
            "status IN ('pending', 'applied', 'duplicate', 'rejected', "
            "'manual_review', 'unmatched')",
            name="ck_escrow_event_status",
        ),
        sa.CheckConstraint("length(evidence_sha256) = 64", name="ck_escrow_event_evidence_hash"),
        sa.ForeignKeyConstraint(["deal_id"], ["escrow_deals.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("network", "event_key", name="uq_escrow_chain_event_key"),
    )
    op.create_index(
        "ix_escrow_chain_event_deal_created", "escrow_chain_events", ["deal_id", "created_at"]
    )
    op.create_index(
        "ix_escrow_chain_event_seqno", "escrow_chain_events", ["network", "masterchain_seqno"]
    )

    op.create_table(
        "escrow_disputes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("opened_by", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), server_default="requested", nullable=False),
        sa.Column("contract_confirmation_event_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'confirmed', 'resolved_buyer', 'resolved_seller', "
            "'rejected', 'manual_review')",
            name="ck_escrow_dispute_status",
        ),
        sa.CheckConstraint("length(reason) BETWEEN 5 AND 2000", name="ck_escrow_dispute_reason"),
        sa.CheckConstraint(
            "reason_code IN ('not_received', 'wrong_asset', 'payment_mismatch', 'other')",
            name="ck_escrow_dispute_reason_code",
        ),
        sa.ForeignKeyConstraint(["deal_id"], ["escrow_deals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["opened_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["contract_confirmation_event_id"], ["escrow_chain_events.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_escrow_dispute_open_deal", "escrow_disputes", ["deal_id"], unique=True,
        postgresql_where=sa.text("status IN ('requested', 'confirmed', 'manual_review')"),
    )
    op.create_index(
        "ix_escrow_dispute_opened_by", "escrow_disputes", ["opened_by", "created_at"]
    )

    op.create_table(
        "escrow_withdrawals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seller_id", sa.Uuid(), nullable=False),
        sa.Column("wallet_id", sa.Uuid(), nullable=False),
        sa.Column("network", sa.String(16), server_default="testnet", nullable=False),
        sa.Column("recipient_address", sa.String(128), nullable=False),
        sa.Column("amount_nanotons", sa.Numeric(30, 0), nullable=True),
        sa.Column(
            "status", sa.String(32), server_default="blocked_abi_unavailable", nullable=False
        ),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("transaction_hash", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("network = 'testnet'", name="ck_escrow_withdrawal_network_testnet"),
        sa.CheckConstraint(
            "status IN ('blocked_abi_unavailable', 'prepared', 'submitted', "
            "'confirmed', 'failed', 'manual_review')",
            name="ck_escrow_withdrawal_status",
        ),
        sa.CheckConstraint(
            "amount_nanotons IS NULL OR amount_nanotons > 0",
            name="ck_escrow_withdrawal_amount_positive",
        ),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_escrow_withdrawal_seller_created", "escrow_withdrawals", ["seller_id", "created_at"]
    )

    op.create_table(
        "escrow_idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 8 AND 128", name="ck_escrow_idem_key_length"
        ),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_escrow_idem_request_hash"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id", "operation", "idempotency_key", name="uq_escrow_idempotency_actor_operation"
        ),
    )

    op.create_table(
        "escrow_observer_checkpoints",
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("network", sa.String(16), server_default="testnet", nullable=False),
        sa.Column("cursor", sa.String(512), nullable=True),
        sa.Column("last_masterchain_seqno", sa.BigInteger(), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("network = 'testnet'", name="ck_escrow_checkpoint_network_testnet"),
        sa.PrimaryKeyConstraint("checkpoint_id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO escrow_observer_checkpoints "
            "(checkpoint_id, network, cursor, last_masterchain_seqno, updated_at) "
            "VALUES ('ton-testnet-escrow', 'testnet', NULL, NULL, now())"
        )
    )


def downgrade() -> None:
    op.drop_table("escrow_observer_checkpoints")
    op.drop_table("escrow_idempotency_records")
    op.drop_index("ix_escrow_withdrawal_seller_created", table_name="escrow_withdrawals")
    op.drop_table("escrow_withdrawals")
    op.drop_index("ix_escrow_dispute_opened_by", table_name="escrow_disputes")
    op.drop_index("uq_escrow_dispute_open_deal", table_name="escrow_disputes")
    op.drop_table("escrow_disputes")
    op.drop_index("ix_escrow_chain_event_seqno", table_name="escrow_chain_events")
    op.drop_index("ix_escrow_chain_event_deal_created", table_name="escrow_chain_events")
    op.drop_table("escrow_chain_events")
    op.drop_index("ix_escrow_deal_seller_created", table_name="escrow_deals")
    op.drop_index("ix_escrow_deal_buyer_created", table_name="escrow_deals")
    op.drop_index("uq_escrow_deal_open_listing_intent", table_name="escrow_deals")
    op.drop_table("escrow_deals")
    op.drop_index("ix_escrow_listing_seller_created", table_name="escrow_listing_intents")
    op.drop_index("uq_escrow_listing_open_market_listing", table_name="escrow_listing_intents")
    op.drop_table("escrow_listing_intents")
