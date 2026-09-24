"""Backtest-vs-live statistics for a strategy, and the decay rule.

BACKTEST numbers come from the strategy's latest walk-forward run and are
OUT-OF-SAMPLE only: the stitched test windows, each on fresh capital, chained. Never
in-sample -- an in-sample CAGR next to a live hit rate would be a comparison designed to
flatter the backtest.

LIVE numbers come from closed picks, net of costs. ``live_return`` is the mean net
return per closed pick and ``hit_rate`` the share that closed positive.

DECAY. A live strategy whose live hit rate has fallen at least
``decay.hit_rate_drop_pts`` points below its backtest win rate, over at least
``decay.min_closed_picks`` closed picks, is flagged ``decaying`` by the system. The
system may DEMOTE live -> decaying on its own; only a person retires a strategy.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from stk.config.promotion import PromotionConfig
from stk.strategies.repo import get_strategy, list_strategies, set_status


@dataclass
class LiveStats:
    closed: int = 0
    open: int = 0
    hit_rate: float | None = None
    live_return: float | None = None  # mean net return per closed pick, a fraction
    avg_hold_days: float | None = None


@dataclass
class BacktestStats:
    run_id: int | None = None
    kind: str | None = None
    cagr: float | None = None
    win_rate: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    trades: int = 0
    avg_hold_days: float | None = None
    is_approximate: bool = False
    approx_reasons: list[str] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)  # rebased to 100
    benchmark_curve: list[float] = field(default_factory=list)
    curve_dates: list[str] = field(default_factory=list)
    windows: list[dict[str, Any]] = field(default_factory=list)
    gate_verdict: str | None = None
    gate_checks: list[dict[str, Any]] = field(default_factory=list)


def live_stats(conn: sqlite3.Connection, strategy_id: int) -> LiveStats:
    row = conn.execute(
        """SELECT COUNT(*) AS n, AVG(net_return) AS avg_ret, AVG(holding_days) AS avg_hold,
                  AVG(CASE WHEN net_return > 0 THEN 1.0 ELSE 0.0 END) AS hit
           FROM pick_outcomes o JOIN picks p ON p.pick_id = o.pick_id
           WHERE p.strategy_id=? AND o.exit_reason != 'void'""",
        (strategy_id,),
    ).fetchone()
    open_n = conn.execute(
        "SELECT COUNT(*) AS n FROM picks WHERE strategy_id=? AND status IN "
        "('pending_entry','open')", (strategy_id,)).fetchone()["n"]
    if not row["n"]:
        return LiveStats(closed=0, open=open_n)
    return LiveStats(closed=row["n"], open=open_n, hit_rate=row["hit"],
                     live_return=row["avg_ret"], avg_hold_days=row["avg_hold"])


def _stitch(rows: list[sqlite3.Row], column: str) -> tuple[list[str], list[float]]:
    """Chain per-window equity curves (each rebased to its own start) into one, from 100."""
    dates: list[str] = []
    values: list[float] = []
    level = 100.0
    window: list[tuple[str, float]] = []

    def flush() -> None:
        nonlocal level
        if not window:
            return
        base = window[0][1]
        for d, v in window:
            dates.append(d)
            values.append(level * v / base)
        level = values[-1]
        window.clear()

    current = None
    for r in rows:
        if r[column] is None:
            continue
        if current is not None and r["window"] != current:
            flush()
        current = r["window"]
        window.append((r["date"], float(r[column])))
    flush()
    return dates, values


def backtest_stats(conn: sqlite3.Connection, slug: str) -> BacktestStats:
    strategy = get_strategy(conn, slug)
    if strategy is None:
        raise KeyError(slug)
    run = conn.execute(
        """SELECT * FROM backtest_runs WHERE strategy_ref=? AND status='success'
           ORDER BY (kind='walk_forward') DESC, run_id DESC LIMIT 1""",
        (slug,),
    ).fetchone()
    if run is None:
        return BacktestStats()
    stats = BacktestStats(run_id=run["run_id"], kind=run["kind"],
                          gate_verdict=run["gate_verdict"],
                          is_approximate=bool(run["is_approximate"]))
    stats.approx_reasons = json.loads(run["approx_reasons_json"] or "[]")
    stats.gate_checks = json.loads(run["gate_report_json"] or "{}").get("checks", [])

    trades = conn.execute(
        """SELECT COUNT(*) AS n, AVG(holding_days) AS hold,
                  AVG(CASE WHEN CAST(net_pnl AS REAL) > 0 THEN 1.0 ELSE 0.0 END) AS win
           FROM backtest_trades WHERE run_id=?""", (run["run_id"],)).fetchone()
    stats.trades = trades["n"]
    stats.win_rate = trades["win"]
    stats.avg_hold_days = trades["hold"]

    windows = conn.execute(
        "SELECT * FROM backtest_windows WHERE run_id=? ORDER BY window_id", (run["run_id"],)
    ).fetchall()
    stats.windows = [dict(w) for w in windows]
    if windows:
        dds = [w["max_drawdown"] for w in windows if w["max_drawdown"] is not None]
        stats.max_drawdown = min(dds) if dds else None
        growth = 1.0
        for w in windows:
            growth *= 1.0 + (w["strat_return"] or 0.0)
        days = (date.fromisoformat(windows[-1]["test_end"])
                - date.fromisoformat(windows[0]["test_start"])).days
        stats.cagr = growth ** (365.25 / days) - 1.0 if days > 0 and growth > 0 else None
        sharpes = conn.execute(
            "SELECT AVG(value) AS s FROM backtest_metrics WHERE run_id=? AND metric='sharpe' "
            "AND scope LIKE 'window:%'", (run["run_id"],)).fetchone()["s"]
        stats.sharpe = sharpes
    else:
        m = {r["metric"]: r["value"] for r in conn.execute(
            "SELECT metric, value FROM backtest_metrics WHERE run_id=? AND scope='overall'",
            (run["run_id"],))}
        stats.cagr, stats.max_drawdown, stats.sharpe = m.get("cagr"), m.get("max_drawdown"), \
            m.get("sharpe")

    eq = conn.execute(
        """SELECT e.date, e.equity, e.benchmark,
                  (SELECT w.label FROM backtest_windows w
                   WHERE w.run_id=e.run_id AND e.date BETWEEN w.test_start AND w.test_end) AS window
           FROM backtest_equity e WHERE e.run_id=? ORDER BY e.date""", (run["run_id"],)
    ).fetchall()
    stats.curve_dates, stats.equity_curve = _stitch(eq, "equity")
    _, stats.benchmark_curve = _stitch(eq, "benchmark")
    if len(stats.benchmark_curve) != len(stats.equity_curve):
        stats.benchmark_curve = []  # a benchmark that doesn't cover the run is omitted, not padded
    return stats


def flag_decay(conn: sqlite3.Connection, promo: PromotionConfig) -> list[str]:
    """Move live strategies whose live hit rate has slumped to ``decaying``. Returns slugs."""
    flagged: list[str] = []
    for s in list_strategies(conn):
        if s.status != "live":
            continue
        live = live_stats(conn, s.strategy_id)
        bt = backtest_stats(conn, s.slug)
        if (live.closed < promo.decay.min_closed_picks or live.hit_rate is None
                or bt.win_rate is None):
            continue
        drop_pts = (bt.win_rate - live.hit_rate) * 100.0
        if drop_pts >= promo.decay.hit_rate_drop_pts:
            set_status(conn, s.strategy_id, "decaying", actor="system",
                       reason=f"live hit rate {live.hit_rate:.0%} over {live.closed} picks vs "
                              f"backtest win rate {bt.win_rate:.0%} ({drop_pts:.0f} pts below)")
            flagged.append(s.slug)
    return flagged
