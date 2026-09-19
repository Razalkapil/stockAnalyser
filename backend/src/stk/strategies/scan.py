"""The nightly scan: run every live strategy on a date and record its picks.

For each strategy in status ``live`` or ``decaying`` the latest spec version is
evaluated on the scan date's close through a ``PointInTimeView`` -- exactly as the
backtest engine would on that decision day -- and each signal becomes a ``picks``
row. Re-running for the same date is safe: a pick is unique on
(strategy version, exchange, symbol, signal date) and duplicates are ignored, so a
re-scan never double-counts a name.

A ``candidate`` strategy (not yet through the gate, or awaiting approval) is NEVER
scanned: only strategies that have earned it produce picks.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from stk.backtest.view import PointInTimeView
from stk.config.backtest import BacktestConfig
from stk.domain.dsl.evaluate import explain
from stk.domain.dsl.model import StrategySpec
from stk.store.db.engine import transaction
from stk.strategies.dsl_strategy import DslStrategy
from stk.strategies.repo import list_strategies, load_spec
from stk.strategies.runner import build_market_data, lake_span

SCANNED_STATUSES = ("live", "decaying")


@dataclass
class ScanResult:
    scan_date: date
    strategies: int = 0
    picks_created: int = 0
    picks_existing: int = 0


def _reason(spec: StrategySpec) -> str:
    rules = [ln.strip() for ln in explain(spec) if not ln.startswith(("Stop", "Target", "Time"))]
    text = f"{spec.name}: " + "; ".join(r for r in rules if not r.endswith(":"))
    return text if len(text) <= 240 else text[:237] + "..."


def _window_end(signal: date, hold_days: int) -> date:
    return pd.bdate_range(signal, periods=hold_days + 2)[-1].date()


def scan(
    conn: sqlite3.Connection,
    *,
    parquet_root: Path,
    cfg: BacktestConfig,
    exchange: str = "NSE",
    scan_date: date | None = None,
) -> ScanResult:
    span = lake_span(parquet_root, exchange)
    if span is None:
        raise ValueError("the price lake is empty -- run `stk backfill prices` first")
    day = scan_date or span.last
    if not span.first <= day <= span.last:
        raise ValueError(f"{day} is outside the lake's range {span.first}..{span.last}")

    result = ScanResult(scan_date=day)
    for strategy in list_strategies(conn):
        if strategy.status not in SCANNED_STATUSES:
            continue
        spec = load_spec(conn, strategy.latest_version_id)
        data, _bench = build_market_data(spec, parquet_root=parquet_root, conn=conn, cfg=cfg,
                                         exchange=exchange, start=day, end=day)
        if day not in data.trading_dates(day, day):
            # No bar for the strategy's universe on this date (holiday / not ingested yet):
            # say so rather than emitting picks off stale data.
            raise ValueError(f"no bars for {exchange} on {day}; ingest that date first")
        signals = DslStrategy(spec).signals(PointInTimeView(data, day), frozenset())
        result.strategies += 1
        today = data.bars[data.bars["date"] == pd.Timestamp(day)].set_index("symbol")

        with transaction(conn):
            for rank, sig in enumerate(signals, start=1):
                row = today.loc[sig.symbol]
                ref = float(row["close_raw"]) if "close_raw" in row else float(row["close"])
                stop_pct = float(sig.stop_pct) if sig.stop_pct is not None else None
                target_pct = float(sig.target_pct) if sig.target_pct is not None else None
                cur = conn.execute(
                    """INSERT INTO picks (strategy_id, strategy_version_id, exchange, symbol,
                           horizon, signal_date, ref_price, stop_price, target_price, stop_pct,
                           target_pct, hold_days, window_end, score, rank_in_strategy, reason,
                           status, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'pending_entry', ?)
                       ON CONFLICT (strategy_version_id, exchange, symbol, signal_date)
                       DO NOTHING""",
                    (
                        strategy.strategy_id, strategy.latest_version_id, exchange, sig.symbol,
                        spec.horizon.value, day.isoformat(), ref,
                        ref * (1 - stop_pct) if stop_pct is not None else None,
                        ref * (1 + target_pct) if target_pct is not None else None,
                        stop_pct, target_pct, sig.max_hold_days,
                        _window_end(day, sig.max_hold_days).isoformat(), sig.score, rank,
                        _reason(spec), datetime.now(UTC).isoformat(),
                    ),
                )
                if cur.rowcount:
                    result.picks_created += 1
                else:
                    result.picks_existing += 1
    return result
