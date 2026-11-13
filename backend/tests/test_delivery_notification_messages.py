from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.notifications import service as notification_service


@pytest.mark.parametrize(
    ("event_type", "role", "expected"),
    [
        ("delivery_prepared", "seller", "подтвердите точную передачу NFT"),
        ("delivery_prepared", "buyer", "ещё не подтверждено"),
        ("delivery_submitted", "seller", "независимой проверки в блокчейне"),
        ("delivery_submitted", "buyer", "сервис проверяет подтверждение"),
        ("delivery_confirmed", "buyer", "независимо подтверждена в блокчейне"),
        ("delivery_confirmed", "seller", "независимо подтверждена в блокчейне"),
        ("delivery_manual_review", "buyer", "не считайте NFT доставленным"),
        ("delivery_manual_review", "seller", "не считайте NFT доставленным"),
    ],
)
def test_delivery_notifications_are_russian_truthful_and_role_specific(
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
    role: str,
    expected: str,
) -> None:
    monkeypatch.setattr(
        notification_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_direct_link=None),
    )
    delivery = notification_service.NotificationDelivery(
        id=uuid.uuid4(),
        claim_token=uuid.uuid4(),
        recipient_telegram_id=123456,
        recipient_role=role,
        event_type=event_type,
        order_id=uuid.uuid4(),
        price_amount=Decimal("1.25"),
        price_currency="TON",
        attempt_count=1,
    )

    message = notification_service.build_notification_message(delivery)

    assert expected.lower() in message.lower()
    assert "<b>VILTARA SHOP</b> · Заказ <code>#" in message
    assert "Оплата внутри платформы пока не подключена" in message
    assert "seed phrase" not in message.lower()
    assert "api key" not in message.lower()
    assert "provider payload" not in message.lower()


def test_unknown_notification_event_remains_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        notification_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_mini_app_direct_link=None),
    )
    delivery = notification_service.NotificationDelivery(
        id=uuid.uuid4(),
        claim_token=uuid.uuid4(),
        recipient_telegram_id=123456,
        recipient_role="buyer",
        event_type="raw_provider_error",
        order_id=uuid.uuid4(),
        price_amount=Decimal("1"),
        price_currency="TON",
        attempt_count=1,
    )

    with pytest.raises(notification_service.UnsupportedNotificationEvent):
        notification_service.build_notification_message(delivery)
