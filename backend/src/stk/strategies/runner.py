"""Run a registered strategy: load data, run the engine, run walk-forward.

The one place that wires together the data lake (via ``store.duck``), the
fundamentals ledger (SQLite), the DSL strategy and the backtest engine.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from stk.backtest.data import load_benchmark
from stk.backtest.engine import BacktestResult, run_backtest
from stk.backtest.setup import build_engine_config, make_rates_fn
from stk.backtest.view import MarketData
from stk.backtest.walkforward import WindowResult, run_walk_forward
from stk.config.backtest import BacktestConfig
from stk.domain.dsl.catalogue import CATALOGUE, FUNDAMENTAL_INDICATORS, Indicator
from stk.domain.dsl.evaluate import resolve_params
from stk.domain.dsl.model import Cond, Ind, StrategySpec
from stk.domain.dsl.validate import param_combinations
from stk.domain.walkforward import generate_windows
from stk.ingest.fundamentals_metrics import load_metric_frame
from stk.store import duck
from stk.strategies.dsl_strategy import DslStrategy, prepare_frame

#: Calendar days of history loaded before a run's start so 252-session indicators are warm.
WARMUP_DAYS = 400


def indicators_used(spec: StrategySpec) -> set[str]:
    """Catalogue indicator names referenced anywhere in a spec (entry + rank)."""
    names: set[str] = set()

    def operand(op: Any) -> None:
        if isinstance(op, Ind):
            names.add(op.ind)
        elif hasattr(op, "__dict__") and not isinstance(op, float | int):
            for v in op.__dict__.values():
                for child in (v if isinstance(v, tuple | list) else [v]):
                    operand(child)

    def node(n: Any) -> None:
        if isinstance(n, Cond):
            operand(n.left)
            for side in (n.right if isinstance(n.right, tuple) else (n.right,)):
                operand(side)
        else:
            for child in getattr(n, "all", None) or getattr(n, "any", None) or []:
                node(child)
            inner = getattr(n, "not_", None)
            if inner is not None:
                node(inner)

    node(spec.entry)
    if spec.rank:
        names.update(k.ind for k in spec.rank.by)
    return names


def benchmark_reason(benchmark: pd.DataFrame, index_code: str) -> str:
    """WHY a benchmark did not cover a run -- two very different problems, one fix each."""
    if benchmark.empty:
        return (f"no {index_code} index data has been ingested at all (run "
                "`stk ingest indices --date ...` for the span)")
    first = pd.Timestamp(benchmark["date"].min()).date()
    return f"the {index_code} index data ingested starts {first}; earlier windows have no benchmark"


def approx_reasons(
    spec: StrategySpec,
    start: date,
    *,
    benchmark_missing: bool,
    benchmark_note: str | None = None,
) -> list[str]:
    """Why a run's numbers should be read as approximate (empty = no known caveat)."""
    used = indicators_used(spec)
    reasons: list[str] = []
    for name in sorted(used):
        entry: Indicator = CATALOGUE[name]
        if entry.available_from and start < entry.available_from:
            reasons.append(f"{name} has no data before {entry.available_from} "
                           "(rules using it cannot fire earlier)")
    if used & FUNDAMENTAL_INDICATORS:
        reasons.append("fundamentals are point-in-time from XBRL broadcast dates, but the NSE "
                       "filings API history is shallow, so early windows have no fundamentals")
    if benchmark_missing:
        reasons.append("benchmark did not cover some windows: "
                       + (benchmark_note or "the benchmark series starts too late"))
    return reasons


@dataclass
class LakeSpan:
    first: date
    last: date


def lake_span(parquet_root: Path, exchange: str) -> LakeSpan | None:
    with duck.connect(parquet_root) as session:
        row = session.con.execute(
            "SELECT min(date), max(date) FROM bars_daily_adjusted WHERE exchange = ?", [exchange]
        ).fetchone()
    if not row or row[0] is None:
        return None
    return LakeSpan(row[0], row[1])


def _load_bars(
    parquet_root: Path, exchange: str, start: date, end: date, tradeable_series: list[str]
) -> pd.DataFrame:
    with duck.connect(parquet_root) as session:
        return session.sql(
            "backtest_panel", [tradeable_series, exchange, start.isoformat(), end.isoformat()]
        ).df()


def build_market_data(
    spec: StrategySpec,
    *,
    parquet_root: Path,
    conn: sqlite3.Connection,
    cfg: BacktestConfig,
    exchange: str,
    start: date,
    end: date,
) -> tuple[MarketData, pd.DataFrame]:
    """Feature-bearing market data for [start, end] plus the benchmark frame."""
    bars = _load_bars(parquet_root, exchange, start - timedelta(days=WARMUP_DAYS), end,
                      cfg.tradeable_series)
    if bars.empty:
        raise ValueError(
            f"no adjusted bars for {exchange} in [{start}, {end}] -- run `stk backfill prices` "
            "then `stk ingest adjustments`"
        )
    benchmark = load_benchmark(parquet_root, index_code=cfg.benchmark_index_code,
                               start=start - timedelta(days=WARMUP_DAYS), end=end)
    index_close = (benchmark.set_index("date")["close"] if not benchmark.empty else None)
    fundamentals = (
        load_metric_frame(conn, cfg.fundamentals_lag_days)
        if indicators_used(spec) & FUNDAMENTAL_INDICATORS else None
    )
    frame = prepare_frame(spec, bars, adv_lookback_days=cfg.adv_lookback_days,
                          index_close=index_close, fundamentals=fundamentals)
    return MarketData(frame), benchmark


def run_single(
    spec: StrategySpec,
    *,
    parquet_root: Path,
    conn: sqlite3.Connection,
    cfg: BacktestConfig,
    exchange: str,
    start: date,
    end: date,
    params: dict[str, float] | None = None,
) -> tuple[BacktestResult, list[str]]:
    data, benchmark = build_market_data(spec, parquet_root=parquet_root, conn=conn, cfg=cfg,
                                        exchange=exchange, start=start, end=end)
    result = run_backtest(
        data, DslStrategy(spec, params), start, end, build_engine_config(cfg, exchange),
        make_rates_fn(), benchmark=benchmark,
    )
    return result, approx_reasons(
        spec, start, benchmark_missing=result.benchmark_missing,
        benchmark_note=benchmark_reason(benchmark, cfg.benchmark_index_code))


def run_walk_forward_for(
    spec: StrategySpec,
    *,
    parquet_root: Path,
    conn: sqlite3.Connection,
    cfg: BacktestConfig,
    exchange: str,
    start: date,
    end: date,
) -> tuple[list[WindowResult], list[str]]:
    windows = generate_windows(
        start, end, train_months=cfg.walk_forward.train_months,
        test_months=cfg.walk_forward.test_months, step_months=cfg.walk_forward.step_months,
    )
    if not windows:
        raise ValueError(
            f"[{start}, {end}] is too short for {cfg.walk_forward.train_months}m train + "
            f"{cfg.walk_forward.test_months}m test windows"
        )
    data, benchmark = build_market_data(spec, parquet_root=parquet_root, conn=conn, cfg=cfg,
                                        exchange=exchange, start=start, end=end)
    grid = param_combinations(spec)
    results = run_walk_forward(
        data,
        lambda p: DslStrategy(spec, {**resolve_params(spec, None), **p}),
        windows,
        build_engine_config(cfg, exchange),
        make_rates_fn(),
        benchmark=benchmark,
        param_grid=grid if len(grid) > 1 else None,
    )
    missing = any(w.result.benchmark_missing for w in results)
    return results, approx_reasons(
        spec, windows[0].test_start, benchmark_missing=missing,
        benchmark_note=benchmark_reason(benchmark, cfg.benchmark_index_code))
