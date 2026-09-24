"""The evening prompt must FIT the configured provider limit in its WORST case: nothing promoted,
so the brief is written from previews instead of picks.

Found live on the lab prompt: Groq's free tier refuses a request over 8,000 tokens/minute. The
evening prompt has the same exposure by a different route -- strategy_previews is cumulative and
every registered strategy can contribute to a day. The config caps decide the size; this makes an
over-budget cap a build failure rather than a recorded run failure.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from stk.ai.client import prompt_json
from stk.ai.inputs import build_input
from stk.ai.prompts import EVENING_SYSTEM
from stk.backtest.setup import make_rates_fn
from stk.config.ai import load_ai_config
from stk.config.backtest import load_backtest_config
from stk.domain.dsl.model import StrategySpec
from stk.playground.context import PlayCtx
from stk.store.db.engine import connect, migrate
from stk.strategies.repo import list_strategies, register_spec, set_status

SEEDS = sorted((Path(__file__).parents[2] / "config" / "strategies").glob("*.json"))
DAY = date(2026, 9, 23)
#: The longest preview `reason` measured on the live DB.
LONG_REASON = "x" * 148


@pytest.fixture
def env(tmp_path):
    migrate(tmp_path / "app.db")
    conn = connect(tmp_path / "app.db")
    for f in SEEDS:
        register_spec(conn, StrategySpec.model_validate(json.loads(f.read_text())), origin="seed")
    for row in list_strategies(conn):
        set_status(conn, row.strategy_id, "rejected", actor="gate",
                   reason="failed the promotion gate: beats_benchmark_after_costs, max_drawdown")
    ctx = PlayCtx(tmp_path / "parquet", load_backtest_config(), make_rates_fn())
    yield conn, ctx
    conn.close()


def seed_previews(conn, per_strategy: int) -> None:
    for row in list_strategies(conn):
        vid = conn.execute("SELECT max(version_id) FROM strategy_versions WHERE strategy_id=?",
                           (row.strategy_id,)).fetchone()[0]
        for i in range(per_strategy):
            conn.execute(
                "INSERT INTO strategy_previews (strategy_id, strategy_version_id, "
                "status_at_preview, exchange, symbol, horizon, signal_date, ref_price, "
                "stop_price, target_price, stop_pct, target_pct, hold_days, window_end, score, "
                "rank_in_strategy, reason, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row.strategy_id, vid, "rejected", "NSE", f"SYM{row.strategy_id}X{i}", "swing",
                 DAY.isoformat(), 1234.56, 1100.12, 1500.34, 0.05, 0.1, 25, "2026-10-29",
                 90.5 - i, i + 1, LONG_REASON, "2026-09-24T00:00:00+00:00"))
    conn.commit()


def size_of(conn, ctx) -> tuple[int, int]:
    cfg = load_ai_config()
    inp = build_input(conn, ctx, cfg, DAY)
    return len(EVENING_SYSTEM) + len(prompt_json(inp.payload)), inp.preview_count


def test_a_full_preview_day_fits_the_configured_budget_with_headroom(env):
    conn, ctx = env
    seed_previews(conn, per_strategy=10)  # the worst case: every strategy fills its day
    size, count = size_of(conn, ctx)
    cfg = load_ai_config()
    assert count == cfg.evening_review.max_previews_total
    assert cfg.max_input_chars is not None
    assert size < cfg.max_input_chars * 0.95, f"{size:,} chars vs limit {cfg.max_input_chars:,}"


def test_the_cap_not_the_table_bounds_the_prompt(env):
    """106 preview rows already exist live; ten times that must not change the prompt."""
    conn, ctx = env
    seed_previews(conn, per_strategy=3)
    small, _ = size_of(conn, ctx)
    seed_previews_more = 40
    for row in list_strategies(conn):
        vid = conn.execute("SELECT max(version_id) FROM strategy_versions WHERE strategy_id=?",
                           (row.strategy_id,)).fetchone()[0]
        for i in range(3, seed_previews_more):
            conn.execute(
                "INSERT INTO strategy_previews (strategy_id, strategy_version_id, "
                "status_at_preview, exchange, symbol, horizon, signal_date, ref_price, hold_days, "
                "window_end, score, rank_in_strategy, reason, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row.strategy_id, vid, "rejected", "NSE", f"SYM{row.strategy_id}X{i}", "swing",
                 DAY.isoformat(), 10.0, 25, "2026-10-29", 50.0, i + 1, LONG_REASON,
                 "2026-09-24T00:00:00+00:00"))
    conn.commit()
    big, count = size_of(conn, ctx)
    assert count <= load_ai_config().evening_review.max_previews_total
    assert big <= small * 1.25  # capped rows differ only in symbols/scores
