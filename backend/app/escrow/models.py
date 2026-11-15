"""SQLAlchemy projection models for the isolated TON escrow domain.

These rows are durable intents and indexed evidence, not proof of chain ownership
or balances. Chain-derived states are advanced only by the escrow observer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy import event as sa_event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.models import Listing, NFTAsset, TimestampMixin, User, Wallet


class EscrowBase(DeclarativeBase):
    """Keep escrow table metadata isolated from the marketplace model registry."""


class EscrowListingIntent(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_listing_intents"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_listing_network_testnet"),
        CheckConstraint("price_currency = 'TON'", name="ck_escrow_listing_currency_ton"),
        CheckConstraint("price_amount > 0", name="ck_escrow_listing_price_positive"),
        CheckConstraint(
            "status IN ('intent_only', 'active', 'reserved', 'cancelled', 'manual_review')",
            name="ck_escrow_listing_status",
        ),
        UniqueConstraint("seller_id", "idempotency_key", name="uq_escrow_listing_seller_idem"),
        Index(
            "uq_escrow_listing_open_market_listing",
            "marketplace_listing_id",
            unique=True,
            postgresql_where=text(
                "status IN ('intent_only', 'active', 'reserved', 'manual_review')"
            ),
        ),
        Index("ix_escrow_listing_seller_created", "seller_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    marketplace_listing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(Listing.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(NFTAsset.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    seller_wallet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(Wallet.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    item_address: Mapped[str] = mapped_column(String(128), nullable=False)
    listing_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    collection_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    seller_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(24, 9), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(8), server_default="TON", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), server_default="intent_only", nullable=False
    )
    contract_address: Mapped[str | None] = mapped_column(String(128))
    contract_abi_version: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)


class EscrowDeal(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_deals"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_deal_network_testnet"),
        CheckConstraint("price_currency = 'TON'", name="ck_escrow_deal_currency_ton"),
        CheckConstraint("price_amount > 0", name="ck_escrow_deal_price_positive"),
        CheckConstraint("principal_nanotons > 0", name="ck_escrow_deal_principal_positive"),
        CheckConstraint(
            "status IN ('intent_created', 'awaiting_nft', 'awaiting_buyer_funds', "
            "'funded_review', 'nft_release_pending', 'delivered_dispute_window', 'disputed', "
            "'nft_return_pending', 'seller_payout_pending', 'buyer_refund_pending', "
            "'settled', 'refunded', 'expired', 'manual_review')",
            name="ck_escrow_deal_status",
        ),
        CheckConstraint("buyer_id <> seller_id", name="ck_escrow_deal_not_self_trade"),
        UniqueConstraint("buyer_id", "idempotency_key", name="uq_escrow_deal_buyer_idem"),
        UniqueConstraint("network", "deal_salt", name="uq_escrow_deal_network_salt"),
        Index(
            "uq_escrow_deal_open_listing_intent",
            "listing_intent_id",
            unique=True,
            postgresql_where=text(
                "status IN ('intent_created', 'awaiting_nft', 'awaiting_buyer_funds', "
                "'funded_review', 'nft_release_pending', 'delivered_dispute_window', "
                "'disputed', 'nft_return_pending', 'seller_payout_pending', "
                "'buyer_refund_pending', 'manual_review')"
            ),
        ),
        Index("ix_escrow_deal_buyer_created", "buyer_id", "created_at"),
        Index("ix_escrow_deal_seller_created", "seller_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("escrow_listing_intents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    marketplace_listing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(Listing.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    listing_key_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    buyer_wallet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(Wallet.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    deal_salt: Mapped[str] = mapped_column(String(128), nullable=False)
    collection_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_address: Mapped[str | None] = mapped_column(String(128))
    contract_abi_version: Mapped[str | None] = mapped_column(String(64))
    item_address: Mapped[str] = mapped_column(String(128), nullable=False)
    seller_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    buyer_address_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(24, 9), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(8), server_default="TON", nullable=False)
    principal_nanotons: Mapped[Decimal] = mapped_column(Numeric(30, 0), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), server_default="intent_created", nullable=False
    )
    last_chain_seqno: Mapped[int | None] = mapped_column(BigInteger)
    last_chain_logical_time: Mapped[int | None] = mapped_column(BigInteger)
    # Frozen deployment inputs are canonical JSON with an independently checked hash.
    # They contain no signing material and can only be initialized once.
    deployment_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    deployment_snapshot_sha256: Mapped[str | None] = mapped_column(String(64))
    deployment_snapshot_version: Mapped[int | None] = mapped_column(Integer)
    deployment_snapshot_source: Mapped[str | None] = mapped_column(String(128))
    deployment_snapshot_error_code: Mapped[str | None] = mapped_column(String(64))
    # Getter state is an independently verified, monotonic observation at an MC block.
    getter_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    getter_snapshot_sha256: Mapped[str | None] = mapped_column(String(64))
    getter_snapshot_masterchain_seqno: Mapped[int | None] = mapped_column(BigInteger)
    getter_snapshot_block_hash: Mapped[str | None] = mapped_column(String(64))
    getter_snapshot_provider: Mapped[str | None] = mapped_column(String(128))
    getter_snapshot_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)


_IMMUTABLE_DEAL_TERMS = (
    "id",
    "listing_intent_id",
    "marketplace_listing_id",
    "listing_key_snapshot",
    "seller_id",
    "buyer_id",
    "buyer_wallet_id",
    "network",
    "deal_salt",
    "collection_address_snapshot",
    "item_address",
    "seller_address_snapshot",
    "buyer_address_snapshot",
    "price_amount",
    "price_currency",
    "principal_nanotons",
    "idempotency_key",
    "deployment_snapshot_json",
    "deployment_snapshot_sha256",
    "deployment_snapshot_version",
    "deployment_snapshot_source",
)


def assert_deal_terms_immutable(target: EscrowDeal) -> None:
    state = sa_inspect(target)
    changed = [
        name for name in _IMMUTABLE_DEAL_TERMS
        if state.attrs[name].history.has_changes()
    ]
    for name in ("contract_address", "contract_abi_version"):
        history = state.attrs[name].history
        if history.has_changes() and any(value is not None for value in history.deleted):
            changed.append(name)

    seq_history = state.attrs["getter_snapshot_masterchain_seqno"].history
    if seq_history.has_changes() and seq_history.deleted:
        previous_seqno = seq_history.deleted[0]
        new_seqno = target.getter_snapshot_masterchain_seqno
        if previous_seqno is not None and new_seqno is not None:
            if new_seqno < previous_seqno:
                changed.append("getter_snapshot_masterchain_seqno_regressed")
            elif new_seqno == previous_seqno:
                for name in (
                    "getter_snapshot_json",
                    "getter_snapshot_sha256",
                    "getter_snapshot_block_hash",
                    "getter_snapshot_provider",
                    "getter_snapshot_observed_at",
                ):
                    if state.attrs[name].history.has_changes():
                        changed.append(f"{name}_changed_at_same_seqno")

    if changed:
        fields = ", ".join(sorted(set(changed)))
        raise ValueError(f"Immutable DealEscrow terms cannot be changed: {fields}")


def _before_escrow_deal_update(
    _mapper: object,
    _connection: object,
    target: EscrowDeal,
) -> None:
    assert_deal_terms_immutable(target)

sa_event.listen(EscrowDeal, "before_update", _before_escrow_deal_update)


class EscrowChainEvent(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_chain_events"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_event_network_testnet"),
        CheckConstraint("event_index >= 0", name="ck_escrow_event_index_nonnegative"),
        CheckConstraint(
            "status IN ('pending', 'applied', 'duplicate', 'rejected', "
            "'manual_review', 'unmatched')",
            name="ck_escrow_event_status",
        ),
        CheckConstraint(
            "length(evidence_sha256) = 64", name="ck_escrow_event_evidence_hash"
        ),
        UniqueConstraint("network", "event_key", name="uq_escrow_chain_event_key"),
        Index("ix_escrow_chain_event_deal_created", "deal_id", "created_at"),
        Index("ix_escrow_chain_event_seqno", "network", "masterchain_seqno"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    event_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_hash: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[str | None] = mapped_column(String(128))
    logical_time: Mapped[int | None] = mapped_column(BigInteger)
    phase: Mapped[str | None] = mapped_column(String(32))
    attempt_id: Mapped[str | None] = mapped_column(String(128))
    query_id: Mapped[str | None] = mapped_column(String(128))
    operation_id: Mapped[str | None] = mapped_column(String(128))
    deal_salt: Mapped[str | None] = mapped_column(String(128))
    account_address: Mapped[str | None] = mapped_column(String(128))
    observed_contract_state: Mapped[str | None] = mapped_column(String(64))
    contract_state_reconciled: Mapped[bool] = mapped_column(
        Boolean, nullable=False,
        server_default=text("false")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_address: Mapped[str] = mapped_column(String(128), nullable=False)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("escrow_deals.id", ondelete="RESTRICT")
    )
    source_address: Mapped[str | None] = mapped_column(String(128))
    destination_address: Mapped[str | None] = mapped_column(String(128))
    item_address: Mapped[str | None] = mapped_column(String(128))
    collection_address: Mapped[str | None] = mapped_column(String(128))
    amount_nanotons: Mapped[Decimal | None] = mapped_column(Numeric(30, 0))
    masterchain_seqno: Mapped[int] = mapped_column(BigInteger, nullable=False)
    finalized: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))


class EscrowDispute(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_disputes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'confirmed', 'resolved_buyer', 'resolved_seller', "
            "'rejected', 'manual_review')",
            name="ck_escrow_dispute_status",
        ),
        CheckConstraint("length(reason) BETWEEN 5 AND 2000", name="ck_escrow_dispute_reason"),
        CheckConstraint(
            "reason_code IN ('not_received', 'wrong_asset', 'payment_mismatch', 'other')",
            name="ck_escrow_dispute_reason_code",
        ),
        Index(
            "uq_escrow_dispute_open_deal",
            "deal_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'confirmed', 'manual_review')"),
        ),
        Index("ix_escrow_dispute_opened_by", "opened_by", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("escrow_deals.id", ondelete="RESTRICT"), nullable=False
    )
    opened_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), server_default="requested", nullable=False)
    contract_confirmation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("escrow_chain_events.id", ondelete="RESTRICT")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EscrowWithdrawal(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_withdrawals"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_withdrawal_network_testnet"),
        CheckConstraint(
            "status IN ('blocked_abi_unavailable', 'prepared', 'submitted', 'confirmed', "
            "'failed', 'manual_review')",
            name="ck_escrow_withdrawal_status",
        ),
        CheckConstraint(
            "amount_nanotons IS NULL OR amount_nanotons > 0",
            name="ck_escrow_withdrawal_amount_positive",
        ),
        Index("ix_escrow_withdrawal_seller_created", "seller_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(Wallet.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    recipient_address: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_nanotons: Mapped[Decimal | None] = mapped_column(Numeric(30, 0))
    status: Mapped[str] = mapped_column(
        String(32), server_default="blocked_abi_unavailable", nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_hash: Mapped[str | None] = mapped_column(String(128))


class EscrowIdempotencyRecord(TimestampMixin, EscrowBase):
    __tablename__ = "escrow_idempotency_records"
    __table_args__ = (
        CheckConstraint(
            "length(idempotency_key) BETWEEN 8 AND 128",
            name="ck_escrow_idem_key_length",
        ),
        CheckConstraint("length(request_sha256) = 64", name="ck_escrow_idem_request_hash"),
        UniqueConstraint(
            "actor_id", "operation", "idempotency_key", name="uq_escrow_idempotency_actor_operation"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))


class EscrowWalletActionRecord(TimestampMixin, EscrowBase):
    """Durable wallet action intent; submitted references remain untrusted hints."""

    __tablename__ = "escrow_wallet_actions"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_action_network_testnet"),
        CheckConstraint(
            "status IN ('pending', 'prepared', 'submitted', 'ambiguous', 'finalized', "
            "'failed', 'manual_review', 'blocked_abi')",
            name="ck_escrow_action_status",
        ),
        CheckConstraint(
            "(status <> 'finalized' "
            "AND finalized_transaction_hash IS NULL "
            "AND finality_masterchain_seqno IS NULL "
            "AND finality_masterchain_block_hash IS NULL "
            "AND finality_proof_sha256 IS NULL "
            "AND finality_provider IS NULL) OR ("
            "finalized_transaction_hash IS NOT NULL "
            "AND unsigned_payload_json IS NOT NULL "
            "AND unsigned_bocs_json IS NOT NULL "
            "AND length(finalized_transaction_hash) = 64 "
            "AND finality_masterchain_seqno IS NOT NULL "
            "AND finality_masterchain_seqno > 0 "
            "AND finality_masterchain_block_hash IS NOT NULL "
            "AND length(finality_masterchain_block_hash) = 64 "
            "AND finality_proof_sha256 IS NOT NULL "
            "AND length(finality_proof_sha256) = 64 "
            "AND finality_provider IS NOT NULL "
            "AND length(finality_provider) BETWEEN 1 AND 128)",
            name="ck_escrow_action_finality_pair",
        ),
        CheckConstraint("length(idempotency_key) BETWEEN 8 AND 128",
            name="ck_escrow_action_idempotency_length"),
        CheckConstraint("length(request_sha256) = 64", name="ck_escrow_action_request_hash"),
        CheckConstraint(
            "unsigned_boc_sha256 IS NULL OR length(unsigned_boc_sha256) = 64",
            name="ck_escrow_action_boc_hash"),
        CheckConstraint(
            "(unsigned_boc_sha256 IS NULL AND unsigned_boc_ref IS NULL) OR "
            "(unsigned_boc_sha256 IS NOT NULL AND unsigned_boc_ref IS NOT NULL)",
            name="ck_escrow_action_boc_pair"),
        CheckConstraint(
            "submission_reference_sha256 IS NULL OR length(submission_reference_sha256) = 64",
            name="ck_escrow_action_submission_hash"),
        CheckConstraint(
            "(submission_reference IS NULL AND submission_reference_sha256 IS NULL) OR "
            "(submission_reference IS NOT NULL AND submission_reference_sha256 IS NOT NULL "
            "AND length(submission_reference) BETWEEN 1 AND 512)",
            name="ck_escrow_action_submission_pair"),
        CheckConstraint("attempt_count >= 0", name="ck_escrow_action_attempt_count"),
        UniqueConstraint(
            "actor_id", "action_type", "idempotency_key",
            name="uq_escrow_action_actor_type_idem",
        ),
        Index("ix_escrow_action_deal_status", "deal_id", "status"),
        Index("ix_escrow_action_retry", "status", "next_retry_at"),
        Index(
            "uq_escrow_action_submission_reference",
            "network", "submission_reference_sha256", unique=True,
            postgresql_where=text("submission_reference_sha256 IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("escrow_deals.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), server_default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    attempt_id: Mapped[str | None] = mapped_column(String(128))
    query_id: Mapped[str | None] = mapped_column(String(128))
    unsigned_boc_sha256: Mapped[str | None] = mapped_column(String(64))
    unsigned_boc_ref: Mapped[str | None] = mapped_column(String(512))
    unsigned_payload_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    unsigned_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    unsigned_bocs_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    # Independent finality evidence is separate from the untrusted client reference.
    finalized_transaction_hash: Mapped[str | None] = mapped_column(String(128))
    finality_masterchain_seqno: Mapped[int | None] = mapped_column(BigInteger)
    finality_masterchain_block_hash: Mapped[str | None] = mapped_column(String(64))
    finality_proof_sha256: Mapped[str | None] = mapped_column(String(64))
    finality_provider: Mapped[str | None] = mapped_column(String(128))
    submission_reference: Mapped[str | None] = mapped_column(String(512))
    submission_reference_sha256: Mapped[str | None] = mapped_column(String(64))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))


class EscrowObserverCheckpoint(EscrowBase):
    __tablename__ = "escrow_observer_checkpoints"
    __table_args__ = (
        CheckConstraint("network = 'testnet'", name="ck_escrow_checkpoint_network_testnet"),
    )

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    network: Mapped[str] = mapped_column(String(16), server_default="testnet", nullable=False)
    cursor: Mapped[str | None] = mapped_column(Text)
    last_masterchain_seqno: Mapped[int | None] = mapped_column(BigInteger)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
