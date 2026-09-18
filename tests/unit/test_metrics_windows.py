"""Metrics on hand-worked curves; walk-forward window generation."""

from __future__ import annotations

import itertools
import math
from datetime import date

import pytest

from stk.domain.metrics import (
    TradeResult,
    cagr,
    compute_metrics,
    max_drawdown,
    sharpe,
)
from stk.domain.walkforward import generate_windows


class TestMaxDrawdown:
    def test_peak_to_trough(self):
        assert max_drawdown([100, 120, 90, 110]) == pytest.approx(-0.25)  # 120 -> 90

    def test_monotone_rise_has_none(self):
        assert max_drawdown([100, 101, 102]) == 0.0

    def test_uses_worst_of_several(self):
        assert max_drawdown([100, 90, 200, 150]) == pytest.approx(-0.25)


class TestCagr:
    def test_doubling_over_two_years(self):
        assert cagr(100, 200, date(2020, 1, 1), date(2022, 1, 1)) == pytest.approx(
            2 ** (365.25 / 731) - 1
        )

    def test_degenerate_inputs_are_zero_not_errors(self):
        assert cagr(100, 200, date(2020, 1, 1), date(2020, 1, 1)) == 0.0
        assert cagr(0, 200, date(2020, 1, 1), date(2021, 1, 1)) == 0.0


class TestSharpe:
    def test_no_variance_is_zero(self):
        assert sharpe([100, 100, 100, 100]) == 0.0

    def test_positive_drift_positive_sharpe(self):
        assert sharpe([100, 101, 101.5, 103, 103.2, 105]) > 0

    def test_too_short_is_zero(self):
        assert sharpe([100, 101]) == 0.0


class TestComputeMetrics:
    dates = tuple(date(2024, 1, d) for d in (1, 2, 3, 4, 5))

    def test_trade_stats_hand_worked(self):
        trades = [TradeResult(100, 0.10, 3), TradeResult(50, 0.05, 2), TradeResult(-40, -0.04, 1)]
        m = compute_metrics(self.dates, [1000, 1020, 1010, 1080, 1110], [0.5] * 5, trades)
        assert m.trade_count == 3
        assert m.win_rate == pytest.approx(2 / 3)
        assert m.avg_win == pytest.approx(75)
        assert m.avg_loss == pytest.approx(-40)
        assert m.profit_factor == pytest.approx(150 / 40)
        assert m.total_return == pytest.approx(0.11)
        assert m.exposure == pytest.approx(0.5)

    def test_no_losses_profit_factor_is_inf_not_a_crash(self):
        m = compute_metrics(self.dates, [1, 1, 1, 1, 1], [0] * 5, [TradeResult(5, 0.1, 1)])
        assert math.isinf(m.profit_factor)

    def test_no_trades(self):
        m = compute_metrics(self.dates, [1, 1, 1, 1, 1], [0] * 5, [])
        assert m.win_rate == 0.0 and m.profit_factor == 0.0 and m.trade_count == 0

    def test_benchmark_alpha(self):
        m = compute_metrics(self.dates, [100, 101, 102, 103, 110], [0.5] * 5, [],
                            benchmark_close=[100, 100, 100, 100, 104])
        assert m.benchmark_return == pytest.approx(0.04)
        assert m.alpha == pytest.approx(0.06)

    def test_missing_benchmark_is_none_not_zero(self):
        m = compute_metrics(self.dates, [100] * 5, [0] * 5, [])
        assert m.benchmark_return is None and m.alpha is None

    def test_misaligned_inputs_rejected(self):
        with pytest.raises(ValueError):
            compute_metrics(self.dates, [1, 2], [0, 0], [])


class TestWindows:
    def test_rolling_non_overlapping_test_windows(self):
        ws = generate_windows(date(2020, 1, 1), date(2023, 12, 31), train_months=24, test_months=6)
        assert [w.label for w in ws] == ["W1", "W2", "W3", "W4"][: len(ws)]
        assert ws[0].train_start == date(2020, 1, 1)
        assert ws[0].train_end == date(2021, 12, 31)
        assert ws[0].test_start == date(2022, 1, 1)
        assert ws[0].test_end == date(2022, 6, 30)
        assert ws[1].test_start == date(2022, 7, 1)  # next window starts where the last test ended
        for a, b in itertools.pairwise(ws):
            assert a.test_end < b.test_start

    def test_test_never_overlaps_its_own_train(self):
        for w in generate_windows(date(2015, 1, 1), date(2024, 12, 31), train_months=36,
                                  test_months=12):
            assert w.train_end < w.test_start

    def test_partial_final_window_is_dropped_not_truncated(self):
        ws = generate_windows(date(2020, 1, 1), date(2022, 3, 31), train_months=24, test_months=6)
        assert ws == []  # only 3 months of test room

    def test_bad_arguments(self):
        with pytest.raises(ValueError):
            generate_windows(date(2020, 1, 1), date(2024, 1, 1), train_months=0, test_months=6)
