from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
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
            "Зарезервировано",
        ),
        (
            "order_created",
            "seller",
            "Покупатель зарезервировал ваше объявление.",
            "Зарезервировано",
        ),
        ("order_cancelled", "buyer", "Вы отменили заказ.", "Отменён"),
        ("order_cancelled", "seller", "Покупатель отменил заказ.", "Отменён"),
        (
            "order_expired",
            "buyer",
            "Срок резерва заказа истёк автоматически.",
            "Истёк",
        ),
        (
            "order_expired",
            "seller",
            "Срок резерва заказа истёк автоматически.",
            "Истёк",
        ),
        (
            "delivery_prepared",
            "buyer",
            "Продавец подготовил прямую передачу NFT. Получение NFT ещё не подтверждено.",
            "Ожидается перевод продавца",
        ),
        (
            "delivery_prepared",
            "seller",
            (
                "Требуется действие: проверьте данные и подпишите перевод именно этого NFT "
                "в своём TON-кошельке."
            ),
            "Ожидается перевод продавца",
        ),
        (
            "delivery_submitted",
            "buyer",
            "Данные о переводе получены. Сервис проверяет подтверждение в сети TON.",
            "Проверка перевода",
        ),
        (
            "delivery_submitted",
            "seller",
            "Мы получили данные о переводе. Дождитесь независимой проверки в сети TON.",
            "Проверка перевода",
        ),
        (
            "delivery_confirmed",
            "buyer",
            "Передача именно этого NFT на кошелёк покупателя подтверждена в блокчейне TON.",
            "Перевод подтверждён",
        ),
        (
            "delivery_confirmed",
            "seller",
            "Передача именно этого NFT на кошелёк покупателя подтверждена в блокчейне TON.",
            "Перевод подтверждён",
        ),
        (
            "delivery_manual_review",
            "buyer",
            (
                "Передача требует ручной проверки. Не считайте NFT полученным "
                "и не отправляйте повторный перевод."
            ),
            "Требуется проверка",
        ),
        (
            "delivery_manual_review",
            "seller",
            "Передача требует ручной проверки. Не считайте NFT полученным и не отправляйте повторный перевод.",
            "Требуется проверка",
        ),
    ],
)
def test_builds_russian_notifications_for_every_event_and_recipient(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
    event_type: str,
    role: str,
    expected_description: str,
    expected_status: str,
) -> None:
    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(
            telegram_mini_app_direct_link="https://t.me/viltara_shop_bot/marketplace"
        ),
    )

    message = build_notification_message(delivery_factory(event_type, role))

    assert expected_description in message
    assert f"Статус: {expected_status}" in message
    assert "Сумма: 1.25 TON" in message
    assert "Оплата пока не подключена. Платёж не принимался." in message
    assert "Status:" not in message
    assert "Amount:" not in message
    expected_link = (
        "https://t.me/viltara_shop_bot/marketplace?startapp=order_"
        + ORDER_ID.hex
    )
    assert f"Открыть заказ в Mini App: {expected_link}" in message


def test_unknown_event_type_fails_explicitly_instead_of_expiring_order(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
) -> None:
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
    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(telegram_mini_app_direct_link=None),
    )

    message = build_notification_message(delivery_factory("order_created"))

    assert "Ваш заказ создан, объявление зарезервировано." in message
    assert "Статус: Зарезервировано" in message
    assert "Открыть заказ в Mini App:" not in message


def test_public_web_app_url_is_not_added_as_telegram_direct_link(
    monkeypatch: pytest.MonkeyPatch,
    delivery_factory,
) -> None:
    monkeypatch.setattr(
        "app.notifications.service.get_settings",
        lambda: SimpleNamespace(
            telegram_mini_app_direct_link="https://shop.example.com/miniapp"
        ),
    )

    message = build_notification_message(delivery_factory("order_created"))

    assert "Ваш заказ создан, объявление зарезервировано." in message
    assert "Открыть заказ в Mini App:" not in message
    assert "shop.example.com" not in message
