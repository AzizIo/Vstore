from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.escrow import (
    _build_deployment_snapshot,
    _listing_actions,
    _prepare_action,
    list_retryable_outbound_actions,
    router,
    submit_wallet_reference,
)
from app.escrow.contracts import EscrowWalletAction
from app.escrow.models import EscrowIdempotencyRecord
from app.escrow.schemas import (
    EscrowDealCreate,
    EscrowDealResponse,
    EscrowListingIntentCreate,
    EscrowListingIntentResponse,
    EscrowNftProjection,
    EscrowPageResponse,
    EscrowRetryFailedOutboundInput,
    EscrowRetryableOutboundActionResponse,
    EscrowWalletReferenceInput,
)
from app.escrow.service import canonical_request_sha256


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


def test_retry_query_id_is_a_bounded_uint64_decimal_string() -> None:
    assert EscrowRetryFailedOutboundInput(query_id="18446744073709551615").query_id == "18446744073709551615"
    for invalid in ("0", "-1", "18446744073709551616", "1.0", "abc"):
        with pytest.raises(ValidationError):
            EscrowRetryFailedOutboundInput(query_id=invalid)


def test_page_response_uses_frontend_pagination_envelope() -> None:
    page = EscrowPageResponse(items=[], total=0, next_cursor=None)
    assert page.model_dump(mode="json") == {"items": [], "total": 0, "next_cursor": None}


def test_backend_exposes_expected_deal_scoped_preparation_routes() -> None:
    paths = {route.path for route in router.routes}
    assert "/escrow/marketplace/listing-intents" in paths
    assert "/escrow/buyer/deals" in paths
    assert "/escrow/seller/deals" in paths
    assert "/escrow/deals/{deal_id}/prepare/create-deal-escrow" in paths
    assert "/escrow/deals/{deal_id}/prepare/activate-deal" in paths
    assert "/escrow/deals/{deal_id}/prepare/deposit-nft" in paths
    assert "/escrow/deals/{deal_id}/prepare/funding" in paths
    assert "/escrow/deals/{deal_id}/prepare/accept" in paths
    assert "/escrow/deals/{deal_id}/prepare/dispute" in paths
    assert "/escrow/deals/{deal_id}/prepare/nft-return" in paths
    assert "/escrow/deals/{deal_id}/prepare/withdraw-unsold-nft" in paths
    assert "/escrow/deals/{deal_id}/retryable-outbound-actions" in paths
    assert "/escrow/deals/{deal_id}/prepare/retry-failed-outbound" in paths
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

    # Exercise the actual route-level replay branch: the durable blocked action
    # must keep both its ID and its persisted error code on a same-key retry.
    expected_hash = canonical_request_sha256({
        "actor_id": str(buyer_id),
        "deal_id": str(deal.id),
        "action_type": EscrowWalletAction.FUND_DEAL.value,
        "network": deal.network,
        "wallet_id": str(wallet_id),
        "wallet_address": deal.buyer_address_snapshot,
        "listing_key": deal.listing_key_snapshot,
        "item_address": deal.item_address,
        "collection_address": deal.collection_address_snapshot,
        "seller_address": deal.seller_address_snapshot,
        "buyer_address": deal.buyer_address_snapshot,
        "principal_nanotons": str(deal.principal_nanotons),
        "deal_salt": deal.deal_salt,
        "context": {},
    })
    blocked_action = SimpleNamespace(
        id=action_record.id,
        deal_id=deal_id,
        request_sha256=expected_hash,
        status="blocked_abi",
        last_error_code="deployment_snapshot_incomplete",
    )
    replay_session = ActionSession()
    async def replay_scalar(_statement: object) -> SimpleNamespace | None:
        replay_session.scalar_calls += 1
        return deal if replay_session.scalar_calls == 1 else blocked_action
    replay_session.scalar = replay_scalar  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as replay_error:
        await _prepare_action(
            deal_id,
            EscrowWalletAction.FUND_DEAL,
            SimpleNamespace(id=buyer_id),
            replay_session,
            None,
            "fund-action-key-0001",
        )
    assert replay_error.value.status_code == 503
    assert replay_error.value.detail["code"] == "deployment_snapshot_incomplete"
    assert replay_error.value.detail["action_id"] == str(action_record.id)
    assert replay_error.value.detail["action_status"] == "blocked_abi"


def test_preview_compose_is_the_only_compose_runtime_opted_into_preview_mode() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    production_compose = (repository_root / "docker-compose.yml").read_text()
    preview_compose = (repository_root / "docker-compose.preview.yml").read_text()

    assert "PREVIEW_MODE" not in production_compose
    assert 'PREVIEW_MODE: "1"' in preview_compose
    assert "ENVIRONMENT: production" in preview_compose


class WalletReferenceSession:
    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.added: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.refresh_calls = 0

    async def scalar(self, _statement: object) -> object:
        return self.results.pop(0) if self.results else None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def refresh(self, _record: object) -> None:
        self.refresh_calls += 1


def _prepared_wallet_action(*, actor_id: UUID, action_type: str = "fund_deal"):
    return SimpleNamespace(
        id=uuid4(),
        actor_id=actor_id,
        action_type=action_type,
        network="testnet",
        status="prepared",
        attempt_count=0,
        unsigned_boc_sha256="b" * 64,
        unsigned_boc_ref="db://escrow_wallet_actions/action/unsigned_bocs_json",
        submission_reference=None,
        submission_reference_sha256=None,
        last_error_code=None,
    )


@pytest.mark.asyncio
async def test_wallet_reference_is_a_durable_hint_not_chain_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    actor_id = uuid4()
    action = _prepared_wallet_action(actor_id=actor_id)
    session = WalletReferenceSession(action, None)
    reference = "a" * 64

    response = await submit_wallet_reference(
        EscrowWalletReferenceInput(
            action_id=action.id,
            action="fund_deal",
            reference=reference,
        ),
        SimpleNamespace(id=actor_id),
        session,  # type: ignore[arg-type]
        "wallet-reference-key-0001",
    )

    expected_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
    assert response.action_id == action.id
    assert response.status == "ambiguous"
    assert response.reference_sha256 == expected_hash
    assert response.reconciliation_status == "awaiting_independent_chain_reconciliation"
    assert action.status == "ambiguous"
    assert action.last_error_code == "awaiting_independent_chain_reconciliation"
    assert len(session.added) == 1
    assert isinstance(session.added[0], EscrowIdempotencyRecord)
    assert session.added[0].resource_id == action.id
    assert session.commit_calls == 1
    # The endpoint does not call the observer, set a deal status or release a listing.


@pytest.mark.asyncio
async def test_wallet_reference_hides_actions_owned_by_another_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    session = WalletReferenceSession(None)

    with pytest.raises(HTTPException) as error:
        await submit_wallet_reference(
            EscrowWalletReferenceInput(
                action_id=uuid4(),
                action="fund_deal",
                reference="a" * 64,
            ),
            SimpleNamespace(id=uuid4()),
            session,  # type: ignore[arg-type]
            "wallet-reference-key-0002",
        )

    assert error.value.status_code == 404
    assert error.value.detail["code"] == "escrow_action_not_found"
    assert session.added == []
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_wallet_reference_exact_idempotency_replay_returns_current_chain_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    actor_id = uuid4()
    action = _prepared_wallet_action(actor_id=actor_id)
    reference = "c" * 64
    reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
    action.status = "finalized"
    action.submission_reference = reference
    action.submission_reference_sha256 = reference_hash
    key = "wallet-reference-replay-0001"
    request_hash = canonical_request_sha256(
        {
            "actor_id": str(actor_id),
            "action_id": str(action.id),
            "action": "fund_deal",
            "reference_sha256": reference_hash,
        }
    )
    receipt = SimpleNamespace(
        request_sha256=request_hash,
        resource_type="wallet_action",
        resource_id=action.id,
    )
    session = WalletReferenceSession(action, receipt)

    response = await submit_wallet_reference(
        EscrowWalletReferenceInput(
            action_id=action.id,
            action="fund_deal",
            reference=reference,
        ),
        SimpleNamespace(id=actor_id),
        session,  # type: ignore[arg-type]
        key,
    )

    assert response.status == "finalized"
    assert response.reconciliation_status == "already_finalized"
    assert response.reference_sha256 == reference_hash
    assert session.added == []
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_wallet_reference_idempotency_key_cannot_be_reused_for_another_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    actor_id = uuid4()
    action = _prepared_wallet_action(actor_id=actor_id)
    original_ref_hash = hashlib.sha256(("d" * 64).encode()).hexdigest()
    request_hash = canonical_request_sha256(
        {
            "actor_id": str(actor_id),
            "action_id": str(action.id),
            "action": "fund_deal",
            "reference_sha256": original_ref_hash,
        }
    )
    receipt = SimpleNamespace(
        request_sha256=request_hash,
        resource_type="wallet_action",
        resource_id=action.id,
    )
    session = WalletReferenceSession(action, receipt)

    with pytest.raises(HTTPException) as error:
        await submit_wallet_reference(
            EscrowWalletReferenceInput(
                action_id=action.id,
                action="fund_deal",
                reference="e" * 64,
            ),
            SimpleNamespace(id=actor_id),
            session,  # type: ignore[arg-type]
            "wallet-reference-replay-0002",
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "idempotency_payload_conflict"
    assert action.status == "prepared"
    assert action.submission_reference is None
    assert session.rollback_calls == 1


@pytest.mark.asyncio
async def test_conflicting_second_wallet_reference_quarantines_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    actor_id = uuid4()
    old_reference = "f" * 64
    old_hash = hashlib.sha256(old_reference.encode()).hexdigest()
    action = _prepared_wallet_action(actor_id=actor_id)
    action.status = "ambiguous"
    action.submission_reference = old_reference
    action.submission_reference_sha256 = old_hash
    session = WalletReferenceSession(action, None)

    with pytest.raises(HTTPException) as error:
        await submit_wallet_reference(
            EscrowWalletReferenceInput(
                action_id=action.id,
                action="fund_deal",
                reference="9" * 64,
            ),
            SimpleNamespace(id=actor_id),
            session,  # type: ignore[arg-type]
            "wallet-reference-conflict-0001",
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "submission_reference_conflict"
    assert action.status == "manual_review"
    assert action.last_error_code == "submission_reference_conflict"
    assert action.submission_reference_sha256 == old_hash
    assert session.commit_calls == 1
    assert len(session.added) == 1



@pytest.mark.asyncio
async def test_new_idempotency_key_cannot_prepare_same_active_outbound_retry_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    buyer_id, seller_id, deal_id, wallet_id = uuid4(), uuid4(), uuid4(), uuid4()
    buyer_address = "0:" + "b" * 64
    deal = SimpleNamespace(
        id=deal_id,
        buyer_id=buyer_id,
        seller_id=seller_id,
        buyer_wallet_id=wallet_id,
        listing_intent_id=uuid4(),
        status="settled",
        listing_key_snapshot="a" * 64,
        item_address="0:" + "c" * 64,
        collection_address_snapshot="0:" + "d" * 64,
        seller_address_snapshot="0:" + "e" * 64,
        buyer_address_snapshot=buyer_address,
        principal_nanotons=1_000_000_000,
        deal_salt="f" * 64,
        network="testnet",
    )
    active_action = SimpleNamespace(id=uuid4(), status="prepared")

    class RetrySession:
        def __init__(self) -> None:
            self.scalar_calls = 0
            self.rollback_calls = 0

        async def scalar(self, _statement: object):
            self.scalar_calls += 1
            if self.scalar_calls in {1, 3}:
                return deal
            if self.scalar_calls == 4:
                return active_action
            return None

        async def get(self, _model: type[object], _identity: object):
            return SimpleNamespace(seller_wallet_id=uuid4())

        async def rollback(self) -> None:
            self.rollback_calls += 1

    async def verified_wallet(
        _session: object, *, user_id: object, wallet_id: object
    ):
        assert user_id == buyer_id
        assert wallet_id == deal.buyer_wallet_id
        return SimpleNamespace(id=wallet_id), buyer_address

    monkeypatch.setattr("app.api.escrow._verified_wallet", verified_wallet)
    proof = SimpleNamespace(
        action=SimpleNamespace(query_id=42, recipient_address=buyer_address)
    )
    context = {
        "query_id": "42",
        "proof_anchor": {
            "provider_id": "pytoniq-trust0-testnet-v1",
            "masterchain_seqno": 700,
            "masterchain_block_hash": "1" * 64,
            "state_data_hash": "2" * 64,
        },
    }
    session = RetrySession()

    with pytest.raises(HTTPException) as error:
        await _prepare_action(
            deal_id,
            EscrowWalletAction.RETRY_FAILED_OUTBOUND_ACTION,
            SimpleNamespace(id=buyer_id),
            session,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            "retry-new-key-0001",
            context,
            proof,  # type: ignore[arg-type]
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "outbound_retry_already_prepared"
    assert error.value.detail["action_status"] == "prepared"
    assert session.rollback_calls == 1
    assert session.scalar_calls == 4


@pytest.mark.asyncio
async def test_retry_preparation_rejects_a_wallet_that_is_not_the_proved_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    buyer_id, seller_id, deal_id, wallet_id = uuid4(), uuid4(), uuid4(), uuid4()
    deal = SimpleNamespace(
        id=deal_id,
        buyer_id=buyer_id,
        seller_id=seller_id,
        buyer_wallet_id=wallet_id,
        listing_intent_id=uuid4(),
        status="settled",
        listing_key_snapshot="a" * 64,
        item_address="0:" + "c" * 64,
        collection_address_snapshot="0:" + "d" * 64,
        seller_address_snapshot="0:" + "e" * 64,
        buyer_address_snapshot="0:" + "b" * 64,
        principal_nanotons=1_000_000_000,
        deal_salt="f" * 64,
        network="testnet",
    )

    class RetrySession:
        def __init__(self) -> None:
            self.scalar_calls = 0

        async def scalar(self, _statement: object):
            self.scalar_calls += 1
            return deal if self.scalar_calls == 1 else None

    async def wrong_wallet(
        _session: object, *, user_id: object, wallet_id: object
    ):
        return SimpleNamespace(id=wallet_id), "0:" + "9" * 64

    monkeypatch.setattr("app.api.escrow._verified_wallet", wrong_wallet)
    proof = SimpleNamespace(
        action=SimpleNamespace(query_id=42, recipient_address="0:" + "8" * 64)
    )
    with pytest.raises(HTTPException) as error:
        await _prepare_action(
            deal_id,
            EscrowWalletAction.RETRY_FAILED_OUTBOUND_ACTION,
            SimpleNamespace(id=buyer_id),
            RetrySession(),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            "retry-wrong-wallet-0001",
            {"query_id": "42"},
            proof,  # type: ignore[arg-type]
        )
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "outbound_retry_recipient_wallet_mismatch"


@pytest.mark.asyncio
async def test_retryable_outbound_projection_is_recipient_wallet_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.escrow._require_testnet", lambda: None)
    buyer_id, deal_id, wallet_id = uuid4(), uuid4(), uuid4()
    recipient = "0:" + "b" * 64
    deal = SimpleNamespace(
        id=deal_id,
        buyer_id=buyer_id,
        seller_id=uuid4(),
        buyer_wallet_id=wallet_id,
    )

    class ProjectionSession:
        async def scalar(self, _statement: object):
            return deal

    async def verified_wallet(
        _session: object, *, user_id: object, wallet_id: object
    ):
        assert user_id == buyer_id
        assert wallet_id == deal.buyer_wallet_id
        return SimpleNamespace(id=wallet_id), recipient

    class FakeProvider:
        def __init__(self, **_kwargs: object) -> None:
            self.closed = False

        async def read_current_outbound_retry_proofs(self, _deal: object):
            return (
                SimpleNamespace(
                    action=SimpleNamespace(
                        query_id=42, slot="first", kind=4,
                        recipient_address=recipient, amount_nanotons=90_000_000,
                        retry_window_seconds=1800,
                    ),
                    masterchain_seqno=700,
                ),
                SimpleNamespace(
                    action=SimpleNamespace(
                        query_id=43, slot="second", kind=5,
                        recipient_address="0:" + "9" * 64, amount_nanotons=90_000_000,
                        retry_window_seconds=1800,
                    ),
                    masterchain_seqno=700,
                ),
            )

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("app.api.escrow._verified_wallet", verified_wallet)
    monkeypatch.setattr("app.api.escrow.PytoniqTONTestnetEscrowProvider", FakeProvider)

    actions = await list_retryable_outbound_actions(
        deal_id,
        SimpleNamespace(id=buyer_id),
        ProjectionSession(),  # type: ignore[arg-type]
    )

    assert len(actions) == 1
    assert actions[0].query_id == "42"
    assert actions[0].recipient_address == recipient
    assert actions[0].proof_masterchain_seqno == 700


def test_retryable_outbound_response_accepts_only_kind_specific_windows() -> None:
    common = {
        "query_id": "18446744073709551615",
        "slot": "second",
        "recipient_address": "0:" + "a" * 64,
        "amount_nanotons": "90000000",
        "proof_masterchain_seqno": 700,
    }
    terminal = EscrowRetryableOutboundActionResponse(
        **common, kind=6, retry_window_seconds=0
    )
    assert terminal.retry_window_seconds == 0
    lifecycle = EscrowRetryableOutboundActionResponse(
        **common, kind=4, retry_window_seconds=1800
    )
    assert lifecycle.retry_window_seconds == 1800
    reserve = EscrowRetryableOutboundActionResponse(
        **{**common, "amount_nanotons": "0"},
        kind=7, retry_window_seconds=0,
    )
    assert reserve.amount_nanotons == "0"
    for kind, window in ((4, 0), (6, 1800), (7, 1)):
        with pytest.raises(ValidationError):
            EscrowRetryableOutboundActionResponse(
                **common, kind=kind, retry_window_seconds=window
            )
    with pytest.raises(ValidationError):
        EscrowRetryableOutboundActionResponse(
            **{**common, "query_id": "18446744073709551616"},
            kind=6, retry_window_seconds=0,
        )
