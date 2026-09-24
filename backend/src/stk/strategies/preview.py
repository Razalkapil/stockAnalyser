"""Preview: what a strategy that is NOT promoted would have picked, had it been.

The gate rejects a strategy on its out-of-sample record, and `scan` then refuses to
run it -- correctly, because a pick is a recommendation. But "rejected" should not
also mean "invisible": you cannot judge a rule you cannot watch, and the reason a
strategy lost is often in the names it wants to buy today.

So this is the scan's read-only shadow. It shares `scan`'s evaluation verbatim
(`evaluate_strategies`) over the strategies `scan` skips, and writes to
`strategy_previews` -- a separate table, never `picks`. Nothing here promotes
anything, and a preview row carries the strategy's status at the time it was made so
it can never be read as something that earned its place.

WHAT MAY SEE A PREVIEW. Tracking and out-of-sample stats read `picks` only, so a
preview can never become a tracked position or flatter a backtest. The AI evening
review is the one deliberate exception: on a day with NO picks it is shown previews as
READ-ONLY CONTEXT, so the market brief is not permanently empty (the market overview
and open-position notes never needed picks -- docs/PROJECT_BRIEF.md section 9). Three
properties keep that safe, all in stk/ai/inputs.py::_previews:

  * previews travel with NO identifiers, so the model cannot rank one and
    ai/evening.py::_store -- which writes AI reasons by pick_id -- cannot reach one;
  * they are included only when `picks` is empty, so they never compete with a real
    recommendation;
  * the brief they produce is labelled coverage="preview" through to the screen.

Nothing writes back here, and nothing here is ever tracked.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from stk.config.backtest import BacktestConfig
from stk.store.db.engine import transaction
from stk.strategies.repo import StrategyRow
from stk.strategies.scan import SCANNED_STATUSES, evaluate_strategies, resolve_day


@dataclass
class PreviewResult:
    scan_date: date
    strategies: int = 0
    rows_created: int = 0
    rows_existing: int = 0


def preview(
    conn: sqlite3.Connection,
    *,
    parquet_root: Path,
    cfg: BacktestConfig,
    exchange: str = "NSE",
    scan_date: date | None = None,
    slug: str | None = None,
) -> PreviewResult:
    """Record what every non-promoted strategy (or just ``slug``) would pick on a date."""
    day = resolve_day(parquet_root, exchange, scan_date)
    result = PreviewResult(scan_date=day)

    def include(s: StrategyRow) -> bool:
        # The complement of the scan: anything it would already have produced real picks for
        # is excluded, so a strategy is never in both tables for the same day.
        if s.status in SCANNED_STATUSES:
            return False
        return slug is None or s.slug == slug

    for strategy, spec, candidates in evaluate_strategies(
        conn, parquet_root=parquet_root, cfg=cfg, exchange=exchange, day=day, include=include,
    ):
        result.strategies += 1
        now = datetime.now(UTC).isoformat()
        with transaction(conn):
            for c in candidates:
                cur = conn.execute(
                    """INSERT INTO strategy_previews (strategy_id, strategy_version_id,
                           status_at_preview, exchange, symbol, horizon, signal_date, ref_price,
                           stop_price, target_price, stop_pct, target_pct, hold_days, window_end,
                           score, rank_in_strategy, reason, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT (strategy_version_id, exchange, symbol, signal_date)
                       DO NOTHING""",
                    (
                        strategy.strategy_id, strategy.latest_version_id, strategy.status,
                        exchange, c.symbol, spec.horizon.value, day.isoformat(), c.ref_price,
                        c.stop_price, c.target_price, c.stop_pct, c.target_pct, c.hold_days,
                        c.window_end.isoformat(), c.score, c.rank, c.reason, now,
                    ),
                )
                if cur.rowcount:
                    result.rows_created += 1
                else:
                    result.rows_existing += 1
    return result
