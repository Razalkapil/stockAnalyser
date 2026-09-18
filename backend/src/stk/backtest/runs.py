"""Persist and reload backtest runs.

Every run is stored whole -- strategy ref, params, config, windows,
metrics, equity curve, trade list -- so a result can be inspected or
compared later without re-running it. Money stays TEXT (Decimal-exact);
statistics are REAL.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from typing import Any

from stk.backtest.engine import BacktestResult
from stk.backtest.walkforward import WindowResult
from stk.core.version import code_version
from stk.domain.metrics import Metrics
from stk.store.db.engine import transaction

_METRIC_FIELDS = (
    "total_return", "cagr", "win_rate", "avg_win", "avg_loss", "profit_factor",
    "max_drawdown", "sharpe", "exposure", "trade_count", "benchmark_return", "alpha",
)


def _metric_rows(run_id: int, scope: str, m: Metrics) -> list[tuple[int, str, str, float | None]]:
    rows: list[tuple[int, str, str, float | None]] = []
    for name in _METRIC_FIELDS:
        value = getattr(m, name)
        # inf (profit factor with no losses) is not valid JSON/REAL-friendly: store NULL.
        unstorable = value is None or value == float("inf")
        rows.append((run_id, scope, name, None if unstorable else float(value)))
    return rows


def _insert_trades(
    conn: sqlite3.Connection, run_id: int, label: str | None, res: BacktestResult
) -> None:
    conn.executemany(
        """INSERT INTO backtest_trades (run_id, window_label, symbol, entry_date, entry_price,
               exit_date, exit_price, qty, entry_costs, exit_costs, gross_pnl, net_pnl,
               return_pct, exit_reason, holding_days, reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (run_id, label, t.symbol, t.entry_date.isoformat(), str(t.entry_price),
             t.exit_date.isoformat(), str(t.exit_price), t.qty, str(t.entry_costs),
             str(t.exit_costs), str(t.gross_pnl), str(t.net_pnl), t.return_pct,
             t.exit_reason, t.holding_days, t.reason)
            for t in res.trades
        ],
    )


def _begin(conn: sqlite3.Connection, *, ref: str, kind: str, exchange: str, start: date,
           end: date, benchmark_code: str | None, params: dict[str, Any],
           config: dict[str, Any], approx_reasons: list[str]) -> int:
    cur = conn.execute(
        """INSERT INTO backtest_runs (strategy_ref, kind, status, exchange, data_start, data_end,
               benchmark_code, params_json, config_json, code_version, is_approximate,
               approx_reasons_json, started_at)
           VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ref, kind, exchange, start.isoformat(), end.isoformat(), benchmark_code,
         json.dumps(params, default=str), json.dumps(config, default=str), code_version(),
         int(bool(approx_reasons)), json.dumps(approx_reasons),
         datetime.now(UTC).isoformat()),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


def _finish(conn: sqlite3.Connection, run_id: int, stats: dict[str, int], missing: bool) -> None:
    conn.execute(
        """UPDATE backtest_runs SET status='success', finished_at=?, stats_json=?,
               benchmark_missing=? WHERE run_id=?""",
        (datetime.now(UTC).isoformat(), json.dumps(stats), int(missing), run_id),
    )


def save_single_run(
    conn: sqlite3.Connection,
    result: BacktestResult,
    *,
    strategy_ref: str,
    exchange: str,
    benchmark_code: str | None,
    params: dict[str, Any],
    config: dict[str, Any],
    approx_reasons: list[str] | None = None,
) -> int:
    with transaction(conn):
        run_id = _begin(conn, ref=strategy_ref, kind="single", exchange=exchange,
                        start=result.dates[0], end=result.dates[-1],
                        benchmark_code=benchmark_code, params=params, config=config,
                        approx_reasons=approx_reasons or [])
        conn.executemany(
            "INSERT INTO backtest_metrics (run_id, scope, metric, value) VALUES (?,?,?,?)",
            _metric_rows(run_id, "overall", result.metrics),
        )
        conn.executemany(
            "INSERT INTO backtest_equity (run_id, date, equity, benchmark) VALUES (?,?,?,?)",
            [
                (run_id, d.isoformat(), e,
                 result.benchmark_close[i] if result.benchmark_close else None)
                for i, (d, e) in enumerate(zip(result.dates, result.equity, strict=True))
            ],
        )
        _insert_trades(conn, run_id, None, result)
        _finish(conn, run_id, result.stats, result.benchmark_missing)
    return run_id


def save_walk_forward_run(
    conn: sqlite3.Connection,
    windows: list[WindowResult],
    *,
    strategy_ref: str,
    exchange: str,
    benchmark_code: str | None,
    params: dict[str, Any],
    config: dict[str, Any],
    approx_reasons: list[str] | None = None,
) -> int:
    if not windows:
        raise ValueError("cannot store a walk-forward run with no windows")
    with transaction(conn):
        run_id = _begin(conn, ref=strategy_ref, kind="walk_forward", exchange=exchange,
                        start=windows[0].window.test_start, end=windows[-1].window.test_end,
                        benchmark_code=benchmark_code, params=params, config=config,
                        approx_reasons=approx_reasons or [])
        for wr in windows:
            m, w = wr.result.metrics, wr.window
            conn.execute(
                """INSERT INTO backtest_windows (run_id, label, train_start, train_end, test_start,
                       test_end, chosen_params_json, strat_return, bench_return, excess_return,
                       max_drawdown, trade_count, result)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, w.label, w.train_start.isoformat(), w.train_end.isoformat(),
                 w.test_start.isoformat(), w.test_end.isoformat(),
                 json.dumps(wr.chosen_params, default=str), m.total_return, m.benchmark_return,
                 m.alpha, m.max_drawdown, m.trade_count, wr.outcome),
            )
            conn.executemany(
                "INSERT INTO backtest_metrics (run_id, scope, metric, value) VALUES (?,?,?,?)",
                _metric_rows(run_id, f"window:{w.label}", m),
            )
            conn.executemany(
                "INSERT INTO backtest_equity (run_id, date, equity, benchmark) VALUES (?,?,?,?)",
                [
                    (run_id, d.isoformat(), e,
                     wr.result.benchmark_close[i] if wr.result.benchmark_close else None)
                    for i, (d, e) in enumerate(zip(wr.result.dates, wr.result.equity, strict=True))
                ],
            )
            _insert_trades(conn, run_id, w.label, wr.result)
        stats: dict[str, int] = {}
        for wr in windows:
            for k, v in wr.result.stats.items():
                stats[k] = stats.get(k, 0) + v
        _finish(conn, run_id, stats, all(wr.result.benchmark_missing for wr in windows))
    return run_id


def load_run_summary(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    run = conn.execute("SELECT * FROM backtest_runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None:
        raise KeyError(f"no backtest run {run_id}")
    metrics = {
        f"{r['scope']}/{r['metric']}": r["value"]
        for r in conn.execute("SELECT * FROM backtest_metrics WHERE run_id=?", (run_id,))
    }
    windows = [dict(r) for r in conn.execute(
        "SELECT * FROM backtest_windows WHERE run_id=? ORDER BY window_id", (run_id,))]
    n_trades = conn.execute(
        "SELECT COUNT(*) AS n FROM backtest_trades WHERE run_id=?", (run_id,)
    ).fetchone()["n"]
    return {"run": dict(run), "metrics": metrics, "windows": windows, "trade_count": n_trades}
