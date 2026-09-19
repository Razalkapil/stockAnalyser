"""Run a strategy through walk-forward and the promotion gate, then record the outcome.

    spec -> walk-forward (out-of-sample, after costs) -> stored run
         -> gate verdict -> status change (with an audit event)

Status outcomes:
  pass                    -> live for origins in ``auto_live_origins`` (seeds),
                             otherwise candidate awaiting explicit approval
  fail                    -> rejected
  insufficient_evidence   -> stays candidate, reason says why. NOT rejected:
                             "we could not tell" is not "no".
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from stk.backtest.runs import save_walk_forward_run
from stk.backtest.walkforward import WindowResult
from stk.config.backtest import BacktestConfig
from stk.config.promotion import PromotionConfig
from stk.domain.gate import GateReport, WindowSummary, evaluate_gate
from stk.strategies.repo import StrategyRow, get_strategy, load_spec, set_status
from stk.strategies.runner import run_walk_forward_for


def summarise(windows: list[WindowResult]) -> list[WindowSummary]:
    return [
        WindowSummary(w.window.label, w.outcome, w.result.metrics.max_drawdown,
                      w.result.metrics.trade_count)
        for w in windows
    ]


def status_for(report: GateReport, origin: str, auto_live: list[str]) -> tuple[str, str]:
    """(new status, reason) for a gate verdict."""
    failed = [c.name for c in report.checks if not c.passed]
    if report.verdict == "pass":
        if origin in auto_live:
            return "live", "passed the promotion gate"
        return "candidate", "passed the promotion gate; awaiting approval"
    if report.verdict == "insufficient_evidence":
        why = [c.detail for c in report.checks
               if c.name in ("scored_windows", "enough_trades") and not c.passed]
        return "candidate", "gate could not decide: " + "; ".join(why)
    return "rejected", "failed the promotion gate: " + ", ".join(failed)


def promote(
    conn: sqlite3.Connection,
    slug: str,
    *,
    parquet_root: Path,
    cfg: BacktestConfig,
    promo: PromotionConfig,
    exchange: str,
    start: date,
    end: date,
) -> tuple[StrategyRow, GateReport, int]:
    """Backtest, gate and (if warranted) change status. Returns (strategy, report, run_id)."""
    strategy = get_strategy(conn, slug)
    if strategy is None:
        raise KeyError(f"no strategy {slug!r}; run `stk strategies seed` first")
    spec = load_spec(conn, strategy.latest_version_id)

    windows, reasons = run_walk_forward_for(
        spec, parquet_root=parquet_root, conn=conn, cfg=cfg, exchange=exchange,
        start=start, end=end)
    report = evaluate_gate(summarise(windows), promo.thresholds_for(spec.horizon.value))

    run_id = save_walk_forward_run(
        conn, windows, strategy_ref=slug, exchange=exchange,
        benchmark_code=cfg.benchmark_index_code, params={}, config=cfg.model_dump(mode="json"),
        approx_reasons=reasons,
    )
    conn.execute(
        "UPDATE backtest_runs SET strategy_version_id=?, gate_verdict=?, gate_report_json=? "
        "WHERE run_id=?",
        (strategy.latest_version_id, report.verdict, json.dumps(report.to_dict()), run_id),
    )
    new_status, reason = status_for(report, strategy.origin, promo.auto_live_origins)
    set_status(conn, strategy.strategy_id, new_status, actor="gate", reason=reason,
               backtest_run_id=run_id)
    updated = get_strategy(conn, slug)
    assert updated is not None
    return updated, report, run_id
