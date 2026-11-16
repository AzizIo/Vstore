import pytest
from fastapi import HTTPException

from app.api.escrow import _retry_descriptor_from_proof


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
