"""Tests for the pure liquidity-eligibility rule."""

from __future__ import annotations

from stk.domain.universe import (
    LiquidityMetrics,
    LiquidityThresholds,
    is_liquid,
    is_tradeable_intraday,
)

THRESHOLDS = LiquidityThresholds(
    min_median_turnover_inr=20_000_000,
    min_median_trades=500,
    min_price_inr=10,
    min_listed_days=120,
)


def _metrics(**overrides) -> LiquidityMetrics:
    defaults = dict(
        median_turnover_20d=50_000_000,
        median_volume_20d=100_000,
        median_trades_20d=1000,
        avg_price_20d=500.0,
        listed_days=500,
    )
    defaults.update(overrides)
    return LiquidityMetrics(**defaults)


class TestIsLiquid:
    def test_passes_all_thresholds(self):
        passed, _reason = is_liquid(_metrics(), THRESHOLDS)
        assert passed is True

    def test_fails_on_low_turnover(self):
        passed, reason = is_liquid(_metrics(median_turnover_20d=1_000_000), THRESHOLDS)
        assert passed is False
        assert "turnover" in reason

    def test_fails_on_low_trade_count(self):
        passed, reason = is_liquid(_metrics(median_trades_20d=10), THRESHOLDS)
        assert passed is False
        assert "trades" in reason

    def test_fails_on_penny_stock_price(self):
        passed, reason = is_liquid(_metrics(avg_price_20d=2.0), THRESHOLDS)
        assert passed is False
        assert "price" in reason

    def test_fails_on_recent_listing(self):
        passed, reason = is_liquid(_metrics(listed_days=30), THRESHOLDS)
        assert passed is False
        assert "listed_days" in reason

    def test_none_metrics_fail_closed_not_open(self):
        """A missing metric (e.g. no bars yet) must be treated as
        ineligible, never as passing by default."""
        passed, _reason = is_liquid(_metrics(median_turnover_20d=None), THRESHOLDS)
        assert passed is False

    def test_unreported_trades_skips_only_the_trades_check(self):
        """NSE's legacy bhavcopy (2010 to 2019-09) has no trades column, so the
        median is null for that whole era. That must not blanket-reject the era."""
        passed, reason = is_liquid(_metrics(median_trades_20d=None), THRESHOLDS)
        assert passed is True
        assert "trades check skipped" in reason

    def test_unreported_trades_still_enforces_the_other_checks(self):
        passed, reason = is_liquid(
            _metrics(median_trades_20d=None, median_turnover_20d=1_000_000), THRESHOLDS
        )
        assert passed is False
        assert "turnover" in reason

    def test_reason_always_populated(self):
        _, reason = is_liquid(_metrics(), THRESHOLDS)
        assert reason  # never empty, even on pass


class TestIsTradeableIntraday:
    def test_t2t_series_flagged_non_intraday(self):
        assert is_tradeable_intraday("BE", frozenset({"BE", "BZ"})) is False

    def test_normal_series_is_intraday_tradeable(self):
        assert is_tradeable_intraday("EQ", frozenset({"BE", "BZ"})) is True
