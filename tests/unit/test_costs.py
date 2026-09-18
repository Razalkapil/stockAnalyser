"""Tests for the dated cost-rate schedule (config/costs.yaml + RateSchedule).

Phase 1 scope: loading and date-resolution only. The actual
compute_costs() pipeline is phase 2 -- but the rate-boundary resolution
tested here is exactly what would silently corrupt a 2010-2026 backtest
if it picked the wrong rate on either side of a transition date.
"""

from __future__ import annotations

from datetime import date

import pytest

from stk.config.costs import get_rate_schedule


@pytest.fixture
def schedule():
    return get_rate_schedule(force_reload=True)


class TestExchangeTxnBoundary:
    """NSE exchange transaction charge changed 2024-10-01 and again 2026-03-01."""

    def test_rate_before_first_transition(self, schedule):
        # Before 2024-10-01, only the (hypothetical earlier) entry would
        # apply -- our schedule's earliest NSE entry is 2024-10-01, so a
        # date before that resolves to the earliest available entry.
        rate = schedule.exchange_txn_as_of("NSE", date(2024, 1, 1))
        assert rate.rate == pytest.approx(0.0000297)

    def test_rate_day_before_second_transition(self, schedule):
        rate = schedule.exchange_txn_as_of("NSE", date(2026, 2, 28))
        assert rate.rate == pytest.approx(0.0000297)

    def test_rate_on_second_transition_day(self, schedule):
        rate = schedule.exchange_txn_as_of("NSE", date(2026, 3, 1))
        assert rate.rate == pytest.approx(0.0000307)

    def test_bse_rate_unaffected_by_nse_transition(self, schedule):
        rate = schedule.exchange_txn_as_of("BSE", date(2026, 3, 1))
        assert rate.rate == pytest.approx(0.0000375)


class TestIpftBoundary:
    """NSE IPFT dropped from Rs 10/crore to Rs 0.01/crore on 2026-03-01."""

    def test_rate_before_transition(self, schedule):
        rate = schedule.ipft_as_of("NSE", date(2026, 2, 28))
        assert rate.per_crore_inr == pytest.approx(10.0)

    def test_rate_on_transition_day(self, schedule):
        rate = schedule.ipft_as_of("NSE", date(2026, 3, 1))
        assert rate.per_crore_inr == pytest.approx(0.01)


class TestStampDutyBoundary:
    """Stamp duty became uniform nationwide on 2020-07-01."""

    def test_rate_on_effective_date(self, schedule):
        rate = schedule.stamp_duty_as_of(date(2020, 7, 1))
        assert rate.delivery["buy"] == pytest.approx(0.00015)
        assert rate.delivery["sell"] == pytest.approx(0.0)

    def test_intraday_stamp_duty_lower_than_delivery(self, schedule):
        rate = schedule.stamp_duty_as_of(date(2024, 1, 1))
        assert rate.intraday["buy"] < rate.delivery["buy"]


class TestSttAsymmetry:
    """STT: delivery both legs; intraday sell-leg only."""

    def test_delivery_stt_both_legs(self, schedule):
        rate = schedule.stt_as_of(date(2024, 1, 1))
        assert rate.delivery["buy"] == pytest.approx(0.001)
        assert rate.delivery["sell"] == pytest.approx(0.001)

    def test_intraday_stt_buy_leg_is_zero(self, schedule):
        rate = schedule.stt_as_of(date(2024, 1, 1))
        assert rate.intraday["buy"] == pytest.approx(0.0)
        assert rate.intraday["sell"] == pytest.approx(0.00025)


class TestGstScope:
    """GST must apply to brokerage/exchange_txn/sebi fee/IPFT and NOT to
    STT or stamp duty. Getting this wrong is a one-line bug with a
    persistent small bias in every backtest."""

    def test_gst_applies_to_expected_components_only(self, schedule):
        assert set(schedule.gst_applies_to) == {
            "brokerage",
            "exchange_txn",
            "sebi_turnover_fee",
            "ipft",
        }

    def test_stt_and_stamp_duty_excluded_from_gst_scope(self, schedule):
        assert "stt" not in schedule.gst_applies_to
        assert "stamp_duty" not in schedule.gst_applies_to


class TestDpCharge:
    """DP charge: flat, per-scrip, per-day, sell leg only -- dominates
    cost on small delivery sells (e.g. ~31bps on a Rs 5,000 sell)."""

    def test_dp_charge_is_flat_not_percentage(self, schedule):
        rate = schedule.dp_charge_as_of(date(2024, 1, 1))
        assert rate.per_scrip_inr == pytest.approx(13.0)

    def test_dp_charge_dominates_small_delivery_sell(self, schedule):
        # Illustrative golden-value check: on a Rs 5,000 sell, the flat
        # DP charge alone is already ~26bps (13 / 5000 = 0.0026), before
        # GST or any percentage-based charge is even added -- confirming
        # this is NOT negligible the way a percentage-only cost model
        # would assume.
        dp = schedule.dp_charge_as_of(date(2024, 1, 1))
        sell_value = 5000.0
        dp_bps = (dp.per_scrip_inr / sell_value) * 10_000
        assert dp_bps > 20  # meaningfully large relative to bps-scale exchange fees
