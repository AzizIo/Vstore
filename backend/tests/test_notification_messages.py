from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest

from app.notifications.service import (
    NotificationDelivery,
    UnsupportedNotificationEvent,
    build_notification_message,
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
            "Ваш заказ создан, объявление зарезервировано.",
            "Заказ зарезервирован",
        ),
        (
            "order_created",
            "seller",
            "Покупатель зарезервировал ваше объявление.",
            "Заказ зарезервирован",
        ),
        ("order_cancelled", "buyer", "Вы отменили заказ.", "Заказ отменён"),
        (
            "order_cancelled",
            "seller",
            "Покупатель отменил заказ.",
            "Заказ отменён",
        ),
        (
            "order_expired",
            "buyer",
            "Время резервирования заказа истекло автоматически.",
            "Резервирование истекло",
        ),
        (
            "order_expired",
            "seller",
            "Время резервирования заказа истекло автоматически.",
            "Резервирование истекло",
        ),
    ],
)
def test_builds_explicit_russian_messages_for_supported_events_and_roles(
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
        lambda: SimpleNamespace(
            telegram_mini_app_direct_link="https://t.me/viltara_shop_bot/marketplace"
        ),
    )

    message = build_notification_message(delivery_factory(event_type, role))

    assert expected_description in message
    assert f"<b>{expected_status}</b>" in message
    assert "<b>Сумма:</b> <code>1.25 TON</code>" in message
    assert "Оплата внутри платформы пока не подключена" in message
    assert "Pending payment" not in message
    expected_link = (
        "https://t.me/viltara_shop_bot/marketplace?startapp=order_"
        + ORDER_ID.hex
    )
    assert f'<a href="{expected_link}">Открыть заказ в приложении</a>' in message
    assert "<b>VILTARA SHOP</b> · Заказ <code>#12345678</code>" in message


def test_unknown_event_type_fails_explicitly_instead_of_expiring_order(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(telegram_mini_app_direct_link=None),
    )

    with pytest.raises(
        UnsupportedNotificationEvent,
        match="Unsupported Telegram notification event_type: 'transfer_confirmed'",
    ):
        build_notification_message(delivery_factory("transfer_confirmed"))


def test_missing_mini_app_url_omits_link_but_keeps_russian_notification(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(telegram_mini_app_direct_link=None),
    )

    message = build_notification_message(delivery_factory("order_created"))

    assert "Ваш заказ создан, объявление зарезервировано." in message
    assert "<b>Заказ зарезервирован</b>" in message
    assert "Открыть заказ в приложении" not in message


def test_public_web_app_url_is_not_added_as_telegram_direct_link(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(
            telegram_mini_app_direct_link="https://shop.example.com/miniapp"
        ),
    )

    message = build_notification_message(delivery_factory("order_created"))

    assert "Ваш заказ создан, объявление зарезервировано." in message
    assert "Открыть заказ в приложении" not in message
    assert "shop.example.com" not in message


def test_notification_escapes_database_values_before_rendering_html(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(telegram_mini_app_direct_link=None),
    )
    delivery = replace(
        delivery_factory(),
        price_currency="<b>TON</b>&",
    )

    message = build_notification_message(delivery)

    assert "<b>Сумма:</b> <code>1.25 &lt;b&gt;TON&lt;/b&gt;&amp;</code>" in message
    assert "<code>1.25 <b>TON</b>&</code>" not in message
