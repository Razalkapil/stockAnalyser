"""Slippage tiers, participation cap, circuit-lock heuristic."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stk.domain.costs import Side
from stk.domain.fills import BarPrices, Lock, can_buy, can_sell, circuit_lock
from stk.domain.slippage import SlippageTier, apply_slippage, cap_quantity, slippage_bps

TIERS = (
    SlippageTier(Decimal(500_000_000), Decimal(5)),
    SlippageTier(Decimal(100_000_000), Decimal(10)),
    SlippageTier(Decimal(0), Decimal(40)),
)
BANDS = (Decimal(2), Decimal(5), Decimal(10), Decimal(20))


def frozen(px: str) -> BarPrices:
    p = Decimal(px)
    return BarPrices(p, p, p, p)


class TestSlippage:
    def test_tier_selection(self):
        assert slippage_bps(Decimal(900_000_000), TIERS) == 5
        assert slippage_bps(Decimal(100_000_000), TIERS) == 10  # boundary is inclusive
        assert slippage_bps(Decimal(1), TIERS) == 40

    def test_unknown_adv_gets_the_worst_tier_not_the_best(self):
        assert slippage_bps(None, TIERS) == 40

    def test_adverse_direction(self):
        assert apply_slippage(Decimal(100), Side.BUY, Decimal(10)) == Decimal("100.10")
        assert apply_slippage(Decimal(100), Side.SELL, Decimal(10)) == Decimal("99.90")

    def test_no_tiers_is_an_error(self):
        with pytest.raises(ValueError):
            slippage_bps(Decimal(1), ())


class TestParticipationCap:
    def test_caps_to_fraction_of_volume(self):
        assert cap_quantity(1000, 10_000, Decimal("0.05")) == 500

    def test_small_order_untouched(self):
        assert cap_quantity(10, 10_000, Decimal("0.05")) == 10

    def test_zero_volume_fills_nothing(self):
        assert cap_quantity(10, 0, Decimal("0.05")) == 0

    @pytest.mark.parametrize("cap", [Decimal(0), Decimal("1.5")])
    def test_bad_cap_rejected(self, cap):
        with pytest.raises(ValueError):
            cap_quantity(10, 100, cap)


class TestCircuitLock:
    def test_frozen_at_upper_band_is_upper_lock(self):
        assert circuit_lock(frozen("110"), Decimal(100), BANDS) is Lock.UPPER  # +10%

    def test_frozen_at_lower_band_is_lower_lock(self):
        assert circuit_lock(frozen("95"), Decimal(100), BANDS) is Lock.LOWER  # -5%

    def test_frozen_at_a_non_band_move_is_not_a_lock(self):
        """An illiquid name that simply didn't trade and closed +3.2% is not locked."""
        assert circuit_lock(frozen("103.2"), Decimal(100), BANDS) is Lock.NONE

    def test_a_bar_that_traded_is_not_locked_even_at_a_band(self):
        bar = BarPrices(Decimal(109), Decimal(110), Decimal(108), Decimal(110))
        assert circuit_lock(bar, Decimal(100), BANDS) is Lock.NONE

    def test_no_prev_close_is_not_a_lock(self):
        assert circuit_lock(frozen("110"), None, BANDS) is Lock.NONE

    def test_rounding_tolerance(self):
        # +9.9% from a tick-rounded 10% band still counts
        assert circuit_lock(frozen("109.9"), Decimal(100), BANDS) is Lock.UPPER

    def test_directional_blocks(self):
        assert not can_buy(Lock.UPPER) and can_sell(Lock.UPPER)
        assert not can_sell(Lock.LOWER) and can_buy(Lock.LOWER)
        assert can_buy(Lock.NONE) and can_sell(Lock.NONE)
