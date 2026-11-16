from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.escrow import (
    _canonical_sha256,
    _retry_descriptor_from_proof,
    list_retryable_outbound_actions,
)
from app.escrow.schemas import (
    EscrowOutboundRetryRequest,
    EscrowRetryableOutboundActionResponse,
)


def _retry_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "slot": "first",
        "kind": 4,
        "query_id": 4321,
        "deal_salt": "ab" * 32,
        "attempt_id": 7,
        "amount_nanotons": 90_000_000,
        "message_value_nanotons": 90_000_000,
        "expected_state": 10,
        "expected_pending_action": 0,
        "status": 1,
        "retry_window_seconds": 1800,
        "bounce_phase": 1,
        "message_body_hash": "cd" * 32,
        "recipient_address": "0:" + "33" * 32,
    }
    row.update(changes)
    return row


def test_retry_descriptor_requires_one_canonical_bounced_match() -> None:
    descriptor = _retry_descriptor_from_proof(
        {"outbound_actions": [_retry_row()]},
        query_id=4321,
        expected_deal_salt="ab" * 32,
    )
    assert descriptor.query_id == 4321
    assert descriptor.deal_salt == "ab" * 32
    assert descriptor.recipient_address == "0:" + "33" * 32
    assert descriptor.status == 1
    assert descriptor.retry_window_seconds == 1800


@pytest.mark.parametrize(
    ("getter", "query_id", "salt", "code"),
    [
        ({"outbound_actions": []}, 4321, "ab" * 32, "not_found"),
        ({"outbound_actions": [_retry_row(), _retry_row()]}, 4321, "ab" * 32, "duplicate"),
        ({"outbound_actions": [_retry_row(status=0)]}, 4321, "ab" * 32, "not_bounced"),
        ({"outbound_actions": [_retry_row(deal_salt="cd" * 32)]}, 4321, "ab" * 32, "salt_mismatch"),
        (
            {"outbound_actions": [_retry_row(recipient_address="not-an-address")]},
            4321,
            "ab" * 32,
            "recipient_invalid",
        ),
        (
            {"outbound_actions": [_retry_row(retry_window_seconds=0)]},
            4321,
            "ab" * 32,
            "window_invalid",
        ),
        ({"outbound_actions": [_retry_row(query_id=True)]}, 4321, "ab" * 32, "not_found"),
        ({}, 4321, "ab" * 32, "proof_incomplete"),
    ],
)
def test_retry_descriptor_rejects_invalid_or_ambiguous_storage(
    getter: dict[str, object], query_id: int, salt: str, code: str,
) -> None:
    with pytest.raises(HTTPException) as exc:
        _retry_descriptor_from_proof(
            getter, query_id=query_id, expected_deal_salt=salt
        )
    detail = exc.value.detail
    assert isinstance(detail, dict) and str(detail["code"]).endswith(code)




def test_retry_descriptor_accepts_contract_defined_zero_window_terminal_refund() -> None:
    seller_refund = _retry_descriptor_from_proof(
        {"outbound_actions": [_retry_row(
            kind=6, retry_window_seconds=0,
        )]},
        query_id=4321,
        expected_deal_salt="ab" * 32,
    )
    assert seller_refund.kind == 6
    assert seller_refund.retry_window_seconds == 0

    execution_reserve = _retry_descriptor_from_proof(
        {"outbound_actions": [_retry_row(
            kind=7, retry_window_seconds=0,
            amount_nanotons=0, message_value_nanotons=0,
        )]},
        query_id=4321,
        expected_deal_salt="ab" * 32,
    )
    assert execution_reserve.kind == 7
    assert execution_reserve.amount_nanotons == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": 4, "retry_window_seconds": 0},
        {"kind": 6, "retry_window_seconds": 1800},
        {"kind": 7, "retry_window_seconds": 1800},
        {"kind": 7, "amount_nanotons": 1},
        {"kind": 7, "message_value_nanotons": 1},
        {"kind": 4, "amount_nanotons": 0},
        {"kind": 4, "attempt_id": 0},
        {"kind": 4, "bounce_phase": 0},
        {"kind": 4, "message_body_hash": "not-a-hash"},
    ],
)
def test_retry_descriptor_rejects_invalid_kind_specific_fields(
    changes: dict[str, object],
) -> None:
    with pytest.raises(HTTPException):
        _retry_descriptor_from_proof(
            {"outbound_actions": [_retry_row(**changes)]},
            query_id=4321,
            expected_deal_salt="ab" * 32,
        )


def test_execution_reserve_retry_waits_for_seller_deployment_refund() -> None:
    getter = {
        "outbound_actions": [
            _retry_row(kind=6, query_id=4321, retry_window_seconds=0),
            _retry_row(
                kind=7, query_id=4322, retry_window_seconds=0,
                amount_nanotons=0, message_value_nanotons=0,
            ),
        ]
    }
    with pytest.raises(HTTPException) as exc:
        _retry_descriptor_from_proof(
            getter, query_id=4322, expected_deal_salt="ab" * 32
        )
    assert exc.value.detail["code"] == "outbound_action_retry_order_not_ready"


def test_retry_request_uses_bounded_decimal_uint64_string() -> None:
    request = EscrowOutboundRetryRequest(query_id="18446744073709551615")
    assert request.query_id == "18446744073709551615"
    with pytest.raises(Exception):
        EscrowOutboundRetryRequest(query_id="18446744073709551616")
    with pytest.raises(Exception):
        EscrowOutboundRetryRequest(query_id="0")


@pytest.mark.asyncio
async def test_retry_projection_uses_current_proof_and_exact_recipient_wallet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buyer_id, deal_id, wallet_id = uuid4(), uuid4(), uuid4()
    recipient = "0:" + "33" * 32
    deployment_snapshot = {"deal_salt": "ab" * 32}
    deal = SimpleNamespace(
        id=deal_id,
        buyer_id=buyer_id,
        seller_id=uuid4(),
        buyer_wallet_id=wallet_id,
        listing_intent_id=uuid4(),
        contract_address="0:" + "44" * 32,
        deployment_snapshot_json=deployment_snapshot,
        deployment_snapshot_sha256=_canonical_sha256(deployment_snapshot),
        deal_salt="ab" * 32,
        network="testnet",
    )

    class ProjectionSession:
        def __init__(self) -> None:
            self.rollback_calls = 0

        async def scalar(self, _statement: object):
            return deal

        async def rollback(self) -> None:
            self.rollback_calls += 1

    async def verified_wallet(_session: object, *, user_id: object, wallet_id: object):
        assert user_id == buyer_id
        assert wallet_id == deal.buyer_wallet_id
        return SimpleNamespace(id=wallet_id), recipient

    class ProofProvider:
        async def verify_deployed_account(self, proof_deal: object, *, require_initial_state: bool):
            assert require_initial_state is False
            assert proof_deal.contract_address == deal.contract_address
            return ({
                "outbound_actions": [_retry_row()],
                "_proof_masterchain_seqno": 700,
                "_proof_masterchain_block_hash": "aa" * 32,
                "_proof_state_data_hash": "bb" * 32,
                "_proof_provider_id": "pytoniq-trust0-testnet-v1",
            }, 700, "aa" * 32, "pytoniq-trust0-testnet-v1")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ton_escrow_finality_provider=ProofProvider()))
    )
    monkeypatch.setattr("app.api.escrow._verified_wallet", verified_wallet)

    actions = await list_retryable_outbound_actions(
        deal_id, request, SimpleNamespace(id=buyer_id),
        ProjectionSession(),  # type: ignore[arg-type]
    )

    assert len(actions) == 1
    assert isinstance(actions[0], EscrowRetryableOutboundActionResponse)
    assert actions[0].query_id == "4321"
    assert actions[0].recipient_address == recipient
    assert actions[0].proof_masterchain_seqno == 700
    assert actions[0].proof_masterchain_block_hash == "aa" * 32
    assert actions[0].proof_state_data_hash == "bb" * 32
    assert actions[0].proof_provider_id == "pytoniq-trust0-testnet-v1"


@pytest.mark.asyncio
async def test_retry_projection_hides_third_party_and_duplicate_query_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buyer_id, deal_id, wallet_id = uuid4(), uuid4(), uuid4()
    recipient = "0:" + "33" * 32
    third_party = "0:" + "99" * 32
    deployment_snapshot = {"deal_salt": "ab" * 32}
    deal = SimpleNamespace(
        id=deal_id,
        buyer_id=buyer_id,
        seller_id=uuid4(),
        buyer_wallet_id=wallet_id,
        listing_intent_id=uuid4(),
        contract_address="0:" + "44" * 32,
        deployment_snapshot_json=deployment_snapshot,
        deployment_snapshot_sha256=_canonical_sha256(deployment_snapshot),
        deal_salt="ab" * 32,
        network="testnet",
    )

    class ProjectionSession:
        async def scalar(self, _statement: object):
            return deal

        async def rollback(self) -> None:
            return None

    async def verified_wallet(_session: object, *, user_id: object, wallet_id: object):
        return SimpleNamespace(id=wallet_id), recipient

    rows = [
        _retry_row(query_id=4321, recipient_address=third_party),
        _retry_row(query_id=4322),
        _retry_row(query_id=4322, slot="second"),
    ]

    class ProofProvider:
        async def verify_deployed_account(self, _deal: object, *, require_initial_state: bool):
            return ({
                "outbound_actions": rows,
                "_proof_masterchain_seqno": 700,
                "_proof_masterchain_block_hash": "aa" * 32,
                "_proof_state_data_hash": "bb" * 32,
                "_proof_provider_id": "pytoniq-trust0-testnet-v1",
            }, 700, "aa" * 32, "pytoniq-trust0-testnet-v1")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ton_escrow_finality_provider=ProofProvider()))
    )
    monkeypatch.setattr("app.api.escrow._verified_wallet", verified_wallet)

    actions = await list_retryable_outbound_actions(
        deal_id, request, SimpleNamespace(id=buyer_id),
        ProjectionSession(),  # type: ignore[arg-type]
    )
    assert actions == []
