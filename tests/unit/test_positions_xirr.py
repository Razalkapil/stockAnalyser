"""Average-cost positions, split/bonus handling, dividends, and XIRR."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stk.domain.positions import (
    Position,
    PositionError,
    apply_buy,
    apply_sell,
    apply_split_or_bonus,
    dividend_cash,
)
from stk.domain.xirr import xirr

D = Decimal


class TestAverageCost:
    def test_buys_blend_into_an_average(self):
        p = apply_buy(apply_buy(Position(), 10, D("100")), 30, D("120"))
        assert (p.qty, p.avg_cost) == (40, D("115"))  # (1000 + 3600) / 40

    def test_partial_sell_realises_against_the_average_and_keeps_it(self):
        p = apply_buy(Position(), 40, D("115"))
        p = apply_sell(p, 10, D("130"))
        assert (p.qty, p.avg_cost, p.realised_pnl) == (30, D("115"), D("150"))

    def test_selling_at_a_loss(self):
        p = apply_sell(apply_buy(Position(), 10, D("100")), 10, D("90"))
        assert p.realised_pnl == D("-100")

    def test_a_closed_position_carries_no_stale_cost(self):
        p = apply_sell(apply_buy(Position(), 10, D("100")), 10, D("100"))
        assert (p.qty, p.avg_cost) == (0, D("0"))
        assert apply_buy(p, 5, D("50")).avg_cost == D("50")  # not blended with the dead one

    def test_realised_pnl_accumulates_across_round_trips(self):
        p = apply_sell(apply_buy(Position(), 10, D("100")), 10, D("110"))
        p = apply_sell(apply_buy(p, 10, D("200")), 10, D("190"))
        assert p.realised_pnl == D("0")  # +100 then -100

    def test_no_shorting(self):
        with pytest.raises(PositionError, match="only 5 held"):
            apply_sell(apply_buy(Position(), 5, D("100")), 6, D("100"))

    @pytest.mark.parametrize("fn", [apply_buy, apply_sell])
    def test_quantity_must_be_positive(self, fn):
        with pytest.raises(PositionError):
            fn(Position(10, D("1")), 0, D("1"))

    def test_unrealised(self):
        assert Position(10, D("100")).unrealised(D("112")) == D("120")


class TestSplitAndBonus:
    def test_one_to_one_bonus_doubles_shares_and_halves_the_average_cost_unchanged(self):
        r = apply_split_or_bonus(Position(10, D("100"), D("5")), D("2"))
        assert (r.position.qty, r.position.avg_cost) == (20, D("50"))
        assert r.position.cost_basis == D("1000")  # what you paid is unchanged
        assert r.position.realised_pnl == D("5")  # history is untouched
        assert (r.dropped_shares, r.dropped_cost) == (D("0"), D("0"))

    def test_five_for_one_split(self):
        r = apply_split_or_bonus(Position(10, D("1000")), D("5"))
        assert (r.position.qty, r.position.avg_cost) == (50, D("200"))

    def test_a_fractional_entitlement_is_floored_and_its_cost_written_off(self):
        """3:2 bonus (factor 2.5) on 5 shares -> 12.5 -> 12; the 0.5 share does not exist."""
        r = apply_split_or_bonus(Position(5, D("100")), D("2.5"))
        assert r.position.qty == 12 and r.dropped_shares == D("0.5")
        assert r.position.cost_basis + r.dropped_cost == D("500")  # nothing vanishes silently
        assert r.dropped_cost == D("20")  # 0.5 / 12.5 of Rs 500

    def test_a_reverse_split_that_leaves_nothing(self):
        r = apply_split_or_bonus(Position(5, D("100")), D("0.1"))  # 10:1 consolidation
        assert r.position.qty == 0 and r.dropped_shares == D("0.5")
        assert r.dropped_cost == D("500")

    def test_a_reverse_split(self):
        r = apply_split_or_bonus(Position(100, D("10")), D("0.1"))
        assert (r.position.qty, r.position.avg_cost) == (10, D("100"))

    def test_an_empty_position_is_untouched_and_bad_factors_are_rejected(self):
        assert apply_split_or_bonus(Position(), D("2")).position == Position()
        with pytest.raises(PositionError):
            apply_split_or_bonus(Position(1, D("1")), D("0"))


class TestDividends:
    def test_cash_is_per_share_times_shares_held(self):
        assert dividend_cash(150, D("17.70")) == D("2655.00")

    def test_rounds_to_paise(self):
        assert dividend_cash(3, D("0.333")) == D("1.00")

    def test_negative_inputs_rejected(self):
        with pytest.raises(PositionError):
            dividend_cash(-1, D("1"))


class TestXirr:
    def test_matches_the_spreadsheet_result(self):
        # Excel: =XIRR({-1000,1100},{2025-01-01,2026-01-01}) -> 0.100000 (365 days)
        r = xirr([(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 1100.0)])
        assert r == pytest.approx(0.10, abs=1e-6)

    def test_multiple_flows(self):
        """-10000 (2024-01-01), -5000 (2024-07-01), +16000 (2025-01-01); actual/365.

        Worked by hand, not taken from any tool: 2024-07-01 is 182 days in and 2025-01-01 is 366
        (2024 is a leap year), so at r = 8%
            -10000 - 5000/1.08^(182/365) + 16000/1.08^(366/365)
          = -10000 - 4811.8 + 14811.7 = -0.1  ~= 0.
        """
        flows = [(date(2024, 1, 1), -10000.0), (date(2024, 7, 1), -5000.0),
                 (date(2025, 1, 1), 16000.0)]
        r = xirr(flows)
        assert r == pytest.approx(0.08, abs=1e-4)
        # ...and the defining property, independent of the solver: NPV at that rate is zero
        npv = sum(cf / (1 + r) ** ((d - flows[0][0]).days / 365) for d, cf in flows)
        assert npv == pytest.approx(0.0, abs=1e-6)

    def test_a_loss_is_negative(self):
        r = xirr([(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 800.0)])
        assert r == pytest.approx(-0.20, abs=1e-6)

    def test_order_of_input_does_not_matter(self):
        a = xirr([(date(2026, 1, 1), 1100.0), (date(2025, 1, 1), -1000.0)])
        b = xirr([(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 1100.0)])
        assert a == pytest.approx(b)

    def test_a_short_holding_annualises(self):
        # +1% in 30 days is about +12.8% a year
        r = xirr([(date(2025, 1, 1), -1000.0), (date(2025, 1, 31), 1010.0)])
        assert r == pytest.approx(1.01 ** (365 / 30) - 1, abs=1e-6)

    @pytest.mark.parametrize("flows", [
        [],
        [(date(2025, 1, 1), -100.0)],
        [(date(2025, 1, 1), -100.0), (date(2026, 1, 1), -50.0)],  # never got anything back
        [(date(2025, 1, 1), 100.0), (date(2026, 1, 1), 50.0)],  # never put anything in
        [(date(2025, 1, 1), -100.0), (date(2025, 1, 1), 110.0)],  # all one day
    ])
    def test_no_answer_is_none_never_zero(self, flows):
        assert xirr(flows) is None

    def test_a_huge_return_still_converges(self):
        r = xirr([(date(2025, 1, 1), -100.0), (date(2025, 3, 1), 500.0)])
        assert r is not None and r > 100  # thousands of percent, but a real answer
