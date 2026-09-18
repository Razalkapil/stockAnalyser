"""Load market data for a backtest, and prepare it point-in-time.

Everything a backtest reads from the lake goes through ``store.duck``.
Two derived columns are computed here, both strictly from the PAST:

  prev_close    the previous bar's adjusted close for the same symbol
                (for circuit-lock detection). Adjusted series are
                continuous across corporate actions, so the ratio is right.
  adv_turnover  trailing-window median turnover, ``shift(1)`` so a bar's
                own value never informs its own slippage tier.

Identity is (exchange, symbol) as printed on the bar. Delisted names
stay -- they have bars even though the current-listings master no longer
knows them -- which is what avoids survivorship bias.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from stk.backtest.view import MarketData
from stk.store import duck


def prepare_bars(bars: pd.DataFrame, adv_lookback_days: int) -> pd.DataFrame:
    """Add prev_close and adv_turnover (both past-only) to a raw adjusted-bars frame."""
    df = bars.sort_values(["symbol", "date"], kind="stable").copy()
    grouped = df.groupby("symbol", sort=False)
    df["prev_close"] = grouped["close"].shift(1)
    df["adv_turnover"] = grouped["turnover"].transform(
        lambda s: s.shift(1).rolling(adv_lookback_days, min_periods=1).median()
    )
    return df


def load_market_data(
    parquet_root: Path,
    *,
    exchange: str,
    start: date,
    end: date,
    adv_lookback_days: int,
    warmup_days: int = 0,
) -> MarketData:
    """Adjusted bars for [start - warmup, end], prepared for the engine."""
    load_from = start - pd.Timedelta(days=warmup_days) if warmup_days else start
    with duck.connect(parquet_root) as session:
        raw = session.sql(
            "backtest_panel", [exchange, load_from.isoformat(), end.isoformat()]
        ).df()
    if raw.empty:
        raise ValueError(
            f"no adjusted bars for {exchange} in [{load_from}, {end}] -- "
            "run `stk backfill prices` and `stk ingest adjustments` first"
        )
    return MarketData(prepare_bars(raw, adv_lookback_days))


def load_benchmark(parquet_root: Path, *, index_code: str, start: date, end: date) -> pd.DataFrame:
    """Benchmark closes keyed on the canonical index_code (never the printed name)."""
    with duck.connect(parquet_root) as session:
        return session.sql(
            "benchmark_series", [index_code, start.isoformat(), end.isoformat()]
        ).df()
