from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.escrow import _listing_actions, _prepare_action, router
from app.escrow.contracts import EscrowWalletAction
from app.escrow.schemas import (
    EscrowDealCreate,
    EscrowDealResponse,
    EscrowListingIntentCreate,
    EscrowListingIntentResponse,
    EscrowNftProjection,
    EscrowPageResponse,
)


def test_frontend_listing_and_deal_create_inputs_match_backend_contract() -> None:
    listing = EscrowListingIntentCreate(
        asset_id=uuid4(), seller_wallet_id=uuid4(), price_nano="2500000000",
    )
    assert listing.model_dump(mode="json")["price_nano"] == "2500000000"

    deal = EscrowDealCreate(listing_id=uuid4(), buyer_wallet_id=uuid4())
    assert "listing_id" in deal.model_dump(mode="json")
    assert "listing_intent_id" not in deal.model_dump(mode="json")

    with pytest.raises(ValidationError):
        EscrowListingIntentCreate(
            asset_id=uuid4(), seller_wallet_id=uuid4(), price_nano="2.5",
        )
    with pytest.raises(ValidationError):
        EscrowDealCreate(listing_intent_id=uuid4(), buyer_wallet_id=uuid4())


def test_listing_response_serializes_frontend_projection_fields() -> None:
    now = datetime.now(UTC)
    response = EscrowListingIntentResponse(
        id=uuid4(), listing_key="a" * 64, seller_id=uuid4(),
        state="intent_only", network="testnet",
        nft=EscrowNftProjection(
            asset_id=uuid4(), title="Test NFT", image_url=None,
            item_address="0:" + "a" * 64, collection_address="0:" + "b" * 64,
        ),
        seller_wallet_address="0:" + "c" * 64, price_nano="2500000000",
        fee_bps=0, available_actions=["create_deal_intent"],
        created_at=now, updated_at=now,
    )
    payload = response.model_dump(mode="json")
    assert {
        "id", "listing_key", "seller_id", "state", "network", "nft",
        "seller_wallet_address", "price_nano", "fee_bps", "available_actions",
        "created_at", "updated_at",
    } == set(payload)
    assert payload["available_actions"] == ["create_deal_intent"]
    assert payload["nft"]["collection_address"] == "0:" + "b" * 64


def test_deal_response_serializes_frontend_projection_fields() -> None:
    now = datetime.now(UTC)
    response = EscrowDealResponse(
        id=uuid4(), listing_id=uuid4(), listing_key="d" * 64,
        buyer_id=uuid4(), seller_id=uuid4(), state="funded_review", network="testnet",
        nft=EscrowNftProjection(
            asset_id=uuid4(), title="Test NFT", image_url=None,
            item_address="0:" + "a" * 64, collection_address="0:" + "b" * 64,
        ),
        escrow_address=None, seller_wallet_address="0:" + "c" * 64,
        buyer_wallet_address="0:" + "e" * 64, price_nano="2500000000", fee_bps=0,
        buyer_review_deadline=None, dispute_deadline=None,
        available_actions=["accept_deal", "open_dispute"], created_at=now,
        updated_at=now, dispute=None,
    )
    payload = response.model_dump(mode="json")
    assert {
        "id", "listing_id", "listing_key", "buyer_id", "seller_id", "state", "network",
        "nft", "escrow_address", "seller_wallet_address", "buyer_wallet_address",
        "price_nano", "fee_bps", "buyer_review_deadline", "dispute_deadline",
        "available_actions", "created_at", "updated_at", "dispute",
    } == set(payload)
    assert payload["available_actions"] == ["accept_deal", "open_dispute"]


def test_page_response_uses_frontend_pagination_envelope() -> None:
    page = EscrowPageResponse(items=[], total=0, next_cursor=None)
    assert page.model_dump(mode="json") == {"items": [], "total": 0, "next_cursor": None}


def test_backend_exposes_expected_deal_scoped_preparation_routes() -> None:
    paths = {route.path for route in router.routes}
    assert "/escrow/marketplace/listing-intents" in paths
    assert "/escrow/buyer/deals" in paths
    assert "/escrow/seller/deals" in paths
    assert "/escrow/deals/{deal_id}/prepare/create-deal-escrow" in paths
    assert "/escrow/deals/{deal_id}/prepare/deposit-nft" in paths
    assert "/escrow/deals/{deal_id}/prepare/funding" in paths
    assert "/escrow/deals/{deal_id}/prepare/accept" in paths
    assert "/escrow/deals/{deal_id}/prepare/dispute" in paths
    assert "/escrow/deals/{deal_id}/prepare/nft-return" in paths
    assert "/escrow/deals/{deal_id}/prepare/withdraw-unsold-nft" in paths
    assert "/escrow/deals/{deal_id}/receipt" not in paths


@pytest.mark.asyncio
async def test_accept_deal_is_buyer_only_and_funded_review_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    seller_id, buyer_id, deal_id = uuid4(), uuid4(), uuid4()
    seller = SimpleNamespace(id=seller_id)
    buyer = SimpleNamespace(id=buyer_id)

    class DealSession:
        def __init__(
            self,
            deal: SimpleNamespace,
            existing_action: SimpleNamespace | None = None,
        ) -> None:
            self.deal = deal
            self.existing_action = existing_action
            self.scalar_calls = 0
            self.get_calls = 0

        async def scalar(self, statement: object) -> SimpleNamespace | None:
            self.scalar_calls += 1
            # The first query loads the deal; the second checks for an existing
            # durable wallet action.
            if self.scalar_calls == 1:
                return self.deal
            if self.scalar_calls == 2:
                return self.existing_action
            return None

        async def get(
            self, model: type[object], identity: object
        ) -> SimpleNamespace | None:
            # _prepare_action uses AsyncSession.get() to load the listing intent
            # while validating an idempotent replay.
            self.get_calls += 1
            return None

    deal = SimpleNamespace(
        id=deal_id,
        seller_id=seller_id,
        buyer_id=buyer_id,
        status="funded_review",
        listing_key_snapshot="a" * 64,
        item_address="0:" + "b" * 64,
        collection_address_snapshot="0:" + "c" * 64,
        seller_address_snapshot="0:" + "d" * 64,
        buyer_address_snapshot="0:" + "e" * 64,
        principal_nanotons=2_500_000_000,
        deal_salt="f" * 64,
        network="testnet",
        listing_intent_id=uuid4(),
    )
    with pytest.raises(HTTPException) as seller_error:
        await _prepare_action(
            deal_id, EscrowWalletAction.ACCEPT_DEAL, seller, DealSession(deal), None,
            "accept-key-0001",
        )
    assert seller_error.value.status_code == 409

    deal.status = "awaiting_buyer_funds"
    with pytest.raises(HTTPException) as buyer_error:
        await _prepare_action(
            deal_id, EscrowWalletAction.ACCEPT_DEAL, buyer, DealSession(deal), None,
            "accept-key-0001",
        )
    assert buyer_error.value.status_code == 409

    # A valid actor/state reaches the idempotent replay path, which loads the
    # listing intent through AsyncSession.get(). A missing intent must produce
    # the expected 404 instead of an AttributeError from an incomplete test double.
    deal.status = "funded_review"
    replay_session = DealSession(deal, SimpleNamespace(deal_id=deal_id))
    with pytest.raises(HTTPException) as replay_error:
        await _prepare_action(
            deal_id, EscrowWalletAction.ACCEPT_DEAL, buyer, replay_session, None,
            "accept-key-0001",
        )
    assert replay_error.value.status_code == 404
    assert replay_session.get_calls == 1


def test_listing_available_actions_are_actor_scoped() -> None:
    seller_id, buyer_id = uuid4(), uuid4()
    intent = SimpleNamespace(status="active", seller_id=seller_id)

    assert _listing_actions(intent, seller_id) == []
    assert _listing_actions(intent, buyer_id) == ["create_deal_intent"]
