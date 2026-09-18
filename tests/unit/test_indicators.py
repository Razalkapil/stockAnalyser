"""Indicators: hand-worked values, and the mechanical no-look-ahead proof."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stk.domain.indicators import compute_indicators


def panel(closes: dict[str, list[float]], vol: int = 1000, spread: float = 0.0) -> pd.DataFrame:
    rows = []
    for sym, cs in closes.items():
        days = pd.bdate_range("2023-01-02", periods=len(cs))
        for d, c in zip(days, cs, strict=True):
            rows.append(dict(date=d, symbol=sym, open=c, high=c * (1 + spread),
                             low=c * (1 - spread), close=c, volume=vol, turnover=c * vol))
    return pd.DataFrame(rows)


def random_panel(n: int = 320, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for sym in ("AAA", "BBB", "CCC"):
        close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.015, n))
        days = pd.bdate_range("2022-01-03", periods=n)
        for d, c in zip(days, close, strict=True):
            rows.append(dict(
                date=d, symbol=sym, open=c * (1 + rng.normal(0, 0.004)),
                high=c * 1.01, low=c * 0.99, close=c,
                volume=int(rng.integers(50_000, 500_000)), turnover=c * 200_000,
                delivery_pct=float(rng.uniform(20, 70)),
            ))
    return pd.DataFrame(rows)


def index_series(df: pd.DataFrame, seed: int = 9) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = sorted(df["date"].unique())
    return pd.Series(1000 * np.cumprod(1 + rng.normal(0.0002, 0.008, len(dates))), index=dates)


class TestHandWorked:
    def test_sma20_is_the_trailing_mean_including_today(self):
        out = compute_indicators(panel({"A": list(range(1, 41))}))
        a = out[out.symbol == "A"].reset_index(drop=True)
        assert np.isnan(a["sma20"].iloc[18])  # not enough history yet
        assert a["sma20"].iloc[19] == pytest.approx(10.5)  # mean(1..20)
        assert a["sma20"].iloc[39] == pytest.approx(30.5)  # mean(21..40)

    def test_return_over_n_days(self):
        out = compute_indicators(panel({"A": [100.0] * 5 + [110.0]}))
        assert out["ret5"].iloc[5] == pytest.approx(0.10)
        assert np.isnan(out["ret5"].iloc[4])

    def test_rsi_is_100_when_price_only_rises_and_0_when_only_falls(self):
        up = compute_indicators(panel({"U": [100.0 + i for i in range(40)]}))
        down = compute_indicators(panel({"D": [200.0 - i for i in range(40)]}))
        assert up["rsi14"].iloc[-1] == pytest.approx(100.0)
        assert down["rsi14"].iloc[-1] == pytest.approx(0.0)

    def test_rsi_stays_in_bounds_on_noise(self):
        out = compute_indicators(random_panel())
        r = out["rsi14"].dropna()
        assert len(r) > 100 and r.between(0, 100).all()

    def test_atr_of_a_constant_range_equals_that_range(self):
        out = compute_indicators(panel({"A": [100.0] * 40}, spread=0.01))  # H-L = 2
        assert out["atr14"].iloc[-1] == pytest.approx(2.0)
        assert out["atr_pct14"].iloc[-1] == pytest.approx(0.02)

    def test_breakout_compares_today_against_the_PRIOR_window(self):
        """high_prior20 must end at t-1. If it included today, `close > high_prior20`
        could never be true and every breakout strategy would silently fire never."""
        closes = [100.0] * 25 + [120.0]
        out = compute_indicators(panel({"A": closes}))
        last = out.iloc[-1]
        assert last["high_prior20"] == pytest.approx(100.0)
        assert last["close"] > last["high_prior20"]

    def test_volume_ratio_uses_the_prior_average_not_including_today(self):
        p = panel({"A": [100.0] * 30})
        p.loc[p.index[-1], "volume"] = 5000  # 5x the 1000 baseline
        out = compute_indicators(p)
        assert out["vol_ratio20"].iloc[-1] == pytest.approx(5.0)

    def test_gap_pct(self):
        p = panel({"A": [100.0, 100.0]})
        p.loc[1, "open"] = 103.0
        assert compute_indicators(p)["gap_pct"].iloc[1] == pytest.approx(3.0)

    def test_close_location(self):
        p = panel({"A": [100.0, 100.0]})
        p.loc[1, ["high", "low", "close"]] = [110.0, 100.0, 108.0]
        assert compute_indicators(p)["close_location"].iloc[1] == pytest.approx(0.8)

    def test_close_location_is_nan_not_a_crash_on_a_frozen_bar(self):
        assert np.isnan(compute_indicators(panel({"A": [100.0, 100.0]}))["close_location"].iloc[1])

    def test_close_raw_undoes_the_adjustment_factor(self):
        p = panel({"A": [50.0, 50.0]})
        p["cumulative_price_factor"] = 0.5  # a later 1:1 bonus halved this bar
        assert compute_indicators(p)["close_raw"].iloc[0] == pytest.approx(100.0)

    def test_symbols_do_not_leak_into_each_other(self):
        out = compute_indicators(panel({"A": [10.0] * 30, "B": [1000.0] * 30}))
        assert out[out.symbol == "A"]["sma20"].dropna().eq(10.0).all()
        assert out[out.symbol == "B"]["sma20"].dropna().eq(1000.0).all()


class TestRelativeStrength:
    def test_without_a_benchmark_it_is_nan_never_zero(self):
        out = compute_indicators(random_panel())
        assert out["rs63"].isna().all()

    def test_stock_minus_index_return(self):
        closes = [100.0] * 65 + [120.0]  # +20% over the last 63 sessions from the flat base
        p = panel({"A": closes})
        idx = pd.Series(np.concatenate([np.full(65, 1000.0), [1050.0]]), index=sorted(p["date"]))
        out = compute_indicators(p, idx)
        assert out["rs63"].iloc[-1] == pytest.approx(0.20 - 0.05)


class TestNoLookAhead:
    NON_FEATURE = frozenset({"date", "symbol", "open", "high", "low", "close", "volume",
                             "turnover", "delivery_pct", "cumulative_price_factor"})

    @pytest.mark.parametrize("cut", [40, 130, 260, 300])
    def test_truncating_history_never_changes_an_earlier_row(self, cut):
        """THE proof. Indicators on bars up to D == the same rows computed on the full
        history. Any column that peeks at t+1 (or uses a centred/back-filled window)
        would differ here."""
        full_bars = random_panel()
        idx = index_series(full_bars)
        days = sorted(full_bars["date"].unique())
        cutoff = days[cut]

        full = compute_indicators(full_bars, idx)
        trunc = compute_indicators(full_bars[full_bars.date <= cutoff], idx[idx.index <= cutoff])

        a = full[full.date <= cutoff].reset_index(drop=True)
        b = trunc.reset_index(drop=True)
        feature_cols = [c for c in a.columns if c not in self.NON_FEATURE]
        assert len(feature_cols) > 30  # guard against comparing an empty set
        pd.testing.assert_frame_equal(a[feature_cols], b[feature_cols], check_exact=False,
                                      rtol=1e-9, atol=1e-9)

    def test_poisoning_the_future_leaves_earlier_rows_untouched(self):
        bars = random_panel()
        days = sorted(bars["date"].unique())
        cutoff = days[200]
        poisoned = bars.copy()
        future = poisoned.date > cutoff
        for col in ("open", "high", "low", "close"):
            poisoned.loc[future, col] = 9999.0
        poisoned.loc[future, "volume"] = 1
        a = compute_indicators(bars)
        b = compute_indicators(poisoned)
        cols = [c for c in a.columns if c not in self.NON_FEATURE]
        pd.testing.assert_frame_equal(
            a[a.date <= cutoff][cols].reset_index(drop=True),
            b[b.date <= cutoff][cols].reset_index(drop=True),
            check_exact=False, rtol=1e-9, atol=1e-9,
        )
