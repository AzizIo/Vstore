from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.notifications.service import (
    build_notification_message,
    NotificationDelivery,
    UnsupportedNotificationEvent,
)


ORDER_ID = UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def delivery_factory():
    def make(
        event_type: str = "order_created",
        recipient_role: str = "buyer",
    ) -> NotificationDelivery:
        return NotificationDelivery(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            claim_token=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            recipient_telegram_id=123456789,
            recipient_role=recipient_role,
            event_type=event_type,
            order_id=ORDER_ID,
            price_amount=Decimal("1.250000000"),
            price_currency="TON",
            attempt_count=1,
        )

    return make


@pytest.mark.parametrize(
    ("event_type", "role", "expected_description", "expected_status"),
    [
        (
            "order_created",
            "buyer",
            "Your order was created and the listing is reserved.",
            "Reserved",
        ),
        (
            "order_created",
            "seller",
            "A buyer reserved your listing.",
            "Reserved",
        ),
        ("order_cancelled", "buyer", "You cancelled the order.", "Cancelled"),
        (
            "order_cancelled",
            "seller",
            "The buyer cancelled the order.",
            "Cancelled",
        ),
        (
            "order_expired",
            "buyer",
            "The order reservation expired automatically.",
            "Expired",
        ),
        (
            "order_expired",
            "seller",
            "The order reservation expired automatically.",
            "Expired",
        ),
    ],
)
def test_builds_explicit_messages_for_supported_events_and_roles(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
    event_type: str,
    role: str,
    expected_description: str,
    expected_status: str,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url="https://t.me/viltara/app"),
    )

    message = build_notification_message(delivery_factory(event_type, role))

    assert expected_description in message
    assert f"Status: {expected_status}" in message
    assert "Amount: 1.25 TON" in message
    assert "Pending payment" not in message
    assert "Open in Mini App:" in message


def test_unknown_event_type_fails_explicitly_instead_of_expiring_order(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url=None),
    )

    with pytest.raises(
        UnsupportedNotificationEvent,
        match="Unsupported Telegram notification event_type: 'transfer_confirmed'",
    ):
        build_notification_message(delivery_factory("transfer_confirmed"))


def test_missing_mini_app_url_omits_link_but_keeps_notification(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(telegram_mini_app_url=None),
    )

    message = build_notification_message(delivery_factory("order_created"))

    assert "Your order was created and the listing is reserved." in message
    assert "Status: Reserved" in message
    assert "Open in Mini App:" not in message
