"""Nightly pick tracking: mark open picks to market and close them on stop / target / time.

Idempotent by construction. Every run recomputes each open pick's whole history from
the (back-adjusted) bars, then REPLACES its marks -- so a corporate action arriving
mid-hold, or a rebuilt adjustment factor, simply produces the corrected series next
run instead of leaving a stale mark behind.

COSTS. Live returns are reported NET, like the backtest's, by subtracting the
round-trip cost drag of a nominal Rs 1 lakh delivery position (buy leg + sell leg +
DP charge) at the rates in force on the tracking date. Nominal size because a pick
has no position size; the DP charge alone makes small positions cost proportionally
more, and 1 lakh is a stated, round, unsurprising choice.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from stk.backtest.setup import make_rates_fn
from stk.config.backtest import BacktestConfig
from stk.domain.costs import Product, Side, compute_costs, dp_charge
from stk.domain.tracking import Bar, TrackedPick, track_pick
from stk.store import duck
from stk.store.db.engine import transaction
from stk.strategies.runner import lake_span

NOMINAL_POSITION_INR = Decimal(100_000)
#: A pick that has produced no bar this many calendar days after its signal is void
#: (delisted, renamed, suspended): it must not sit "pending" forever.
VOID_AFTER_DAYS = 10


@dataclass
class TrackResult:
    tracked: int = 0
    entered: int = 0
    closed: int = 0
    voided: int = 0


def round_trip_cost_pct(exchange: str, on: date) -> float:
    rates = make_rates_fn()(exchange, on)
    buy = compute_costs(Side.BUY, Product.DELIVERY, NOMINAL_POSITION_INR, rates).total
    sell = compute_costs(Side.SELL, Product.DELIVERY, NOMINAL_POSITION_INR, rates).total
    return float((buy + sell + dp_charge(rates)) / NOMINAL_POSITION_INR)


def _bars_by_symbol(
    parquet_root: Path,
    exchange: str,
    symbols: list[str],
    *,
    start: date,
    end: date,
    tradeable_series: list[str],
) -> dict[str, list[Bar]]:
    with duck.connect(parquet_root) as session:
        frame = session.sql(
            "panel_for_symbols",
            [tradeable_series, symbols, exchange, start.isoformat(), end.isoformat()],
        ).df()
    out: dict[str, list[Bar]] = {}
    for sym, grp in frame.groupby("symbol", sort=False):
        out[str(sym)] = [
            Bar(pd.Timestamp(r.date).date(), float(r.open), float(r.high), float(r.low),
                float(r.close))
            for r in grp.sort_values("date").itertuples()
        ]
    return out


def _write(conn: sqlite3.Connection, pick_id: int, state: TrackedPick, status: str) -> None:
    conn.execute("UPDATE picks SET status=? WHERE pick_id=?", (status, pick_id))
    conn.execute("DELETE FROM pick_marks WHERE pick_id=?", (pick_id,))
    conn.executemany(
        "INSERT INTO pick_marks (pick_id, date, net_return) VALUES (?,?,?)",
        [(pick_id, d.isoformat(), r) for d, r in state.marks],
    )
    conn.execute("DELETE FROM pick_outcomes WHERE pick_id=?", (pick_id,))
    if status in ("closed", "void"):
        conn.execute(
            """INSERT INTO pick_outcomes (pick_id, entry_date, entry_price, exit_date,
                   exit_price, exit_reason, net_return, holding_days, mfe, mae, closed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pick_id,
                state.entry_date.isoformat() if state.entry_date else None,
                state.entry_price,
                state.exit_date.isoformat() if state.exit_date else None,
                state.exit_price,
                state.exit_reason or "void",
                state.net_return, state.holding_days, state.mfe, state.mae,
                datetime.now(UTC).isoformat(),
            ),
        )


def track_picks(
    conn: sqlite3.Connection, *, parquet_root: Path, cfg: BacktestConfig, exchange: str = "NSE"
) -> TrackResult:
    result = TrackResult()
    picks = conn.execute(
        "SELECT * FROM picks WHERE exchange=? AND status IN ('pending_entry','open')", (exchange,)
    ).fetchall()
    if not picks:
        return result
    span = lake_span(parquet_root, exchange)
    if span is None:
        raise ValueError("the price lake is empty -- run `stk backfill prices` first")

    first_signal = min(date.fromisoformat(p["signal_date"]) for p in picks)
    bars = _bars_by_symbol(parquet_root, exchange, sorted({p["symbol"] for p in picks}),
                           start=first_signal, end=span.last,
                           tradeable_series=cfg.tradeable_series)
    cost = round_trip_cost_pct(exchange, span.last)

    with transaction(conn):
        for p in picks:
            signal = date.fromisoformat(p["signal_date"])
            after = [b for b in bars.get(p["symbol"], []) if b.date > signal]
            state = track_pick(after, stop_pct=p["stop_pct"], target_pct=p["target_pct"],
                               hold_days=p["hold_days"], cost_pct=cost)
            result.tracked += 1
            if state.status == "pending_entry":
                if (span.last - signal) > timedelta(days=VOID_AFTER_DAYS):
                    _write(conn, p["pick_id"], state, "void")
                    result.voided += 1
                continue
            if p["status"] == "pending_entry":
                result.entered += 1
            if state.status == "closed":
                result.closed += 1
            _write(conn, p["pick_id"], state, state.status)
    return result
