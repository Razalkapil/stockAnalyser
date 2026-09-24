"""The weekly strategy lab against a fake model: validation, backtest, gate, and human approval."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from integration.test_promotion import build_lake, cfg, lenient
from stk.ai.client import LlmError, LlmReply
from stk.ai.lab import (
    MAX_AI_GRID,
    lab_problems,
    run_strategy_lab,
    spec_problems,
)
from stk.ai.lab_schemas import LabReply
from stk.api import auth
from stk.api.app import create_app
from stk.config.ai import AiConfig, Price
from stk.config.horizons import load_horizons
from stk.config.promotion import PromotionConfig, _Thresholds
from stk.domain.dsl.model import StrategySpec
from stk.store.db.engine import connect, migrate
from stk.strategies.proposals import (
    ProposalError,
    approve,
    dismiss,
    list_proposals,
    recent_titles,
)
from stk.strategies.repo import get_strategy, register_spec, set_status

HORIZONS = load_horizons()
DAY = date(2026, 9, 18)


def spec_dict(slug="ai_dip_buyer", **over) -> dict:
    base = {
        "slug": slug, "name": "AI dip buyer", "horizon": "swing",
        "universe": {"min_price_raw": 10},
        "entry": {"left": {"ind": "rsi", "period": 2}, "op": "<", "right": 25},
        "exit": {"stop": {"type": "atr", "mult": 2.0}, "target": {"type": "atr", "mult": 3.0},
                 "max_hold_days": 12},
        "rank": {"by": [{"ind": "rsi", "period": 2, "dir": "asc"}], "max_new_per_day": 2},
        "sizing": {"max_positions": 4},
    }
    base.update(over)
    return base


def idea(slug="ai_dip_buyer", title="Buy short-term dips", **over) -> dict:
    return {"title": title, "rationale": "Oversold pullbacks tend to mean-revert within days.",
            "spec_json": json.dumps(spec_dict(slug, **over))}


def reply(proposals=(), demotions=()) -> LlmReply:
    return LlmReply(json.dumps({"proposals": list(proposals), "demotions": list(demotions)}),
                    "claude-sonnet-5", 4000, 900, "end_turn")


class Model:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    def complete(self, *, system, messages, max_tokens):
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


AI = AiConfig(model="claude-sonnet-5",
              pricing_usd_per_mtok={"claude-sonnet-5": Price(input=2.0, output=10.0)})


@pytest.fixture
def lab(tmp_path):
    db, root = tmp_path / "app.db", tmp_path / "parquet"
    root.mkdir()
    migrate(db)
    build_lake(root, with_index=True)
    conn = connect(db)
    seed = StrategySpec.model_validate({
        "slug": "seed_one", "name": "Seed one", "horizon": "swing",
        "entry": {"left": {"ind": "rsi", "period": 14}, "op": "<", "right": 30},
        "exit": {"stop": {"type": "pct", "value": 0.1}, "max_hold_days": 20}})
    sid, _, _ = register_spec(conn, seed, origin="seed")
    set_status(conn, sid, "live", actor="user", reason="test")
    yield conn, root, db
    conn.close()


def run(conn, root, model, promo=None):
    return run_strategy_lab(conn, AI, model, parquet_root=root, cfg=cfg(),
                            promo=promo or lenient(), day=DAY)


class TestLabIsNotRepeatedByAccident:
    """The partial unique index only stops a second OPEN request. Once one closes, nothing stops
    the next -- and a lab run is a model call plus hours of local backtests."""

    def test_a_day_that_already_succeeded_is_skipped_without_a_call(self, lab):
        conn, root, _ = lab
        first = Model(reply([idea()]))
        assert run(conn, root, first).status == "success" and first.calls == 1

        second = Model()
        again = run(conn, root, second)
        assert again.status == "skipped" and "already ran" in again.detail
        assert second.calls == 0

    def test_force_runs_it_again(self, lab):
        conn, root, _ = lab
        run(conn, root, Model(reply([idea()])))
        model = Model(reply([]))
        result = run_strategy_lab(conn, AI, model, parquet_root=root, cfg=cfg(),
                                  promo=lenient(), day=DAY, force=True)
        assert result.status == "success" and model.calls == 1

    def test_a_failed_run_does_not_settle_the_day(self, lab):
        """Only a success counts; a provider outage must stay retryable."""
        conn, root, _ = lab
        assert run(conn, root, Model(LlmError("down"))).status == "failed"
        retry = Model(reply([]))
        assert run(conn, root, retry).status == "success" and retry.calls == 1


class TestSpecValidation:
    def existing(self):
        return {"seed_one"}

    def test_a_good_spec_is_accepted(self):
        spec, errs = spec_problems(json.dumps(spec_dict()), self.existing(), HORIZONS)
        assert errs == [] and spec is not None

    @pytest.mark.parametrize(("over", "match"), [
        ({"entry": {"left": {"ind": "magic"}, "op": ">", "right": 1}}, "unknown indicator"),
        ({"entry": {"left": {"ind": "close"}, "op": ">", "right": 500}}, "back-adjusted price"),
        ({"exit": {"stop": {"type": "pct", "value": 0.1}, "max_hold_days": 999}}, "outside the"),
        ({"slug": "seed_one"}, "already exists"),
        ({"surprise": "x"}, "not a valid strategy spec"),
    ])
    def test_bad_specs_are_named(self, over, match):
        base = spec_dict()
        base.update(over)
        _spec, errs = spec_problems(json.dumps(base), self.existing(), HORIZONS)
        assert any(match in e for e in errs), errs

    def test_not_even_json_is_rejected_not_crashed_on(self):
        assert spec_problems("this is not json", set(), HORIZONS)[0] is None

    def test_code_smuggled_in_as_a_field_is_just_an_unknown_key(self):
        """The AI cannot ship code: the DSL is data, and unknown keys are refused outright."""
        d = spec_dict()
        d["exec"] = "__import__('os').system('rm -rf /')"
        spec, errs = spec_problems(json.dumps(d), set(), HORIZONS)
        assert spec is None and "not a valid strategy spec" in errs[0]

    def test_a_huge_parameter_grid_is_refused(self):
        params = {f"p{i}": {"default": 1, "grid": [1, 2, 3]} for i in range(2)}  # 9 combos
        assert MAX_AI_GRID < 3**2
        _s, errs = spec_problems(json.dumps(spec_dict(params=params)), set(), HORIZONS)
        assert any("combinations" in e for e in errs)


class TestReplyChecks:
    def test_too_many_proposals(self):
        r = LabReply.model_validate({"proposals": [idea(f"ai_s{i}", f"t{i} title") for i in
                                                   range(4)]})
        assert any("at most 3" in p for p in lab_problems(r, {}, HORIZONS))

    def test_demoting_something_that_does_not_exist_or_is_not_live(self):
        r = LabReply.model_validate({"demotions": [
            {"strategy": "ghost", "rationale": "it is decaying badly"},
            {"strategy": "cand", "rationale": "it never worked at all"}]})
        problems = lab_problems(r, {"cand": "candidate"}, HORIZONS)
        assert any("'ghost'" in p for p in problems) and any("only live or decaying" in p
                                                               for p in problems)

    def test_duplicate_slugs_within_one_reply_are_caught(self):
        r = LabReply.model_validate({"proposals": [idea("ai_same", "First idea"),
                                                   idea("ai_same", "Second idea")]})
        assert any("already exists" in p for p in lab_problems(r, {}, HORIZONS))


class TestRun:
    def test_a_good_idea_is_backtested_gated_and_waits_for_a_person(self, lab):
        conn, root, _ = lab
        m = Model(reply([idea()]))
        r = run(conn, root, m)
        assert r.status == "success" and m.calls == 1
        ((_pid, status),) = r.proposals
        assert status == "awaiting_approval"
        s = get_strategy(conn, "ai_dip_buyer")
        assert (s.origin, s.status) == ("ai", "candidate")  # NOT live: a person decides
        (p,) = list_proposals(conn)
        assert p.gate_verdict == "pass" and p.backtest_run_id is not None and p.spec is not None
        run_row = conn.execute("SELECT * FROM backtest_runs WHERE run_id=?",
                               (p.backtest_run_id,)).fetchone()
        assert run_row["kind"] == "walk_forward" and run_row["gate_verdict"] == "pass"

    def test_the_model_call_is_logged_with_cost(self, lab):
        conn, root, _ = lab
        r = run(conn, root, Model(reply([idea()])))
        row = conn.execute("SELECT * FROM ai_runs WHERE kind='strategy_lab'").fetchone()
        assert row["status"] == "success" and row["cost_usd_est"] == pytest.approx(0.017)
        assert r.cost_usd == pytest.approx(0.017)
        assert conn.execute("SELECT COUNT(*) FROM ai_outputs WHERE kind='proposal'"
                            ).fetchone()[0] == 1

    def test_a_failing_gate_is_recorded_as_rejected_and_cannot_be_approved(self, lab):
        conn, root, _ = lab
        strict = PromotionConfig(default=_Thresholds(min_scored_windows=2, min_pass_ratio=0.0,
                                                     max_drawdown=-0.0000001,
                                                     min_total_trades=0))
        r = run(conn, root, Model(reply([idea()])), strict)
        ((pid, status),) = r.proposals
        assert status == "rejected_by_gate"
        assert get_strategy(conn, "ai_dip_buyer").status == "rejected"
        with pytest.raises(ProposalError, match="not awaiting approval"):
            approve(conn, pid)

    def test_no_benchmark_means_the_gate_cannot_decide(self, tmp_path):
        db, root = tmp_path / "a.db", tmp_path / "p"
        root.mkdir()
        migrate(db)
        build_lake(root, with_index=False)
        conn = connect(db)
        r = run(conn, root, Model(reply([idea()])))
        assert r.proposals[0][1] == "insufficient_evidence"
        assert get_strategy(conn, "ai_dip_buyer").status == "candidate"  # not rejected
        conn.close()

    def test_an_invalid_spec_is_recorded_and_never_backtested_or_registered(self, lab):
        conn, root, _ = lab
        bad = idea(entry={"left": {"ind": "magic"}, "op": ">", "right": 1})
        m = Model(reply([bad]), reply([bad]))  # invalid on the retry too
        r = run(conn, root, m)
        ((_pid, status),) = r.proposals
        assert status == "invalid" and m.calls == 2
        assert get_strategy(conn, "ai_dip_buyer") is None
        assert conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0] == 0
        (p,) = list_proposals(conn)
        assert "unknown indicator 'magic'" in p.validation_errors[0]

    def test_the_retry_can_fix_a_bad_spec(self, lab):
        conn, root, _ = lab
        bad = idea(entry={"left": {"ind": "magic"}, "op": ">", "right": 1})
        m = Model(reply([bad]), reply([idea()]))
        r = run(conn, root, m)
        assert m.calls == 2 and r.proposals[0][1] == "awaiting_approval"

    def test_good_ideas_survive_a_bad_sibling(self, lab):
        conn, root, _ = lab
        bad = idea("ai_bad", "A broken idea", entry={"left": {"ind": "magic"}, "op": ">",
                                                    "right": 1})
        m = Model(reply([idea(), bad]), reply([idea(), bad]))
        r = run(conn, root, m)
        assert sorted(s for _, s in r.proposals) == ["awaiting_approval", "invalid"]

    def test_a_backtest_that_cannot_run_is_that_proposals_status_not_a_crash(self, tmp_path):
        db, root = tmp_path / "a.db", tmp_path / "p"
        root.mkdir()
        migrate(db)  # an EMPTY lake
        conn = connect(db)
        r = run(conn, root, Model(reply([idea()])))
        assert r.status == "success" and r.proposals[0][1] == "backtest_error"
        (p,) = list_proposals(conn)
        assert "price lake is empty" in p.status_note
        conn.close()

    def test_a_failed_call_never_raises_and_stores_nothing(self, lab):
        conn, root, _ = lab
        r = run(conn, root, Model(LlmError("could not reach the API")))
        assert r.status == "failed" and list_proposals(conn) == []
        assert conn.execute("SELECT status FROM ai_runs").fetchone()[0] == "failed"

    def test_an_empty_reply_is_a_perfectly_good_outcome(self, lab):
        conn, root, _ = lab
        r = run(conn, root, Model(reply()))
        assert r.status == "success" and r.proposals == [] and list_proposals(conn) == []

    def test_disabled_does_nothing(self, lab):
        conn, root, _ = lab
        m = Model()
        r = run_strategy_lab(conn, AI.model_copy(update={"enabled": False}), m, parquet_root=root,
                             cfg=cfg(), promo=lenient(), day=DAY)
        assert r.status == "skipped" and m.calls == 0

    def test_at_most_three_ideas_are_taken(self, lab):
        conn, root, _ = lab
        ideas = [idea(f"ai_s{i}", f"Idea number {i}") for i in range(3)]
        assert len(run(conn, root, Model(reply(ideas))).proposals) == 3

    def test_recent_proposals_are_remembered_so_they_are_not_asked_for_twice(self, lab):
        conn, root, _ = lab
        run(conn, root, Model(reply([idea(title="Buy short-term dips")])))
        assert "Buy short-term dips" in recent_titles(conn)


class TestDemotions:
    def test_a_demotion_is_stored_and_changes_nothing(self, lab):
        conn, root, _ = lab
        d = {"strategy": "seed_one", "rationale": "Live hit rate is far below its backtest."}
        r = run(conn, root, Model(reply(demotions=[d])))
        ((_pid, status),) = r.proposals
        assert status == "awaiting_approval"
        assert get_strategy(conn, "seed_one").status == "live"  # untouched until a person says so
        (p,) = list_proposals(conn)
        assert (p.type, p.target_slug, p.title) == ("demote", "seed_one", "Retire Seed one")

    def test_one_open_recommendation_per_strategy(self, lab):
        conn, root, _ = lab
        d = {"strategy": "seed_one", "rationale": "Live hit rate is far below its backtest."}
        run(conn, root, Model(reply(demotions=[d])))
        run(conn, root, Model(reply(demotions=[d])))
        assert len(list_proposals(conn)) == 1


class TestHumanDecisions:
    def new_proposal(self, lab):
        conn, root, _ = lab
        r = run(conn, root, Model(reply([idea()])))
        return conn, r.proposals[0][0]

    def test_approving_a_gate_passing_proposal_takes_it_live_and_audits_it(self, lab):
        conn, pid = self.new_proposal(lab)
        approve(conn, pid)
        assert get_strategy(conn, "ai_dip_buyer").status == "live"
        ev = conn.execute("SELECT actor, reason FROM strategy_status_events "
                          "ORDER BY event_id DESC").fetchone()
        assert ev["actor"] == "user" and f"#{pid}" in ev["reason"]
        assert conn.execute("SELECT status FROM strategy_proposals").fetchone()[0] == "approved"

    def test_a_proposal_cannot_be_decided_twice(self, lab):
        conn, pid = self.new_proposal(lab)
        approve(conn, pid)
        with pytest.raises(ProposalError, match="not awaiting"):
            approve(conn, pid)
        with pytest.raises(ProposalError, match="already approved"):
            dismiss(conn, pid)

    def test_a_proposal_that_did_not_pass_the_gate_cannot_be_forced_live(self, lab):
        conn, pid = self.new_proposal(lab)
        conn.execute("UPDATE strategy_proposals SET gate_verdict='fail'")  # e.g. tampered / stale
        with pytest.raises(ProposalError, match="passed the promotion gate"):
            approve(conn, pid)
        assert get_strategy(conn, "ai_dip_buyer").status == "candidate"

    def test_dismissing_retires_the_candidate_the_backtest_created(self, lab):
        conn, pid = self.new_proposal(lab)
        dismiss(conn, pid)
        assert get_strategy(conn, "ai_dip_buyer").status == "retired"
        assert conn.execute("SELECT status FROM strategy_proposals").fetchone()[0] == "dismissed"

    def test_approving_a_demotion_needs_explicit_confirmation(self, lab):
        conn, root, _ = lab
        d = {"strategy": "seed_one", "rationale": "Live hit rate is far below its backtest."}
        pid = run(conn, root, Model(reply(demotions=[d]))).proposals[0][0]
        with pytest.raises(ProposalError, match="confirmation"):
            approve(conn, pid)
        assert get_strategy(conn, "seed_one").status == "live"
        approve(conn, pid, confirm=True)
        assert get_strategy(conn, "seed_one").status == "retired"

    def test_dismissing_a_demotion_leaves_the_strategy_alone(self, lab):
        conn, root, _ = lab
        d = {"strategy": "seed_one", "rationale": "Live hit rate is far below its backtest."}
        pid = run(conn, root, Model(reply(demotions=[d]))).proposals[0][0]
        dismiss(conn, pid)
        assert get_strategy(conn, "seed_one").status == "live"

    def test_unknown_proposal(self, lab):
        with pytest.raises(ProposalError, match="no proposal 999"):
            approve(lab[0], 999)


class TestApi:
    def client(self, lab):
        conn, root, db = lab
        token = auth.create_token(conn, "t")
        app = create_app(sqlite_path=db, parquet_root=root, cfg=cfg())
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def test_lists_proposals_with_out_of_sample_numbers_and_rules(self, lab):
        conn, root, _ = lab
        run(conn, root, Model(reply([idea()])))
        (p,) = self.client(lab).get("/api/proposals").json()
        assert (p["type"], p["status"], p["gateVerdict"]) == ("new", "awaiting_approval", "pass")
        assert p["rules"][0].startswith("rsi2 <") and p["strategyId"] == "ai_dip_buyer"
        assert {"btCagr", "btWinRate", "btMaxDd", "approx", "approxReasons"} <= set(p)

    def test_approve_and_dismiss_over_http(self, lab):
        conn, root, _ = lab
        r = run(conn, root, Model(reply([idea()]),))
        pid = r.proposals[0][0]
        c = self.client(lab)
        assert c.post(f"/api/proposals/{pid}/approve").status_code == 200
        assert c.post(f"/api/proposals/{pid}/approve").status_code == 409  # already decided
        assert c.post(f"/api/proposals/{pid}/dismiss").status_code == 409
        assert get_strategy(connect(lab[2]), "ai_dip_buyer").status == "live"

    def test_a_demotion_needs_confirm_in_the_body(self, lab):
        conn, root, _ = lab
        d = {"strategy": "seed_one", "rationale": "Live hit rate is far below its backtest."}
        pid = run(conn, root, Model(reply(demotions=[d]))).proposals[0][0]
        c = self.client(lab)
        assert c.post(f"/api/proposals/{pid}/approve").status_code == 409
        assert c.post(f"/api/proposals/{pid}/approve", json={"confirm": True}).status_code == 200

    def test_needs_a_token(self, lab):
        _conn, root, db = lab
        assert TestClient(create_app(sqlite_path=db, parquet_root=root)).get(
            "/api/proposals").status_code == 401


