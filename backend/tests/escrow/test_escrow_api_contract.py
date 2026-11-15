from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.escrow import (
    _build_deployment_snapshot,
    _listing_actions,
    _prepare_action,
    router,
)
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



def test_deployment_snapshot_fails_closed_when_required_chain_terms_are_missing() -> None:
    deal = SimpleNamespace(
        network="testnet",
        listing_key_snapshot="a" * 64,
        seller_address_snapshot="0:" + "b" * 64,
        buyer_address_snapshot="0:" + "c" * 64,
        collection_address_snapshot="0:" + "d" * 64,
        item_address="0:" + "e" * 64,
        principal_nanotons=2_500_000_000,
        deal_salt="f" * 64,
    )

    snapshot, missing = _build_deployment_snapshot(deal)

    assert snapshot is None
    assert "execution_reserve_nanotons" in missing
    assert "fund_query_id" in missing
    assert "oracle_key_a" in missing
    assert "resolver_key_a" in missing
    assert "contract_state" in missing


def test_complete_immutable_deal_snapshot_is_constructed_without_defaulting_terms() -> None:
    deal = SimpleNamespace(
        network="testnet",
        network_id=-3,
        protocol_version=1,
        listing_key_snapshot="a" * 64,
        seller_address_snapshot="0:" + "b" * 64,
        buyer_address_snapshot="0:" + "c" * 64,
        collection_address_snapshot="0:" + "d" * 64,
        item_address="0:" + "e" * 64,
        principal_nanotons=2_500_000_000,
        execution_reserve_nanotons=500_000_000,
        seller_deployment_refund_nanotons=20_000_000,
        nft_transfer_value_nanotons=50_000_000,
        deal_salt="f" * 64,
        activation_query_id=1,
        fund_query_id=2,
        nft_deposit_query_id=3,
        nft_release_query_id=4,
        nft_return_to_escrow_query_id=5,
        oracle_key_a=11,
        oracle_key_b=12,
        oracle_key_c=13,
        resolver_key_a=21,
        resolver_key_b=22,
        resolver_key_c=23,
        deployment_value_nanotons=100_000_000,
        activation_value_nanotons=20_000_000,
        action_value_nanotons=20_000_000,
        nft_deposit_value_nanotons=50_000_000,
        nft_return_value_nanotons=50_000_000,
        contract_state=2,
        deadline_unix=1_800_000_000,
        observed_chain_time_unix=1_799_999_900,
        dispute_phase=0,
        nft_in_escrow=False,
        principal_locked=False,
    )

    snapshot, missing = _build_deployment_snapshot(deal)

    assert missing == ()
    assert snapshot is not None
    assert snapshot.network_id == -3
    assert snapshot.execution_reserve_nanotons == 500_000_000
    assert snapshot.fund_query_id == 2
    assert snapshot.oracle_key_c == 13
    assert snapshot.principal_locked is False



@pytest.mark.asyncio
async def test_prepare_action_persists_idempotency_before_incomplete_snapshot_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    buyer_id = uuid4()
    deal_id = uuid4()
    wallet_id = uuid4()
    listing_intent_id = uuid4()
    deal = SimpleNamespace(
        id=deal_id,
        seller_id=uuid4(),
        buyer_id=buyer_id,
        status="awaiting_buyer_funds",
        listing_key_snapshot="a" * 64,
        item_address="0:" + "b" * 64,
        collection_address_snapshot="0:" + "c" * 64,
        seller_address_snapshot="0:" + "d" * 64,
        buyer_address_snapshot="0:" + "e" * 64,
        principal_nanotons=2_500_000_000,
        deal_salt="f" * 64,
        network="testnet",
        listing_intent_id=listing_intent_id,
        buyer_wallet_id=wallet_id,
    )
    wallet = SimpleNamespace(id=wallet_id)
    listing_intent = SimpleNamespace(seller_wallet_id=uuid4())
    action_record = SimpleNamespace(
        id=uuid4(),
        status="pending",
        last_error_code=None,
    )

    class ActionSession:
        def __init__(self) -> None:
            self.scalar_calls = 0
            self.commit_calls = 0
            self.refresh_calls = 0

        async def scalar(self, _statement: object) -> SimpleNamespace | None:
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return deal
            if self.scalar_calls == 2:
                return None
            if self.scalar_calls == 3:
                return deal
            return None

        async def get(self, _model: type[object], _identity: object) -> SimpleNamespace:
            return listing_intent

        async def commit(self) -> None:
            self.commit_calls += 1

        async def refresh(self, _record: object) -> None:
            self.refresh_calls += 1

    session = ActionSession()

    async def verified_wallet(
        _session: object, *, user_id: object, wallet_id: object
    ) -> tuple[SimpleNamespace, str]:
        assert user_id == buyer_id
        assert wallet_id == wallet_id_expected
        return wallet, deal.buyer_address_snapshot

    wallet_id_expected = wallet_id

    async def create_action(
        _session: object, **_kwargs: object
    ) -> tuple[SimpleNamespace, bool]:
        return action_record, True

    monkeypatch.setattr("app.api.escrow._verified_wallet", verified_wallet)
    monkeypatch.setattr("app.api.escrow.create_or_replay_action", create_action)

    with pytest.raises(HTTPException) as error:
        await _prepare_action(
            deal_id,
            EscrowWalletAction.FUND_DEAL,
            SimpleNamespace(id=buyer_id),
            session,
            None,
            "fund-action-key-0001",
        )

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "deployment_snapshot_incomplete"
    assert error.value.detail["action_id"] == str(action_record.id)
    assert "fund_query_id" in error.value.detail["missing_fields"]
    assert action_record.status == "blocked_abi"
    assert action_record.last_error_code == "deployment_snapshot_incomplete"
    assert session.commit_calls == 2
    assert session.refresh_calls == 1
