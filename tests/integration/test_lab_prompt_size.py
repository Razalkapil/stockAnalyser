"""The lab prompt must FIT the configured provider limit with all ten seed strategies registered.

Found live: the first version was 40k characters, which a free Groq tier (8,000 tokens/minute)
refuses outright. The guard turns that into a recorded failure; this test makes it a build failure
instead, so the prompt cannot grow past the budget unnoticed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stk.ai.client import prompt_json
from stk.ai.lab_inputs import DEAD_STATUSES, _strip_titles, build_lab_input
from stk.ai.prompts import LAB_SYSTEM
from stk.config.ai import load_ai_config
from stk.domain.dsl.model import StrategySpec
from stk.store.db.engine import connect, migrate
from stk.strategies.repo import list_strategies, register_spec, set_status

SEEDS = sorted((Path(__file__).parents[2] / "config" / "strategies").glob("*.json"))


@pytest.fixture
def conn(tmp_path):
    migrate(tmp_path / "app.db")
    c = connect(tmp_path / "app.db")
    for f in SEEDS:
        register_spec(c, StrategySpec.model_validate(json.loads(f.read_text())), origin="seed")
    yield c
    c.close()


def test_all_seeds_fit_the_configured_budget_with_headroom(conn):
    for row in list_strategies(conn):  # the realistic worst case: most seeds end up rejected
        set_status(conn, row.strategy_id, "rejected", actor="system", reason="test")
    cfg = load_ai_config()
    size = len(LAB_SYSTEM) + len(prompt_json(build_lab_input(conn)))
    assert cfg.max_input_chars is not None
    assert size < cfg.max_input_chars * 0.95, f"{size:,} chars vs limit {cfg.max_input_chars:,}"


def test_live_strategies_keep_their_full_rules_and_dead_ones_only_their_entry(conn):
    rows = list_strategies(conn)
    set_status(conn, rows[0].strategy_id, "live", actor="user", reason="t")
    set_status(conn, rows[1].strategy_id, "rejected", actor="system", reason="t")
    by = {s["slug"]: s for s in build_lab_input(conn)["strategies"]}
    live, dead = by[rows[0].slug], by[rows[1].slug]
    assert {"entry", "exit"} <= set(live["spec"])
    assert dead["status"] in DEAD_STATUSES and set(dead["spec"]) <= {"horizon", "entry"}
    assert "status_reason" in live and "status_reason" not in dead


def test_the_shared_universe_is_stated_once_not_per_strategy(conn):
    payload = build_lab_input(conn)
    assert payload["standard_universe"] is not None
    assert not any("universe" in s["spec"] for s in payload["strategies"])


def test_a_different_universe_is_still_shown(conn):
    other = StrategySpec.model_validate({
        "slug": "odd_universe", "name": "Odd", "horizon": "swing",
        "universe": {"min_price_raw": 999.0},
        "entry": {"left": {"ind": "rsi", "period": 14}, "op": "<", "right": 30},
        "exit": {"stop": {"type": "pct", "value": 0.1}, "max_hold_days": 20}})
    register_spec(conn, other, origin="seed")
    by = {s["slug"]: s for s in build_lab_input(conn)["strategies"]}
    assert by["odd_universe"]["spec"]["universe"]["min_price_raw"] == 999.0


def test_the_strategy_summary_never_repeats_the_slug_or_notes_inside_the_spec(conn):
    for s in build_lab_input(conn)["strategies"]:
        assert not {"slug", "name", "notes"} & set(s["spec"])


def test_schema_stripping_removes_noise_but_keeps_real_properties():
    schema = {"title": "X", "type": "object", "additionalProperties": False, "default": 1,
              "properties": {"title": {"type": "string", "title": "Title"},
                             "default": {"type": "integer", "default": 5}},
              "required": ["title"]}
    out = _strip_titles(schema)
    assert out == {"type": "object",
                   "properties": {"title": {"type": "string"}, "default": {"type": "integer"}},
                   "required": ["title"]}
