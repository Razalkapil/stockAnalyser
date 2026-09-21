"""The nightly scan: run every live strategy on a date and record its picks.

For each strategy in status ``live`` or ``decaying`` the latest spec version is
evaluated on the scan date's close through a ``PointInTimeView`` -- exactly as the
backtest engine would on that decision day -- and each signal becomes a ``picks``
row. Re-running for the same date is safe: a pick is unique on
(strategy version, exchange, symbol, signal date) and duplicates are ignored, so a
re-scan never double-counts a name.

A ``candidate`` strategy (not yet through the gate, or awaiting approval) is NEVER
scanned: only strategies that have earned it produce picks.

The evaluation half -- resolving the date, building the panel, turning signals into
priced rows -- lives here as ``evaluate_strategies``/``candidates_for`` and is shared
with ``strategies.preview``, which runs the SAME code over the strategies this module
refuses. Sharing it is the point: a preview that drifted from the scan would be
telling you about a strategy you do not have.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
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
from stk.strategies.repo import StrategyRow, list_strategies, load_spec
from stk.strategies.runner import build_market_data, lake_span

SCANNED_STATUSES = ("live", "decaying")


@dataclass
class ScanResult:
    scan_date: date
    strategies: int = 0
    picks_created: int = 0
    picks_existing: int = 0


@dataclass(frozen=True)
class Candidate:
    """One signal, priced and ranked -- everything a picks/preview row needs."""

    symbol: str
    rank: int
    score: float          # 0-100
    ref_price: float      # unadjusted close on the signal date, what a person would pay
    stop_price: float | None
    target_price: float | None
    stop_pct: float | None
    target_pct: float | None
    hold_days: int
    window_end: date
    reason: str


def _reason(spec: StrategySpec) -> str:
    rules = [ln.strip() for ln in explain(spec) if not ln.startswith(("Stop", "Target", "Time"))]
    text = f"{spec.name}: " + "; ".join(r for r in rules if not r.endswith(":"))
    return text if len(text) <= 240 else text[:237] + "..."


def _window_end(signal: date, hold_days: int) -> date:
    return pd.bdate_range(signal, periods=hold_days + 2)[-1].date()


def resolve_day(parquet_root: Path, exchange: str, scan_date: date | None) -> date:
    """The date to evaluate on, checked against what the lake actually holds."""
    span = lake_span(parquet_root, exchange)
    if span is None:
        raise ValueError("the price lake is empty -- run `stk backfill prices` first")
    day = scan_date or span.last
    if not span.first <= day <= span.last:
        raise ValueError(f"{day} is outside the lake's range {span.first}..{span.last}")
    return day


def candidates_for(
    conn: sqlite3.Connection,
    spec: StrategySpec,
    *,
    parquet_root: Path,
    cfg: BacktestConfig,
    exchange: str,
    day: date,
) -> list[Candidate]:
    """Evaluate one spec on ``day`` exactly as the engine would on that decision day."""
    data, _bench = build_market_data(spec, parquet_root=parquet_root, conn=conn, cfg=cfg,
                                     exchange=exchange, start=day, end=day)
    if day not in data.trading_dates(day, day):
        # No bar for the strategy's universe on this date (holiday / not ingested yet):
        # say so rather than emitting picks off stale data.
        raise ValueError(f"no bars for {exchange} on {day}; ingest that date first")
    signals = DslStrategy(spec).signals(PointInTimeView(data, day), frozenset())
    # The raw score is a weighted sum of percentile ranks, so its ceiling is the sum of the
    # weights. Stored on a 0-100 scale so a score means the same thing across strategies.
    ceiling = sum(k.weight for k in spec.rank.by) if spec.rank else 0.0
    today = data.bars[data.bars["date"] == pd.Timestamp(day)].set_index("symbol")
    reason = _reason(spec)

    out: list[Candidate] = []
    for rank, sig in enumerate(signals, start=1):
        row = today.loc[sig.symbol]
        ref = float(row["close_raw"]) if "close_raw" in row else float(row["close"])
        stop_pct = float(sig.stop_pct) if sig.stop_pct is not None else None
        target_pct = float(sig.target_pct) if sig.target_pct is not None else None
        out.append(Candidate(
            symbol=sig.symbol,
            rank=rank,
            score=round(sig.score / ceiling * 100.0, 1) if ceiling else 0.0,
            ref_price=ref,
            stop_price=ref * (1 - stop_pct) if stop_pct is not None else None,
            target_price=ref * (1 + target_pct) if target_pct is not None else None,
            stop_pct=stop_pct,
            target_pct=target_pct,
            hold_days=sig.max_hold_days,
            window_end=_window_end(day, sig.max_hold_days),
            reason=reason,
        ))
    return out


def evaluate_strategies(
    conn: sqlite3.Connection,
    *,
    parquet_root: Path,
    cfg: BacktestConfig,
    exchange: str,
    day: date,
    include: Callable[[StrategyRow], bool],
) -> Iterator[tuple[StrategyRow, StrategySpec, list[Candidate]]]:
    """Every strategy ``include`` accepts, with its spec and its candidates for ``day``."""
    for strategy in list_strategies(conn):
        if not include(strategy):
            continue
        spec = load_spec(conn, strategy.latest_version_id)
        yield strategy, spec, candidates_for(
            conn, spec, parquet_root=parquet_root, cfg=cfg, exchange=exchange, day=day
        )


def scan(
    conn: sqlite3.Connection,
    *,
    parquet_root: Path,
    cfg: BacktestConfig,
    exchange: str = "NSE",
    scan_date: date | None = None,
) -> ScanResult:
    day = resolve_day(parquet_root, exchange, scan_date)
    result = ScanResult(scan_date=day)

    for strategy, spec, candidates in evaluate_strategies(
        conn, parquet_root=parquet_root, cfg=cfg, exchange=exchange, day=day,
        include=lambda s: s.status in SCANNED_STATUSES,
    ):
        result.strategies += 1
        now = datetime.now(UTC).isoformat()
        with transaction(conn):
            for c in candidates:
                cur = conn.execute(
                    """INSERT INTO picks (strategy_id, strategy_version_id, exchange, symbol,
                           horizon, signal_date, ref_price, stop_price, target_price, stop_pct,
                           target_pct, hold_days, window_end, score, rank_in_strategy, reason,
                           status, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'pending_entry', ?)
                       ON CONFLICT (strategy_version_id, exchange, symbol, signal_date)
                       DO NOTHING""",
                    (
                        strategy.strategy_id, strategy.latest_version_id, exchange, c.symbol,
                        spec.horizon.value, day.isoformat(), c.ref_price,
                        c.stop_price, c.target_price, c.stop_pct, c.target_pct, c.hold_days,
                        c.window_end.isoformat(), c.score, c.rank, c.reason, now,
                    ),
                )
                if cur.rowcount:
                    result.picks_created += 1
                else:
                    result.picks_existing += 1
    return result
