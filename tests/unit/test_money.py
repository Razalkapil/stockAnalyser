"""Tests for Decimal money helpers and Indian (lakh/crore) formatting."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stk.core.money import bps, format_inr, to_money


class TestFormatInr:
    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            (1234567.5, "₹12,34,567.50"),
            (99, "₹99.00"),
            (100000, "₹1,00,000.00"),
            (0, "₹0.00"),
            (999, "₹999.00"),
            (1000, "₹1,000.00"),
            (10000000, "₹1,00,00,000.00"),  # 1 crore
        ],
    )
    def test_grouping(self, amount, expected):
        assert format_inr(amount) == expected

    def test_negative_amount(self):
        assert format_inr(-950) == "-₹950.00"

    def test_no_symbol(self):
        assert format_inr(1234567.5, symbol=False) == "12,34,567.50"


class TestToMoney:
    def test_rounds_to_paise(self):
        assert to_money(1.005) == Decimal("1.01") or to_money(1.005) == Decimal("1.00")
        # Decimal("1.005") from a string is exact, so ROUND_HALF_UP gives 1.01.
        assert to_money("1.005") == Decimal("1.01")

    def test_float_precision_is_not_leaked(self):
        # 0.1 + 0.2 != 0.3 in binary float; to_money must not carry that error.
        result = to_money(str(0.1 + 0.2))
        assert result == Decimal("0.30")


class TestBps:
    def test_basic(self):
        assert bps(Decimal("50"), Decimal("10000")) == Decimal("50")

    def test_zero_basis_returns_zero(self):
        assert bps(Decimal("50"), Decimal("0")) == Decimal("0")
