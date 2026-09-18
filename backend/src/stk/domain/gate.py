"""The promotion gate -- pure.

A strategy goes live only if, over its walk-forward OUT-OF-SAMPLE windows and
AFTER costs, it beats its benchmark in most of them and stays inside a
drawdown limit. The same gate applies to seed and AI-proposed strategies,
no exceptions (the brief's words). Thresholds live in config/promotion.yaml.

Three verdicts, kept distinct on purpose:
  pass                  every check holds
  fail                  enough evidence, and it is not good enough
  insufficient_evidence too few scored windows to say either way -- NOT a
                        pass, and reported differently from a fail because
                        "we could not tell" and "we could tell, and no" call
                        for different next steps (wait for data vs. drop it)

Windows the benchmark did not cover (``no_benchmark``) are excluded from the
count and the pass ratio: with nothing to beat, they are neither wins nor
losses. They are reported so a gate that "passed" on two windows out of ten
is visibly a gate that mostly could not look.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GateThresholds:
    min_scored_windows: int
    min_pass_ratio: float
    max_drawdown: float  # a NEGATIVE fraction, e.g. -0.25 = worst window may lose at most 25%
    min_total_trades: int


@dataclass(frozen=True)
class WindowSummary:
    label: str
    outcome: str  # pass | fail | no_benchmark
    max_drawdown: float  # negative fraction
    trade_count: int


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateReport:
    verdict: str  # pass | fail | insufficient_evidence
    checks: list[GateCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                       for c in self.checks],
        }


def evaluate_gate(windows: list[WindowSummary], t: GateThresholds) -> GateReport:
    scored = [w for w in windows if w.outcome in ("pass", "fail")]
    unscored = len(windows) - len(scored)
    wins = sum(1 for w in scored if w.outcome == "pass")
    total_trades = sum(w.trade_count for w in windows)
    worst_dd = min((w.max_drawdown for w in windows), default=0.0)

    enough = len(scored) >= t.min_scored_windows
    checks = [
        GateCheck(
            "scored_windows", enough,
            f"{len(scored)} scored window(s), need >= {t.min_scored_windows}"
            + (f" ({unscored} had no benchmark and were not counted)" if unscored else ""),
        ),
    ]
    ratio = wins / len(scored) if scored else 0.0
    checks.append(GateCheck(
        "beats_benchmark_after_costs", ratio >= t.min_pass_ratio,
        f"beat the benchmark in {wins}/{len(scored)} windows ({ratio:.0%}), "
        f"need >= {t.min_pass_ratio:.0%}",
    ))
    checks.append(GateCheck(
        "max_drawdown", worst_dd >= t.max_drawdown,
        f"worst window drawdown {worst_dd:.1%}, limit {t.max_drawdown:.1%}",
    ))
    checks.append(GateCheck(
        "enough_trades", total_trades >= t.min_total_trades,
        f"{total_trades} trades, need >= {t.min_total_trades}",
    ))

    if not enough:
        return GateReport("insufficient_evidence", checks)
    return GateReport("pass" if all(c.passed for c in checks) else "fail", checks)
