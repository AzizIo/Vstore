from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from app.db.models import Base as MarketplaceBase
from app.escrow.models import (
    EscrowBase,
    EscrowChainEvent,
    EscrowDeal,
    EscrowDispute,
    EscrowIdempotencyRecord,
    EscrowListingIntent,
    EscrowObserverCheckpoint,
    EscrowWithdrawal,
    EscrowWalletActionRecord,
    assert_deal_terms_immutable,
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
        EscrowWalletActionRecord.__tablename__,
    } == {
        "escrow_listing_intents",
        "escrow_deals",
        "escrow_chain_events",
        "escrow_disputes",
        "escrow_withdrawals",
        "escrow_idempotency_records",
        "escrow_observer_checkpoints",
        "escrow_wallet_actions",
    }
    status_column = EscrowDeal.__table__.c.status
    assert status_column.default is not None or status_column.server_default is not None
    assert EscrowDeal.__table__.c.deal_salt.unique is None
    assert "uq_escrow_deal_network_salt" in {
        constraint.name for constraint in EscrowDeal.__table__.constraints
    }
    assert EscrowListingIntent.__table__.c.listing_key.unique is True
    assert "collection_address_snapshot" in EscrowDeal.__table__.c
    assert "listing_key_snapshot" in EscrowDeal.__table__.c


def test_chain_event_replay_and_idempotency_are_database_constrained() -> None:
    event_uniques = {
        tuple(constraint.columns.keys())
        for constraint in EscrowChainEvent.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("network", "event_key") in event_uniques
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



def test_escrow_models_use_separate_metadata_registry() -> None:
    marketplace_tables = set(MarketplaceBase.metadata.tables)
    escrow_tables = set(EscrowBase.metadata.tables)

    assert "listings" in marketplace_tables
    assert "users" in marketplace_tables
    assert "escrow_deals" not in marketplace_tables
    assert "escrow_listing_intents" not in marketplace_tables
    assert {"escrow_deals", "escrow_listing_intents"} <= escrow_tables
    assert escrow_tables.isdisjoint(marketplace_tables)


@pytest.mark.parametrize(
    "field",
    [
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
    ],
)
def test_deal_deployment_terms_cannot_be_mutated_after_creation(field: str) -> None:
    deal = EscrowDeal(
        id=uuid4(),
        listing_intent_id=uuid4(),
        marketplace_listing_id=uuid4(),
        listing_key_snapshot="k" * 64,
        seller_id=uuid4(),
        buyer_id=uuid4(),
        buyer_wallet_id=uuid4(),
        network="testnet",
        deal_salt="a" * 64,
        collection_address_snapshot="0:" + "b" * 64,
        item_address="0:" + "c" * 64,
        seller_address_snapshot="0:" + "d" * 64,
        buyer_address_snapshot="0:" + "e" * 64,
        price_amount=Decimal("2.5"),
        price_currency="TON",
        principal_nanotons=2_500_000_000,
        idempotency_key="deal-create-1",
    )
    for immutable_field in (
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
    ):
        set_committed_value(
            deal, immutable_field, getattr(deal, immutable_field)
        )

    replacements = {
        "id": uuid4(),
        "listing_intent_id": uuid4(),
        "marketplace_listing_id": uuid4(),
        "listing_key_snapshot": "l" * 64,
        "seller_id": uuid4(),
        "buyer_id": uuid4(),
        "buyer_wallet_id": uuid4(),
        "network": "mainnet",
        "deal_salt": "f" * 64,
        "collection_address_snapshot": "0:" + "f" * 64,
        "item_address": "0:" + "f" * 64,
        "seller_address_snapshot": "0:" + "f" * 64,
        "buyer_address_snapshot": "0:" + "f" * 64,
        "price_amount": Decimal("2.6"),
        "price_currency": "XTR",
        "principal_nanotons": 2_600_000_000,
        "idempotency_key": "deal-create-2",
    }
    setattr(deal, field, replacements[field])

    with pytest.raises(ValueError, match="Immutable DealEscrow terms"):
        assert_deal_terms_immutable(deal)


def test_deployed_contract_address_cannot_be_replaced() -> None:
    deal = EscrowDeal(
        id=uuid4(),
        listing_intent_id=uuid4(),
        marketplace_listing_id=uuid4(),
        listing_key_snapshot="k" * 64,
        seller_id=uuid4(),
        buyer_id=uuid4(),
        buyer_wallet_id=uuid4(),
        network="testnet",
        deal_salt="a" * 64,
        collection_address_snapshot="0:" + "b" * 64,
        item_address="0:" + "c" * 64,
        seller_address_snapshot="0:" + "d" * 64,
        buyer_address_snapshot="0:" + "e" * 64,
        price_amount=Decimal("2.5"),
        price_currency="TON",
        principal_nanotons=2_500_000_000,
        contract_address="0:" + "a" * 64,
        contract_abi_version="abi-v1",
        idempotency_key="deal-create-1",
    )
    set_committed_value(deal, "contract_address", deal.contract_address)
    set_committed_value(deal, "contract_abi_version", deal.contract_abi_version)
    deal.contract_address = "0:" + "f" * 64

    with pytest.raises(ValueError, match="Immutable DealEscrow terms"):
        assert_deal_terms_immutable(deal)


def test_escrow_metadata_foreign_key_targets_are_resolvable() -> None:
    for table in EscrowBase.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column is not None
