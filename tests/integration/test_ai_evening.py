"""The evening review, end to end, against a fake model. No network; no spend."""

from __future__ import annotations

import json

import pytest

from integration.test_api import DAYS, world  # noqa: F401 (fixture)
from stk.ai.client import LlmError, LlmReply
from stk.ai.evening import run_evening_review, semantic_problems
from stk.ai.inputs import build_input
from stk.ai.schemas import EveningReview
from stk.backtest.setup import make_rates_fn
from stk.config.ai import AiConfig, Price, load_ai_config
from stk.playground.context import PlayCtx
from stk.store.db.engine import connect
from stk.strategies.preview import preview
from stk.strategies.repo import set_status

DAY = DAYS[60]


class Model:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0
        self.seen_user: str = ""

    def complete(self, *, system, messages, max_tokens):
        self.calls += 1
        self.seen_user = messages[0]["content"]
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def good_reply(inp) -> LlmReply:
    by_h: dict[str, list[int]] = {}
    for pid, h in inp.pick_ids.items():
        by_h.setdefault(h, []).append(pid)
    payload = {
        "overview": "Indices were flat.",
        "horizons": [{"horizon": h, "ranked": [
            {"pick_id": pid, "rank": i, "explanation": f"pick {pid} fired its rules",
             "conflict": "wide stop" if i == 1 else None} for i, pid in enumerate(pids, start=1)]}
            for h, pids in by_h.items()],
        "notable_picks": [{"symbol": sorted(inp.symbols)[0], "note": "top scorer"}],
        "conflicts": ["one wide stop"], "position_notes": []}
    return LlmReply(json.dumps(payload), "claude-sonnet-5", 1200, 300, "end_turn")


@pytest.fixture
def env(world):  # noqa: F811
    _client, db_path, _token, app = world
    conn = connect(db_path)
    ctx = PlayCtx(app.state.ctx.parquet_root, app.state.ctx.cfg, make_rates_fn())
    ai = AiConfig(model="claude-sonnet-5",
                  pricing_usd_per_mtok={"claude-sonnet-5": Price(input=2.0, output=10.0)})
    yield conn, ctx, ai, world
    conn.close()


@pytest.fixture
def preview_env(env):
    """The real situation: nothing is promoted, so there are no picks -- only previews."""
    conn, ctx, ai, world_ = env
    sid = conn.execute("SELECT strategy_id FROM strategies").fetchone()[0]
    conn.execute("DELETE FROM pick_marks")
    conn.execute("DELETE FROM pick_outcomes")
    conn.execute("DELETE FROM picks")
    conn.commit()
    set_status(conn, sid, "rejected", actor="gate",
               reason="failed the promotion gate: beats_benchmark_after_costs")
    preview(conn, parquet_root=ctx.parquet_root, cfg=ctx.cfg, scan_date=DAY)
    return conn, ctx, ai, world_


def pickless_reply(inp, *, horizons=None) -> LlmReply:
    payload = {
        "overview": "Indices were flat.", "horizons": horizons if horizons is not None else [],
        "notable_picks": [{"symbol": sorted(inp.symbols)[0], "note": "flagged, not promoted"}],
        "conflicts": [], "position_notes": []}
    return LlmReply(json.dumps(payload), "claude-sonnet-5", 900, 200, "end_turn")


def runs(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM ai_runs ORDER BY run_id")]


class TestInput:
    def test_contains_the_picks_strategies_and_ids_the_reply_is_checked_against(self, env):
        conn, ctx, ai, _ = env
        inp = build_input(conn, ctx, ai, DAY)
        assert len(inp.pick_ids) == 2 and inp.symbols <= {"AAA", "BBB", "CCC"}
        p = inp.payload["picks"][0]
        assert {"pick_id", "symbol", "company", "horizon", "strategy", "score_0_100",
                "why_flagged"} <= set(p)
        s = next(iter(inp.payload["strategies"].values()))
        assert s["backtest_out_of_sample"]["approximate"] is True  # never backtested: said so
        assert s["backtest_out_of_sample"]["cagr"] is None  # unknown, NOT zero

    def test_picks_are_capped_per_horizon(self, env):
        conn, ctx, ai, _ = env
        small = ai.model_copy(update={"evening_review": ai.evening_review.model_copy(
            update={"max_picks_per_horizon": 1})})
        assert len(build_input(conn, ctx, small, DAY).pick_ids) == 1

    def test_a_day_with_no_picks_and_no_previews_has_nothing_to_say(self, env):
        conn, ctx, ai, _ = env
        inp = build_input(conn, ctx, ai, DAYS[5])
        assert inp.pick_ids == {} and inp.preview_count == 0
        assert inp.has_content is False and "strategy_previews" not in inp.payload

    def test_previews_fill_in_for_picks_when_nothing_is_promoted(self, preview_env):
        conn, ctx, ai, _ = preview_env
        inp = build_input(conn, ctx, ai, DAY)
        assert inp.pick_ids == {} and inp.is_preview and inp.preview_count > 0
        assert inp.has_content and inp.payload["picks"] == []
        assert set(inp.payload["strategy_previews"]) == {"strategies", "would_be_picks"}

    def test_a_preview_carries_no_identifier_the_model_could_rank(self, preview_env):
        """Hazard 1: preview ids and pick ids are unrelated sequences, and `_store` writes an AI
        reason onto a pick BY id. Nothing a model could echo back may name a row."""
        conn, ctx, ai, _ = preview_env
        block = build_input(conn, ctx, ai, DAY).payload["strategy_previews"]
        for p in [*block["would_be_picks"], *block["strategies"].values()]:
            assert not any(k.endswith("_id") or k == "id" for k in p)

    def test_a_preview_strategy_says_why_it_is_not_promoted_and_shows_no_live_record(
            self, preview_env):
        conn, ctx, ai, _ = preview_env
        strategies = build_input(conn, ctx, ai, DAY).payload["strategy_previews"]["strategies"]
        assert strategies
        for st in strategies.values():
            assert st["not_promoted_because"] and "live" not in st

    def test_previews_are_not_shown_when_there_are_real_picks(self, env):
        conn, ctx, ai, _ = env
        assert "strategy_previews" not in build_input(conn, ctx, ai, DAY).payload

    def test_previews_are_capped_per_strategy_and_in_total(self, preview_env):
        conn, ctx, ai, _ = preview_env
        def cfg(**kw):
            return ai.model_copy(update={"evening_review": ai.evening_review.model_copy(update=kw)})
        one = build_input(conn, ctx, cfg(max_previews_per_strategy=1), DAY)
        rows = one.payload["strategy_previews"]["would_be_picks"]
        assert len(rows) == len({r["strategy"] for r in rows})
        assert build_input(conn, ctx, cfg(max_previews_total=1), DAY).preview_count == 1

    def test_only_this_days_previews_are_used(self, preview_env):
        """strategy_previews is cumulative: 106 rows live, 36 for one day."""
        conn, ctx, ai, _ = preview_env
        conn.execute("INSERT INTO strategy_previews (strategy_id, strategy_version_id, "
                     "status_at_preview, exchange, symbol, horizon, signal_date, ref_price, "
                     "hold_days, window_end, score, rank_in_strategy, reason, created_at) "
                     "SELECT strategy_id, strategy_version_id, status_at_preview, exchange, "
                     "'OLDDAY', horizon, '2000-01-03', ref_price, hold_days, window_end, score, "
                     "rank_in_strategy, reason, created_at FROM strategy_previews LIMIT 1")
        conn.commit()
        inp = build_input(conn, ctx, ai, DAY)
        assert "OLDDAY" not in inp.symbols


class TestSemanticChecks:
    def review(self, **over):
        base = {"overview": "o", "horizons": [], "notable_picks": [], "conflicts": [],
                "position_notes": []}
        base.update(over)
        return EveningReview.model_validate(base)

    def ranked(self, *pairs, horizon="swing"):
        return {"horizon": horizon, "ranked": [
            {"pick_id": p, "rank": r, "explanation": "x"} for p, r in pairs]}

    def inp(self, env):
        return build_input(env[0], env[1], env[2], DAY)

    def test_a_clean_review_has_no_problems(self, env):
        inp = self.inp(env)
        assert semantic_problems(EveningReview.model_validate_json(good_reply(inp).text),
                                 inp) == []

    def test_an_invented_pick_id_is_caught(self, env):
        inp = self.inp(env)
        ids = list(inp.pick_ids)
        r = self.review(horizons=[self.ranked((ids[0], 1), (ids[1], 2), (99999, 3))])
        assert any("99999 was not in the input" in p for p in semantic_problems(r, inp))

    def test_an_unranked_pick_is_caught(self, env):
        inp = self.inp(env)
        r = self.review(horizons=[self.ranked((next(iter(inp.pick_ids)), 1))])
        assert any("were not ranked" in p for p in semantic_problems(r, inp))

    def test_ranks_must_be_a_clean_sequence(self, env):
        inp = self.inp(env)
        ids = list(inp.pick_ids)
        r = self.review(horizons=[self.ranked((ids[0], 1), (ids[1], 3))])
        assert any("must be exactly 1..2" in p for p in semantic_problems(r, inp))

    def test_a_pick_under_the_wrong_horizon_is_caught(self, env):
        inp = self.inp(env)
        ids = list(inp.pick_ids)
        r = self.review(horizons=[self.ranked((ids[0], 1), (ids[1], 2), horizon="momentum")])
        assert any("belongs to" in p for p in semantic_problems(r, inp))

    def test_a_pick_ranked_twice_is_caught(self, env):
        inp = self.inp(env)
        pid = next(iter(inp.pick_ids))
        r = self.review(horizons=[self.ranked((pid, 1), (pid, 2))])
        assert any("ranked twice" in p for p in semantic_problems(r, inp))

    def test_a_ranked_pick_on_a_preview_day_is_rejected(self, preview_env):
        """The collision hazard as a test: a real preview_id offered as a pick_id."""
        conn, ctx, ai, _ = preview_env
        inp = build_input(conn, ctx, ai, DAY)
        preview_id = conn.execute("SELECT min(preview_id) FROM strategy_previews").fetchone()[0]
        r = self.review(horizons=[self.ranked((preview_id, 1))])
        assert any(f"pick_id {preview_id} was not in the input" in p
                   for p in semantic_problems(r, inp))

    def test_an_empty_horizon_list_is_clean_on_a_preview_day(self, preview_env):
        conn, ctx, ai, _ = preview_env
        inp = build_input(conn, ctx, ai, DAY)
        assert semantic_problems(self.review(horizons=[]), inp) == []

    def test_a_preview_symbol_may_be_named_in_a_note(self, preview_env):
        conn, ctx, ai, _ = preview_env
        inp = build_input(conn, ctx, ai, DAY)
        sym = inp.payload["strategy_previews"]["would_be_picks"][0]["symbol"]
        r = self.review(notable_picks=[{"symbol": sym, "note": "flagged"}])
        assert semantic_problems(r, inp) == []

    def test_an_invented_symbol_in_a_note_is_caught(self, env):
        inp = self.inp(env)
        r = EveningReview.model_validate_json(good_reply(inp).text)
        r.notable_picks[0].symbol = "TESLA"
        assert any("'TESLA' was not in the input" in p for p in semantic_problems(r, inp))


class TestRun:
    def test_success_stores_the_brief_the_reasons_and_the_cost(self, env):
        conn, ctx, ai, _ = env
        inp = build_input(conn, ctx, ai, DAY)
        m = Model(good_reply(inp))
        r = run_evening_review(conn, ctx, ai, m, DAY)
        assert r.status == "success" and m.calls == 1
        assert r.cost_usd == pytest.approx((1200 * 2.0 + 300 * 10.0) / 1e6)
        (run,) = runs(conn)
        assert (run["status"], run["attempts"], run["model"]) == ("success", 1, "claude-sonnet-5")
        assert (run["input_tokens"], run["output_tokens"]) == (1200, 300)
        assert run["cost_usd_est"] == pytest.approx(0.0054) and run["prompt_sha256"]
        brief = conn.execute("SELECT * FROM ai_outputs WHERE kind='brief'").fetchone()
        assert brief["business_date"] == DAY.isoformat() and brief["run_id"] == run["run_id"]
        picks = conn.execute("SELECT ai_reason, conflict FROM picks ORDER BY pick_id").fetchall()
        assert all(p["ai_reason"].startswith("pick ") for p in picks)
        assert sum(1 for p in picks if p["conflict"] == "wide stop") == 1

    def test_the_prompt_the_model_sees_is_the_data_and_only_the_data(self, env):
        conn, ctx, ai, _ = env
        inp = build_input(conn, ctx, ai, DAY)
        m = Model(good_reply(inp))
        run_evening_review(conn, ctx, ai, m, DAY)
        seen = json.loads(m.seen_user)
        assert set(seen) == {"date", "index_moves", "picks", "strategies", "open_positions"}
        assert "strategy_previews" not in seen

    def test_the_brief_reaches_the_api_and_the_pick_cards(self, env):
        conn, ctx, ai, (client, *_rest) = env
        inp = build_input(conn, ctx, ai, DAY)
        run_evening_review(conn, ctx, ai, Model(good_reply(inp)), DAY)
        b = client.get(f"/api/briefs/{DAY.isoformat()}").json()
        assert b["pending"] is False and b["overview"] == "Indices were flat."
        assert b["conflicts"] == ["one wide stop"] and b["generatedAt"]
        assert all(x["pending"] is False for x in client.get("/api/briefs").json()
                   if x["date"] == DAY.isoformat())
        picks = client.get(f"/api/picks?date={DAY.isoformat()}").json()
        assert all(p["reason"].startswith("pick ") for p in picks)  # the AI reason replaces it
        assert sum(1 for p in picks if p["conflict"] == "wide stop") == 1

    def test_an_invalid_reply_is_recorded_and_stores_nothing(self, env):
        conn, ctx, ai, _ = env
        m = Model(LlmReply("nope", "m"), LlmReply("still nope", "m"))
        r = run_evening_review(conn, ctx, ai, m, DAY)
        assert r.status == "invalid_output" and m.calls == 2
        assert runs(conn)[0]["status"] == "invalid_output"
        assert conn.execute("SELECT COUNT(*) FROM ai_outputs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM picks WHERE ai_reason IS NOT NULL"
                            ).fetchone()[0] == 0

    def test_a_hallucinated_pick_is_retried_then_rejected_never_stored(self, env):
        conn, ctx, ai, _ = env
        inp = build_input(conn, ctx, ai, DAY)
        bad = json.loads(good_reply(inp).text)
        bad["horizons"][0]["ranked"][0]["pick_id"] = 424242
        m = Model(LlmReply(json.dumps(bad), "m"), LlmReply(json.dumps(bad), "m"))
        r = run_evening_review(conn, ctx, ai, m, DAY)
        assert r.status == "invalid_output" and "424242" in (r.detail or runs(conn)[0]["error"])
        assert conn.execute("SELECT COUNT(*) FROM ai_outputs").fetchone()[0] == 0

    def test_a_network_failure_never_raises_and_is_recorded_as_failed(self, env):
        conn, ctx, ai, _ = env
        r = run_evening_review(conn, ctx, ai, Model(LlmError("could not reach the API")), DAY)
        assert r.status == "failed" and "could not reach the API" in r.detail
        assert runs(conn)[0]["status"] == "failed"

    def test_an_oversized_prompt_is_a_recorded_failure_and_makes_no_call(self, env):
        conn, ctx, ai, _ = env
        model = Model()  # any call would raise IndexError
        r = run_evening_review(conn, ctx, ai.model_copy(update={"max_input_chars": 100}),
                               model, DAY)
        assert r.status == "failed" and "max_input_chars=100" in r.detail
        assert runs(conn)[0]["status"] == "failed"

    def test_a_failed_day_is_retried_next_time_but_a_successful_one_is_not(self, env):
        conn, ctx, ai, _ = env
        inp = build_input(conn, ctx, ai, DAY)
        run_evening_review(conn, ctx, ai, Model(LlmError("down")), DAY)
        m = Model(good_reply(inp))
        assert run_evening_review(conn, ctx, ai, m, DAY).status == "success"  # retried
        again = Model()
        r = run_evening_review(conn, ctx, ai, again, DAY)
        assert r.status == "skipped" and again.calls == 0  # no spend for nothing
        assert "already exists" in r.detail

    def test_force_reruns_a_successful_day(self, env):
        conn, ctx, ai, _ = env
        inp = build_input(conn, ctx, ai, DAY)
        run_evening_review(conn, ctx, ai, Model(good_reply(inp)), DAY)
        m = Model(good_reply(inp))
        assert run_evening_review(conn, ctx, ai, m, DAY, force=True).status == "success"
        assert m.calls == 1

    def test_a_day_with_nothing_at_all_to_say_makes_no_call(self, env):
        conn, ctx, ai, _ = env
        m = Model()
        r = run_evening_review(conn, ctx, ai, m, DAYS[5])
        assert r.status == "skipped" and m.calls == 0
        assert runs(conn)[0]["error"].startswith("nothing to review")

    def test_a_pickless_brief_is_written_from_previews_and_writes_back_to_nothing(
            self, preview_env):
        conn, ctx, ai, _ = preview_env
        inp = build_input(conn, ctx, ai, DAY)
        m = Model(pickless_reply(inp))
        r = run_evening_review(conn, ctx, ai, m, DAY)
        assert r.status == "success" and m.calls == 1
        assert conn.execute("SELECT COUNT(*) FROM ai_outputs WHERE kind='brief'"
                            ).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM picks WHERE ai_reason IS NOT NULL"
                            ).fetchone()[0] == 0
        assert "strategy_previews" in json.loads(m.seen_user)

    def test_a_pickless_brief_never_settles_the_day(self, preview_env):
        conn, ctx, ai, _ = preview_env
        inp = build_input(conn, ctx, ai, DAY)
        for _ in range(2):  # no --force: both must actually call the model
            m = Model(pickless_reply(inp))
            assert run_evening_review(conn, ctx, ai, m, DAY).status == "success"
            assert m.calls == 1

    def test_a_horizon_entry_with_no_ranked_picks_does_not_settle_the_day(self, preview_env):
        """Hazard 2: `[{"horizon":"swing","ranked":[]}]` passes every semantic check, so a
        non-empty `horizons` must not be read as 'this brief ranked picks'."""
        conn, ctx, ai, _ = preview_env
        inp = build_input(conn, ctx, ai, DAY)
        empty = [{"horizon": "swing", "ranked": []}]
        assert run_evening_review(conn, ctx, ai, Model(pickless_reply(inp, horizons=empty)),
                                  DAY).status == "success"
        again = Model(pickless_reply(inp))
        assert run_evening_review(conn, ctx, ai, again, DAY).status == "success"
        assert again.calls == 1

    def test_disabled_ai_does_nothing(self, env):
        conn, ctx, ai, _ = env
        m = Model()
        r = run_evening_review(conn, ctx, ai.model_copy(update={"enabled": False}), m, DAY)
        assert r.status == "skipped" and m.calls == 0 and runs(conn) == []

    def test_an_unpriced_model_has_an_unknown_cost_not_a_zero_one(self, env):
        conn, ctx, ai, _ = env
        inp = build_input(conn, ctx, ai, DAY)
        unpriced = ai.model_copy(update={"pricing_usd_per_mtok": {}})
        r = run_evening_review(conn, ctx, unpriced, Model(good_reply(inp)), DAY)
        assert r.status == "success" and r.cost_usd is None
        assert runs(conn)[0]["cost_usd_est"] is None

    def test_the_committed_config_prices_the_default_model(self):
        cfg = load_ai_config()
        # the ACTIVE provider's model must be priced, or every run's cost would be "unknown"
        assert cfg.provider == "groq" and cfg.model == "openai/gpt-oss-120b"
        assert cfg.estimate_cost_usd(cfg.model, 1_000_000, 1_000_000) is not None
        assert cfg.estimate_cost_usd("claude-sonnet-5", 1_000_000, 1_000_000) == pytest.approx(12.0)
        assert cfg.estimate_cost_usd("mystery-model", 1, 1) is None


