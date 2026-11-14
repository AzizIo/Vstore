from __future__ import annotations

from app.escrow.models import (
    EscrowChainEvent,
    EscrowDeal,
    EscrowDispute,
    EscrowIdempotencyRecord,
    EscrowListingIntent,
    EscrowObserverCheckpoint,
    EscrowWithdrawal,
)


def test_escrow_tables_are_separate_from_order_and_payment_tables() -> None:
    assert {
        EscrowListingIntent.__tablename__,
        EscrowDeal.__tablename__,
        EscrowChainEvent.__tablename__,
        EscrowDispute.__tablename__,
        EscrowWithdrawal.__tablename__,
        EscrowIdempotencyRecord.__tablename__,
        EscrowObserverCheckpoint.__tablename__,
    } == {
        "escrow_listing_intents",
        "escrow_deals",
        "escrow_chain_events",
        "escrow_disputes",
        "escrow_withdrawals",
        "escrow_idempotency_records",
        "escrow_observer_checkpoints",
    }
    assert EscrowDeal.__table__.c.status.default is not None or EscrowDeal.__table__.c.status.server_default is not None


def test_chain_event_replay_and_idempotency_are_database_constrained() -> None:
    event_uniques = {
        tuple(constraint.columns.keys())
        for constraint in EscrowChainEvent.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("network", "transaction_hash", "event_index") in event_uniques
    idem_uniques = {
        tuple(constraint.columns.keys())
        for constraint in EscrowIdempotencyRecord.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("actor_id", "operation", "idempotency_key") in idem_uniques


def test_listing_deal_and_dispute_have_partial_open_record_indexes() -> None:
    for model, index_name in (
        (EscrowListingIntent, "uq_escrow_listing_open_market_listing"),
        (EscrowDeal, "uq_escrow_deal_open_listing_intent"),
        (EscrowDispute, "uq_escrow_dispute_open_deal"),
    ):
        assert index_name in {index.name for index in model.__table__.indexes}
