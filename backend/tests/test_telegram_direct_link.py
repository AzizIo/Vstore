from __future__ import annotations

import pytest

from app.telegram_direct_link import (
    telegram_direct_link_with_startapp,
    validate_telegram_direct_link,
)


@pytest.mark.parametrize(
    "value",
    [
        "https://t.me/viltara_shop_bot/marketplace",
        "https://t.me/viltara_shop_bot/marketplace?startapp=listing_123e4567e89b12d3a456426614174000",
        "  https://t.me/viltara_shop_bot/marketplace  ",
    ],
)
def test_validator_accepts_named_telegram_mini_app_direct_links(value: str) -> None:
    assert validate_telegram_direct_link(value) == value.strip()


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "https://shop.example.com/miniapp",
        "http://t.me/viltara_shop_bot/marketplace",
        "https://t.me/viltara_shop_bot",
        "https://t.me/viltara_shop_bot/marketplace/",
        "https://t.me/viltara_shop_bot/marketplace/extra",
        "https://t.me/viltara_shop_bot/marketplace#fragment",
        "https://t.me/viltara-shop-bot/marketplace",
        "https://t.me/viltara_shop_bot/marketplace with spaces",
    ],
)
def test_validator_rejects_non_telegram_or_malformed_direct_links(
    value: str | None,
) -> None:
    assert validate_telegram_direct_link(value) is None


def test_startapp_builder_preserves_other_query_parameters_and_sets_order() -> None:
    direct_link = (
        "https://t.me/viltara_shop_bot/marketplace"
        "?theme=dark&startapp=listing_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )

    result = telegram_direct_link_with_startapp(
        direct_link,
        startapp="order_123e4567e89b12d3a456426614174000",
    )

    assert result == (
        "https://t.me/viltara_shop_bot/marketplace"
        "?theme=dark&startapp=order_123e4567e89b12d3a456426614174000"
    )


@pytest.mark.parametrize(
    "startapp",
    [
        "https://evil.example/",
        "order_not-a-uuid",
        "transfer_123e4567e89b12d3a456426614174000",
    ],
)
def test_startapp_builder_rejects_unsupported_startapp_values(startapp: str) -> None:
    assert (
        telegram_direct_link_with_startapp(
            "https://t.me/viltara_shop_bot/marketplace",
            startapp=startapp,
        )
        is None
    )
