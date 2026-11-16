from fastapi import HTTPException

from app.api.escrow import _retry_descriptor_from_proof


def _retry_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "query_id": 4321,
        "deal_salt": "ab" * 32,
        "status": 1,
        "retry_window_seconds": 1800,
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
        ({"outbound_actions": [_retry_row(recipient_address="not-an-address")]}, 4321, "ab" * 32, "recipient_invalid"),
        ({"outbound_actions": [_retry_row(retry_window_seconds=0)]}, 4321, "ab" * 32, "window_invalid"),
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


