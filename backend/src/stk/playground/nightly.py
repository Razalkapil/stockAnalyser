"""The end-of-day playground step: corporate actions, then EOD fills, then snapshots.

ORDER MATTERS. Corporate actions run FIRST: the ex-date's bar is already post-action, while
positions and resting orders are still in pre-action terms, so filling before adjusting would
trigger a stop on a split as if it were a crash.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from stk.ingest.jobs import job_run
from stk.playground.context import PlayCtx
from stk.playground.corpactions import CorpActionResult, apply_corporate_actions
from stk.playground.passes import PassResult, eod_pass
from stk.playground.performance import snapshot


@dataclass
class EodResult:
    corp: CorpActionResult
    fills: PassResult
    snapshots: int


def run_eod(conn: sqlite3.Connection, ctx: PlayCtx, day: date) -> EodResult:
    with job_run(conn, "playground_eod", business_date=day) as handle:
        corp = apply_corporate_actions(conn, day)
        fills = eod_pass(conn, ctx, day)
        pids = [r[0] for r in conn.execute(
            "SELECT portfolio_id FROM portfolios WHERE archived_at IS NULL")]
        for pid in pids:
            snapshot(conn, ctx, pid, day)
        handle.rows_written = fills.fills
        handle.metrics = {
            "splits_applied": corp.splits_applied, "orders_rescaled": corp.orders_rescaled,
            "dividends_credited": corp.dividends_credited, "eod_fills": fills.fills,
            "eod_rejected": fills.rejected, "snapshots": len(pids),
        }
    return EodResult(corp, fills, len(pids))
