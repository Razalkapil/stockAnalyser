"""compute_costs against hand-worked examples.

A wrong rate or a mis-scoped GST here is a persistent small bias in every
backtest and paper fill, so each number below was worked by hand from
config/costs.yaml and is asserted exactly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stk.config.costs import get_rate_schedule
from stk.core.money import bps
from stk.domain.costs import (
    BrokerageRule,
    CostRates,
    Product,
    ProductRates,
    Side,
    compute_costs,
    dp_charge,
)


@pytest.fixture(scope="module")
def schedule():
    return get_rate_schedule(force_reload=True)


def rates(schedule, exchange: str, d: date) -> CostRates:
    return schedule.rates_for(exchange, d)


class TestGoldenDeliverySell:
    """Rs 5,000 NSE delivery sell on 2026-09-18 (post 2026-03-01 rates)."""

    def test_itemised_charges(self, schedule):
        b = compute_costs(Side.SELL, Product.DELIVERY, Decimal(5000),
                          rates(schedule, "NSE", date(2026, 9, 18)))
        assert b.brokerage == Decimal("0.00")
        assert b.stt == Decimal("5.00")  # 0.1% of 5000
        assert b.stamp_duty == Decimal("0.00")  # buy side only
        assert b.exchange_txn == Decimal("0.15")  # 5000 * 0.000030699 = 0.1535
        assert b.ipft == Decimal("0.00")  # Rs 0.01/crore -> ~0.000005
        assert b.sebi_fee == Decimal("0.01")  # 5000 * 1e-6 = 0.005 -> rounds up
        # GST = 18% of (0 + 0.15 + 0.00 + 0.01) = 0.0288 -> 0.03
        assert b.gst == Decimal("0.03")
        assert b.total == Decimal("5.19")

    def test_dp_charge_dominates_small_sells_at_about_31_bps(self, schedule):
        """Rs 13 + 18% GST = Rs 15.34; on Rs 5,000 that is ~30.7 bps -- the
        build plan's '~31 bps'. NB this is the DP charge ALONE; the all-in
        cost of the sell is ~41 bps once STT is added. Both are pinned so
        nobody 'fixes' 41 down to 31 or vice versa."""
        r = rates(schedule, "NSE", date(2026, 9, 18))
        dp = dp_charge(r)
        assert dp == Decimal("15.34")
        assert 30 < bps(dp, Decimal(5000)) < 31
        all_in = compute_costs(Side.SELL, Product.DELIVERY, Decimal(5000), r).total + dp
        assert all_in == Decimal("20.53")
        assert 41 < bps(all_in, Decimal(5000)) < 42


class TestBoundaries:
    def test_exchange_txn_and_ipft_change_on_2026_03_01(self, schedule):
        turnover = Decimal(1_000_000)  # Rs 10 lakh: big enough that rounding can't hide a change
        before = compute_costs(Side.BUY, Product.DELIVERY, turnover,
                               rates(schedule, "NSE", date(2026, 2, 27)))
        after = compute_costs(Side.BUY, Product.DELIVERY, turnover,
                              rates(schedule, "NSE", date(2026, 3, 2)))
        assert before.exchange_txn == Decimal("29.70")  # 0.0000297
        # NSE/FA/73061: Rs 306.99/crore. Txn + IPFT = Rs 307/crore both before
        # (297 + 10) and after (306.99 + 0.01): the circular's "no change in outflow".
        assert after.exchange_txn == Decimal("30.70")  # 1e6 * 0.000030699 = 30.699
        assert before.ipft == Decimal("1.00")  # Rs 10/crore on 10 lakh
        assert after.ipft == Decimal("0.00")  # Rs 0.01/crore -> 0.001

    def test_total_txn_plus_ipft_outflow_is_unchanged_across_the_boundary(self, schedule):
        """The circular's whole point: the cash-market outflow stays Rs 307/crore."""
        crore = Decimal(10_000_000)
        for d in (date(2026, 2, 27), date(2026, 3, 2)):
            b = compute_costs(Side.BUY, Product.DELIVERY, crore, rates(schedule, "NSE", d))
            assert b.exchange_txn + b.ipft == Decimal("307.00")

    def test_stamp_duty_buy_side_only(self, schedule):
        r = rates(schedule, "NSE", date(2026, 9, 18))
        buy = compute_costs(Side.BUY, Product.DELIVERY, Decimal(100_000), r)
        sell = compute_costs(Side.SELL, Product.DELIVERY, Decimal(100_000), r)
        assert buy.stamp_duty == Decimal("15.00")  # 0.015%
        assert sell.stamp_duty == Decimal("0.00")

    def test_bse_has_no_ipft(self, schedule):
        b = compute_costs(Side.BUY, Product.DELIVERY, Decimal(1_000_000),
                          rates(schedule, "BSE", date(2025, 1, 1)))
        assert b.ipft == Decimal("0.00")

    def test_intraday_stt_sell_leg_only(self, schedule):
        r = rates(schedule, "NSE", date(2026, 9, 18))
        buy = compute_costs(Side.BUY, Product.INTRADAY, Decimal(100_000), r)
        sell = compute_costs(Side.SELL, Product.INTRADAY, Decimal(100_000), r)
        assert buy.stt == Decimal("0.00")
        assert sell.stt == Decimal("25.00")  # 0.025%

    def test_intraday_brokerage_is_min_of_pct_and_flat(self, schedule):
        r = rates(schedule, "NSE", date(2026, 9, 18))
        small = compute_costs(Side.BUY, Product.INTRADAY, Decimal(10_000), r)
        large = compute_costs(Side.BUY, Product.INTRADAY, Decimal(1_000_000), r)
        assert small.brokerage == Decimal("3.00")  # 0.03% < Rs 20
        assert large.brokerage == Decimal("20.00")  # flat cap


def _synthetic(
    gst_rate: Decimal, stt: Decimal, stamp: Decimal, brokerage_flat: Decimal
) -> CostRates:
    pr = ProductRates(BrokerageRule("flat_per_order", flat=brokerage_flat), stt, stt, stamp, stamp)
    return CostRates(
        gst_rate=gst_rate,
        gst_applies_to=frozenset({"brokerage", "exchange_txn", "sebi_turnover_fee", "ipft"}),
        delivery=pr, intraday=pr,
        exchange_txn_rate=Decimal("0.00003"), ipft_per_crore=Decimal(10),
        sebi_rate=Decimal("0.000001"), dp_charge_inr=Decimal(13), dp_gst_applicable=True,
    )


class TestGstScope:
    @given(
        stt=st.decimals(min_value=0, max_value=Decimal("0.01"), places=5),
        stamp=st.decimals(min_value=0, max_value=Decimal("0.01"), places=5),
        turnover=st.integers(min_value=1000, max_value=10_000_000),
    )
    def test_gst_never_depends_on_stt_or_stamp(self, stt, stamp, turnover):
        """Changing STT or stamp duty must not change GST -- the one-line bug the
        config warns about (a persistent small bias if GST is levied on them)."""
        t = Decimal(turnover)
        base = compute_costs(Side.BUY, Product.DELIVERY, t,
                             _synthetic(Decimal("0.18"), Decimal(0), Decimal(0), Decimal(20)))
        other = compute_costs(Side.BUY, Product.DELIVERY, t,
                              _synthetic(Decimal("0.18"), stt, stamp, Decimal(20)))
        assert other.gst == base.gst

    def test_gst_is_on_the_taxable_subset(self):
        r = _synthetic(Decimal("0.18"), Decimal("0.001"), Decimal("0.00015"), Decimal(20))
        b = compute_costs(Side.BUY, Product.DELIVERY, Decimal(1_000_000), r)
        taxable = b.brokerage + b.exchange_txn + b.sebi_fee + b.ipft
        assert b.gst == (taxable * Decimal("0.18")).quantize(Decimal("0.01"))

    def test_negative_turnover_rejected(self, schedule):
        with pytest.raises(ValueError):
            compute_costs(Side.BUY, Product.DELIVERY, Decimal(-1),
                          rates(schedule, "NSE", date(2026, 9, 18)))
