"""Assemble the evening review's input from what the pipeline already stored.

Reads only: the picks (or, when nothing is promoted, the previews), the strategy statistics,
the paper positions and the index closes.
Nothing here calls a network or an LLM. The result is a plain dict that becomes the JSON the model
is shown, and its `pick_ids` / `symbols` are what the reply is validated against.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from stk.backtest.data import load_benchmark
from stk.config.ai import AiConfig
from stk.config.backtest import BacktestConfig
from stk.playground.context import PlayCtx
from stk.playground.performance import summarise
from stk.strategies.stats import backtest_stats, live_stats

INDICES = ("NIFTY_50", "NIFTY_500")


@dataclass
class ReviewInput:
    day: date
    payload: dict[str, Any]
    pick_ids: dict[int, str] = field(default_factory=dict)  # pick_id -> horizon
    symbols: set[str] = field(default_factory=set)
    #: How many would-be picks travelled as read-only context. They carry NO ids and cannot be
    #: ranked; the counts let the caller tell "nothing to say" from "no picks, but plenty".
    preview_count: int = 0
    position_count: int = 0
    index_count: int = 0

    @property
    def is_preview(self) -> bool:
        """No picks to rank: the brief is a market note, not a recommendation list."""
        return not self.pick_ids

    @property
    def has_content(self) -> bool:
        """Is there anything at all to write about? The ONLY reason to skip the call."""
        return bool(self.pick_ids or self.preview_count or self.position_count
                    or self.index_count)


def _round(v: float | None, n: int = 4) -> float | None:
    return None if v is None else round(float(v), n)


def _index_moves(parquet_root: Path, cfg: BacktestConfig, day: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for code in INDICES:
        df = load_benchmark(parquet_root, index_code=code,
                            start=date.fromordinal(day.toordinal() - 10), end=day)
        if len(df) >= 2:
            last, prev = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
            out.append({"index": code, "close": round(last, 2),
                        "change_pct": round((last / prev - 1) * 100, 2),
                        "as_of": str(df["date"].iloc[-1])[:10]})
    return out


def _previews(conn: sqlite3.Connection, ai: AiConfig, day: date
              ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """What the NOT-promoted rules would have picked today, as read-only context.

    Two things make this safe to show a model whose reply is written back onto `picks`:

      * NO IDENTIFIERS. A preview carries no preview_id and no pick_id, so there is nothing for
        the model to rank and nothing `_store` could write an AI reason onto. The two id
        sequences are unrelated, so an id shown here could later name a real, different pick.
      * BOUNDED. strategy_previews is cumulative, so this filters on signal_date and caps per
        strategy and in total: the prompt budget, not the table, is the binding constraint.

    Ordered rank-first: scores are normalised 0-100 WITHIN a strategy and are not comparable
    across them, so a global score sort would just favour the most generous strategy. Rank-major
    is a round-robin -- every strategy's best name, then its second -- so truncating at the total
    keeps breadth.
    """
    rows = conn.execute(
        """SELECT v.symbol, v.horizon, v.score, v.reason, v.ref_price, v.stop_price,
                  v.target_price, v.hold_days, v.status_at_preview,
                  st.slug, st.name AS strategy_name, st.status_reason, sec.company_name
           FROM strategy_previews v
           JOIN strategies st ON st.strategy_id = v.strategy_id
           LEFT JOIN listings l ON l.exchange = v.exchange AND l.symbol = v.symbol
           LEFT JOIN securities sec ON sec.security_id = l.security_id
           WHERE v.signal_date = ?
           ORDER BY v.rank_in_strategy, v.score DESC, v.symbol""",
        (day.isoformat(),)).fetchall()

    per_strategy: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    strategies: dict[str, dict[str, Any]] = {}
    for r in rows:
        if len(items) >= ai.evening_review.max_previews_total:
            break
        per_strategy[r["slug"]] = per_strategy.get(r["slug"], 0) + 1
        if per_strategy[r["slug"]] > ai.evening_review.max_previews_per_strategy:
            continue
        items.append({
            "symbol": r["symbol"], "company": r["company_name"], "strategy": r["slug"],
            "horizon": r["horizon"], "score_0_100": _round(r["score"], 2),
            "ref_price": _round(r["ref_price"], 2), "stop": _round(r["stop_price"], 2),
            "target": _round(r["target_price"], 2), "hold_days": r["hold_days"],
            "why_flagged": r["reason"],
        })
        if r["slug"] not in strategies:
            bt = backtest_stats(conn, r["slug"])
            # No `live` block: a never-promoted strategy has zero closed picks by construction,
            # and sending "0 closed" invites the model to read it as a bad live record.
            strategies[r["slug"]] = {
                "name": r["strategy_name"], "horizon": r["horizon"],
                "status": r["status_at_preview"], "not_promoted_because": r["status_reason"],
                "backtest_out_of_sample": {
                    "cagr": _round(bt.cagr), "win_rate": _round(bt.win_rate),
                    "max_drawdown": _round(bt.max_drawdown), "trades": bt.trades,
                    "approximate": bt.is_approximate or bt.run_id is None},
            }
    return items, strategies


def build_input(conn: sqlite3.Connection, ctx: PlayCtx, ai: AiConfig, day: date) -> ReviewInput:
    cap = ai.evening_review.max_picks_per_horizon
    rows = conn.execute(
        """SELECT p.pick_id, p.symbol, p.horizon, p.ref_price, p.stop_price, p.target_price,
                  p.hold_days, p.score, p.reason, st.slug, st.name AS strategy_name,
                  st.strategy_id, sec.company_name
           FROM picks p JOIN strategies st ON st.strategy_id = p.strategy_id
           LEFT JOIN listings l ON l.exchange = p.exchange AND l.symbol = p.symbol
           LEFT JOIN securities sec ON sec.security_id = l.security_id
           WHERE p.signal_date = ? ORDER BY p.horizon, p.score DESC""",
        (day.isoformat(),)).fetchall()

    per_horizon: dict[str, int] = {}
    picks: list[dict[str, Any]] = []
    strategies: dict[str, dict[str, Any]] = {}
    inp = ReviewInput(day=day, payload={})
    for r in rows:
        per_horizon[r["horizon"]] = per_horizon.get(r["horizon"], 0) + 1
        if per_horizon[r["horizon"]] > cap:
            continue
        inp.pick_ids[r["pick_id"]] = r["horizon"]
        inp.symbols.add(r["symbol"])
        picks.append({
            "pick_id": r["pick_id"], "symbol": r["symbol"], "company": r["company_name"],
            "horizon": r["horizon"], "strategy": r["strategy_name"],
            "score_0_100": r["score"], "ref_price": _round(r["ref_price"], 2),
            "stop": _round(r["stop_price"], 2), "target": _round(r["target_price"], 2),
            "hold_days": r["hold_days"], "why_flagged": r["reason"],
        })
        if r["slug"] not in strategies:
            bt, live = backtest_stats(conn, r["slug"]), live_stats(conn, r["strategy_id"])
            strategies[r["slug"]] = {
                "name": r["strategy_name"], "horizon": r["horizon"],
                "backtest_out_of_sample": {
                    "cagr": _round(bt.cagr), "win_rate": _round(bt.win_rate),
                    "max_drawdown": _round(bt.max_drawdown), "sharpe": _round(bt.sharpe, 2),
                    "trades": bt.trades, "approximate": bt.is_approximate or bt.run_id is None,
                    "caveats": bt.approx_reasons[:3]},
                "live": {"closed_picks": live.closed, "hit_rate": _round(live.hit_rate),
                         "mean_net_return": _round(live.live_return)},
            }

    positions: list[dict[str, Any]] = []
    for (pid,) in conn.execute("SELECT portfolio_id FROM portfolios WHERE archived_at IS NULL"):
        s = summarise(conn, ctx, pid)
        for p in s.positions[: ai.evening_review.max_positions]:
            inp.symbols.add(p.symbol)
            positions.append({
                "portfolio": s.name, "symbol": p.symbol, "qty": p.qty,
                "avg_cost": float(p.avg_cost), "last_price": _round(float(p.ltp), 2) if p.ltp
                else None, "return": _round(p.unrealised_pct), "days_held": p.days_held})

    inp.position_count = len(positions)
    index_moves = _index_moves(ctx.parquet_root, ctx.cfg, day)
    inp.index_count = len(index_moves)
    payload: dict[str, Any] = {
        "date": day.isoformat(),
        "index_moves": index_moves,
        "picks": picks, "strategies": strategies, "open_positions": positions,
    }
    # Only when there is nothing to rank: beside real picks, previews would be noise competing
    # with the recommendations for the model's attention and the prompt budget.
    if not inp.pick_ids:
        previews, preview_strategies = _previews(conn, ai, day)
        if previews:
            inp.preview_count = len(previews)
            inp.symbols.update(p["symbol"] for p in previews)
            payload["strategy_previews"] = {
                "strategies": preview_strategies, "would_be_picks": previews}
    inp.payload = payload
    return inp
