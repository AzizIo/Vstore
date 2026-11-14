from __future__ import annotations

import argparse

import pytest

from scripts.seed_stars_test_order import _positive_int


@pytest.mark.parametrize(("value", "expected"), [("1", 1), ("25", 25), ("100000", 100000)])
def test_positive_stars_test_amount(value: str, expected: int) -> None:
    assert _positive_int(value) == expected


@pytest.mark.parametrize("value", ["0", "-1", "100001", "not-a-number"])
def test_invalid_stars_test_amount_is_rejected(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int(value)
