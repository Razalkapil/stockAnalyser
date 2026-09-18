"""Technical indicators over a multi-symbol daily panel -- pure pandas.

Every column here is computed from the PAST only. That is a hard
invariant, not a style choice: a strategy reads these columns on the
decision date, and a window that quietly includes the current or a future
bar is look-ahead. Rules the code follows:

  * "prior" windows (``high_prior20``, ``vol_ratio20`` denominators, ...)
    END AT t-1, so a breakout test `close > high_prior20` compares today
    against yesterday's range and can actually fire.
  * Windows that legitimately include today (``sma20``, ``rsi14``) use
    only bars up to and including t.
  * No centred windows, no back-fill, no forward shift (negative shifts).

The truncation-invariance test (`tests/unit/test_indicators.py`) enforces
this mechanically: indicators computed on bars up to D must equal the same
rows of indicators computed on the full history.

Input frame columns: date, symbol, open, high, low, close, volume,
turnover; optional delivery_pct, cumulative_price_factor. Prices are the
BACK-ADJUSTED series, so ratios between them are stable when a later
corporate action arrives -- but absolute price LEVELS are not, hence
``close_raw`` (the unadjusted close) for anything that compares a price to
a rupee amount.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SMA_PERIODS = (20, 50, 100, 200)
EMA_PERIODS = (10, 20, 50, 100, 200)
RSI_PERIODS = (2, 14)
RET_PERIODS = (1, 5, 20, 60, 120, 250)
HIGH_PRIOR_PERIODS = (20, 55, 252)
LOW_PRIOR_PERIODS = (20, 60, 252)
RANGE_PRIOR_PERIODS = (10, 20)
RS_PERIODS = (63, 126, 252)
ATR_PERIOD = 14
ADV_PERIOD = 20


def _grouped(df: pd.DataFrame, col: str) -> pd.core.groupby.SeriesGroupBy:
    return df.groupby("symbol", sort=False)[col]


def _wilder(series: pd.Series, symbols: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (an EMA with alpha = 1/period), per symbol."""
    return series.groupby(symbols, sort=False).transform(
        lambda s: s.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    )


Cols = dict[str, "pd.Series | np.ndarray"]


def _trend(df: pd.DataFrame) -> Cols:
    close_g = _grouped(df, "close")
    cols: Cols = {}
    for n in SMA_PERIODS:
        cols[f"sma{n}"] = close_g.transform(lambda s, n=n: s.rolling(n, min_periods=n).mean())
    for n in EMA_PERIODS:
        cols[f"ema{n}"] = close_g.transform(
            lambda s, n=n: s.ewm(span=n, adjust=False, min_periods=n).mean()
        )
    return cols


def _oscillators(df: pd.DataFrame) -> Cols:
    sym = df["symbol"]
    prev_close = _grouped(df, "close").shift(1)
    cols: Cols = {}
    delta = df["close"] - prev_close
    gain, loss = delta.clip(lower=0.0), (-delta).clip(lower=0.0)
    for n in RSI_PERIODS:
        avg_gain, avg_loss = _wilder(gain, sym, n), _wilder(loss, sym, n)
        rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss.replace(0.0, np.nan))
        # No losses in the window at all -> RSI is 100, not NaN.
        cols[f"rsi{n}"] = rsi.where(~((avg_loss == 0.0) & avg_gain.notna()), 100.0)

    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=False)
    atr = _wilder(true_range, sym, ATR_PERIOD)
    cols[f"atr{ATR_PERIOD}"] = atr
    cols[f"atr_pct{ATR_PERIOD}"] = atr / df["close"]
    return cols


def _momentum(df: pd.DataFrame) -> Cols:
    close_g = _grouped(df, "close")
    cols: Cols = {f"ret{n}": df["close"] / close_g.shift(n) - 1.0 for n in RET_PERIODS}
    cols["mom_12_1"] = close_g.shift(21) / close_g.shift(252) - 1.0
    return cols


def _breakout_levels(df: pd.DataFrame) -> Cols:
    sym = df["symbol"]
    prev_close = _grouped(df, "close").shift(1)
    prior_high = _grouped(df, "high").shift(1)
    prior_low = _grouped(df, "low").shift(1)

    def roll_max(n: int) -> pd.Series:
        return prior_high.groupby(sym, sort=False).transform(
            lambda s: s.rolling(n, min_periods=n).max()
        )

    def roll_min(n: int) -> pd.Series:
        return prior_low.groupby(sym, sort=False).transform(
            lambda s: s.rolling(n, min_periods=n).min()
        )

    cols: Cols = {f"high_prior{n}": roll_max(n) for n in HIGH_PRIOR_PERIODS}
    cols.update({f"low_prior{n}": roll_min(n) for n in LOW_PRIOR_PERIODS})
    cols.update({f"range_pct_prior{n}": (roll_max(n) - roll_min(n)) / prev_close
                 for n in RANGE_PRIOR_PERIODS})
    # This one deliberately INCLUDES today: proximity of today's close to the 52-week high.
    cols["high_252_prox"] = df["close"] / _grouped(df, "high").transform(
        lambda s: s.rolling(252, min_periods=252).max()
    )
    return cols


def _volume_and_candles(df: pd.DataFrame) -> Cols:
    sym = df["symbol"]
    prev_close = _grouped(df, "close").shift(1)
    cols: Cols = {}
    cols["vol_ratio20"] = df["volume"] / _grouped(df, "volume").shift(1).groupby(
        sym, sort=False
    ).transform(lambda s: s.rolling(20, min_periods=20).mean())
    cols["gap_pct"] = (df["open"] / prev_close - 1.0) * 100.0
    cols["close_location"] = (df["close"] - df["low"]) / (df["high"] - df["low"]).replace(
        0.0, np.nan
    )
    # Liquidity: PRIOR-window median turnover (rupees), never including today.
    cols["turnover_med20"] = (
        _grouped(df, "turnover").shift(1).groupby(sym, sort=False)
        .transform(lambda s: s.rolling(ADV_PERIOD, min_periods=ADV_PERIOD).median())
    )
    cols["bar_count"] = df.groupby("symbol", sort=False).cumcount() + 1
    if "delivery_pct" in df.columns:
        cols["delivery_pct_sma20"] = (
            _grouped(df, "delivery_pct").shift(1).groupby(sym, sort=False)
            .transform(lambda s: s.rolling(20, min_periods=10).mean())
        )
    cols["close_raw"] = (
        df["close"] / df["cumulative_price_factor"]
        if "cumulative_price_factor" in df.columns
        else df["close"]
    )
    return cols


def _relative_strength(out: pd.DataFrame, index_close: pd.Series | None) -> None:
    trading_dates = out["date"].drop_duplicates().sort_values()
    idx: pd.Series | None = None
    if index_close is not None and not index_close.empty:
        idx = index_close.copy()
        idx.index = pd.to_datetime(idx.index)
        idx = idx[~idx.index.duplicated()].sort_index()
    for n in RS_PERIODS:
        if idx is None:
            out[f"rs{n}"] = np.nan
            continue
        # Index return over n index-sessions, carried forward onto stock dates the
        # index missed (never back-filled, so it only ever uses past index data).
        idx_ret = (idx / idx.shift(n) - 1.0).reindex(trading_dates).ffill()
        stock_ret = out["close"] / _grouped(out, "close").shift(n) - 1.0
        out[f"rs{n}"] = stock_ret - out["date"].map(idx_ret)


def compute_indicators(
    bars: pd.DataFrame, index_close: pd.Series | None = None
) -> pd.DataFrame:
    """Return ``bars`` (sorted by symbol, date) with every catalogue indicator added.

    ``index_close`` is the benchmark's close indexed by date; without it
    the relative-strength columns are all-NaN (never zero: "no benchmark"
    must not read as "no outperformance").
    """
    df = bars.sort_values(["symbol", "date"], kind="stable").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    cols: Cols = {}
    for family in (_trend, _oscillators, _momentum, _breakout_levels, _volume_and_candles):
        cols.update(family(df))
    out = pd.concat([df, pd.DataFrame(cols, index=df.index)], axis=1)
    _relative_strength(out, index_close)
    return out
