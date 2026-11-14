from __future__ import annotations

import argparse

import pytest

from scripts.seed_stars_test_order import _positive_int, _stars_amount


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", 1),
        ("123456789", 123456789),
        ("1000000000000", 1_000_000_000_000),
        ("9223372036854775807", 9_223_372_036_854_775_807),
    ],
)
def test_positive_telegram_test_account_id(value: str, expected: int) -> None:
    assert _positive_int(value) == expected


@pytest.mark.parametrize("value", ["0", "-1", "9223372036854775808", "not-a-number"])
def test_invalid_telegram_test_account_id_is_rejected(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", 1), ("25", 25), ("100000", 100000)],
)
def test_positive_stars_test_amount(value: str, expected: int) -> None:
    assert _stars_amount(value) == expected


@pytest.mark.parametrize("value", ["0", "-1", "100001", "not-a-number"])
def test_invalid_stars_test_amount_is_rejected(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _stars_amount(value)
