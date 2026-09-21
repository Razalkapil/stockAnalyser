"""The promotion gate: three distinct verdicts, and what each one does to a strategy's status."""

from __future__ import annotations

import pytest

from stk.config.promotion import PromotionConfig, load_promotion_config
from stk.domain.gate import GateThresholds, WindowSummary, evaluate_gate
from stk.strategies.promotion import status_for

T = GateThresholds(min_scored_windows=4, min_pass_ratio=0.6, max_drawdown=-0.25,
                   min_total_trades=20)


def w(label: str, outcome: str, dd: float = -0.05, trades: int = 8) -> WindowSummary:
    return WindowSummary(label, outcome, dd, trades)


class TestVerdicts:
    def test_pass(self):
        r = evaluate_gate([w("1", "pass"), w("2", "pass"), w("3", "pass"), w("4", "fail")], T)
        assert r.verdict == "pass" and r.passed

    def test_fail_on_too_few_wins(self):
        r = evaluate_gate([w("1", "pass"), w("2", "fail"), w("3", "fail"), w("4", "fail")], T)
        assert r.verdict == "fail"
        assert not next(c for c in r.checks if c.name == "beats_benchmark_after_costs").passed

    def test_fail_on_one_terrible_drawdown_even_if_most_windows_win(self):
        r = evaluate_gate([w("1", "pass"), w("2", "pass"), w("3", "pass", dd=-0.40),
                           w("4", "pass")], T)
        assert r.verdict == "fail"
        assert not next(c for c in r.checks if c.name == "max_drawdown").passed

    def test_too_few_trades_is_insufficient_evidence_not_a_failure(self):
        """A strategy that barely trades (or, like the long-term seed with no fundamentals loaded,
        cannot trade at all) has not been shown to be BAD -- it has not been tested. Calling that
        'failed' would reject ideas for lack of data. It stays a candidate and cannot go live."""
        r = evaluate_gate([w(str(i), "pass", trades=2) for i in range(4)], T)
        assert r.verdict == "insufficient_evidence" and not r.passed
        assert not next(c for c in r.checks if c.name == "enough_trades").passed

    def test_zero_trades_is_insufficient_evidence(self):
        r = evaluate_gate([w(str(i), "fail", trades=0) for i in range(6)], T)
        assert r.verdict == "insufficient_evidence"

    def test_enough_trades_and_windows_but_poor_results_is_a_real_failure(self):
        r = evaluate_gate([w(str(i), "fail", trades=10) for i in range(4)], T)
        assert r.verdict == "fail"

    def test_too_few_windows_is_insufficient_evidence_not_pass_and_not_fail(self):
        r = evaluate_gate([w("1", "pass"), w("2", "pass")], T)
        assert r.verdict == "insufficient_evidence"
        assert not r.passed

    def test_windows_without_a_benchmark_are_not_counted_either_way(self):
        windows = [w("1", "pass"), w("2", "pass"), w("3", "no_benchmark"), w("4", "no_benchmark")]
        r = evaluate_gate(windows, T)
        assert r.verdict == "insufficient_evidence"  # only 2 scored
        detail = next(c for c in r.checks if c.name == "scored_windows").detail
        assert "2 had no benchmark" in detail

    def test_windows_the_strategy_never_traded_in_are_not_counted_either_way(self):
        """The long-term seed's real shape: fundamentals only exist for the last window, so it
        sat out the rest at exactly 0%. Against a rising benchmark that reads as a loss, and
        scoring it so rejected the strategy for lacking data rather than for being bad."""
        windows = [w("1", "no_trades", dd=0.0, trades=0), w("2", "no_trades", dd=0.0, trades=0),
                   w("3", "no_trades", dd=0.0, trades=0), w("4", "pass", trades=25)]
        r = evaluate_gate(windows, T)
        assert r.verdict == "insufficient_evidence"  # only 1 scored, need 4
        detail = next(c for c in r.checks if c.name == "scored_windows").detail
        assert "3 had no trades" in detail

    def test_the_two_unscored_reasons_are_named_apart(self):
        windows = [w("1", "pass"), w("2", "no_trades", trades=0), w("3", "no_benchmark")]
        detail = next(c for c in evaluate_gate(windows, T).checks
                      if c.name == "scored_windows").detail
        assert "1 had no trades" in detail and "1 had no benchmark" in detail

    def test_excluding_empty_windows_cannot_smuggle_a_thin_strategy_through(self):
        """Excluding no_trades windows must not become a back door: a strategy that traded in
        only two windows still has too little evidence to go live, however well it did."""
        windows = [w("1", "pass", trades=40), w("2", "pass", trades=40)] + [
            w(str(i), "no_trades", dd=0.0, trades=0) for i in range(3, 9)
        ]
        assert evaluate_gate(windows, T).verdict == "insufficient_evidence"

    def test_the_boundary_is_inclusive(self):
        # exactly 3 of 5 = 60% and exactly the trade/window minimums
        ws = [w("1", "pass", trades=5), w("2", "pass", trades=5), w("3", "pass", trades=5),
              w("4", "fail", trades=5), w("5", "fail", trades=0)]
        assert evaluate_gate(ws, T).verdict == "pass"

    def test_no_windows_at_all(self):
        assert evaluate_gate([], T).verdict == "insufficient_evidence"

    def test_report_serialises_for_storage(self):
        d = evaluate_gate([w("1", "pass")], T).to_dict()
        assert d["verdict"] == "insufficient_evidence"
        assert {c["name"] for c in d["checks"]} >= {"scored_windows", "max_drawdown"}


class TestStatusFromVerdict:
    def report(self, verdict: str):
        ws = {"pass": [w(str(i), "pass") for i in range(4)],
              "fail": [w(str(i), "fail") for i in range(4)],
              "insufficient_evidence": [w("1", "pass")]}[verdict]
        return evaluate_gate(ws, T)

    def test_a_seed_that_passes_goes_live(self):
        assert status_for(self.report("pass"), "seed", ["seed"])[0] == "live"

    def test_an_ai_proposal_that_passes_still_needs_approval(self):
        status, reason = status_for(self.report("pass"), "ai", ["seed"])
        assert status == "candidate" and "awaiting approval" in reason

    def test_a_fail_is_rejected_with_the_failing_checks_named(self):
        status, reason = status_for(self.report("fail"), "seed", ["seed"])
        assert status == "rejected" and "beats_benchmark_after_costs" in reason

    def test_the_reason_names_what_was_missing(self):
        few_trades = evaluate_gate([w(str(i), "pass", trades=1) for i in range(4)], T)
        status, reason = status_for(few_trades, "seed", ["seed"])
        assert status == "candidate" and "1 trades" not in reason and "4 trades" in reason

    def test_insufficient_evidence_is_never_a_rejection(self):
        status, reason = status_for(self.report("insufficient_evidence"), "seed", ["seed"])
        assert status == "candidate" and "could not decide" in reason


class TestConfig:
    def test_committed_config_loads_and_long_term_is_looser(self):
        cfg = load_promotion_config()
        default, long_term = cfg.thresholds_for("swing"), cfg.thresholds_for("long_term")
        assert default.min_scored_windows > long_term.min_scored_windows
        assert default.max_drawdown > long_term.max_drawdown  # -0.25 is stricter than -0.35
        assert "seed" in cfg.auto_live_origins

    def test_unknown_horizon_falls_back_to_default(self):
        cfg = PromotionConfig()
        assert cfg.thresholds_for("whatever") == cfg.thresholds_for("swing")

    @pytest.mark.parametrize("horizon", ["short_term", "swing", "momentum", "long_term"])
    def test_every_horizon_resolves(self, horizon):
        t = load_promotion_config().thresholds_for(horizon)
        assert t.max_drawdown < 0 and 0 < t.min_pass_ratio <= 1
