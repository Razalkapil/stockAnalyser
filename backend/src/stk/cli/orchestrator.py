"""The nightly and weekly runs: an ordered list of `stk` commands, each isolated.

Every step runs as its OWN `stk ...` subprocess. That is the isolation: a crash, an out-of-memory
kill or a hung network call in one step cannot take the others down, and each step is exactly the
command you would type by hand to reproduce it. Each is recorded in ``job_runs`` (name
``nightly.<step>`` / ``weekly.<step>``), so ``/api/status`` and ``stk doctor`` see a failure that
happened at 21:00 without anyone reading a log.

Dependencies are explicit. If the price ingest fails, nothing that reads today's bars runs -- a
scan on yesterday's data would happily produce "today's" picks -- and each blocked step is
recorded as failed with the reason, never omitted. Steps that do not depend on it (indices,
corporate actions) still run.

``job_runs`` stays observability, not a lock: running this twice is always safe, because every
underlying command is idempotent.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from stk.ingest.jobs import job_run

# Output kept when a step fails: enough to see the error, not a whole traceback log.
TAIL_CHARS = 1500

DEFAULT_TIMEOUT_S = 3600
LAB_TIMEOUT_S = 4 * 3600


@dataclass(frozen=True)
class Step:
    name: str
    args: tuple[str, ...]
    #: Steps that must have succeeded for this one to be worth running.
    needs: tuple[str, ...] = ()
    #: Exit codes that mean "finished, but incomplete" -> job status `degraded`, not failed.
    degraded_codes: frozenset[int] = frozenset()
    timeout_s: int = DEFAULT_TIMEOUT_S


@dataclass(frozen=True)
class StepOutcome:
    returncode: int
    tail: str


Runner = Callable[[Sequence[str], int], StepOutcome]


def subprocess_runner(args: Sequence[str], timeout_s: int) -> StepOutcome:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "stk.cli.main", *args],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return StepOutcome(124, f"timed out after {timeout_s}s: {exc}")
    out = (proc.stdout or "") + (proc.stderr or "")
    return StepOutcome(proc.returncode, out[-TAIL_CHARS:])


def nightly_steps(day: date) -> list[Step]:
    d = day.isoformat()
    return [
        # Independent of the price ingest: a bonus announced today must be known before the
        # adjusted series is rebuilt, and an index close does not need our bars.
        Step("corpactions", ("ingest", "corpactions")),
        Step("prices", ("ingest", "daily", "--date", d)),
        Step("indices", ("ingest", "indices", "--date", d)),
        Step("liquidity", ("ingest", "liquidity", "--date", d), needs=("prices",)),
        Step("scan", ("scan", "--date", d), needs=("prices",)),
        Step("track", ("picks", "track"), needs=("prices",)),
        Step("playground_eod", ("playground", "eod", "--date", d), needs=("prices",)),
        # Never blocks and never fails the run (it exits 0); its failures live in ai_runs.
        Step("ai_evening", ("ai", "evening", "--date", d), needs=("prices",)),
    ]


def weekly_steps() -> list[Step]:
    return [
        Step("master", ("ingest", "master")),
        Step("instruments", ("ingest", "instruments")),
        Step("calendar", ("ingest", "calendar")),
        Step("fundamentals_sweep", ("ingest", "fundamentals-sweep")),
        Step("xbrl", ("ingest", "xbrl"), needs=("fundamentals_sweep",),
             degraded_codes=frozenset({2}), timeout_s=LAB_TIMEOUT_S),
        # Reads the freshly-ingested fundamentals, so it goes last.
        Step("ai_lab", ("ai", "lab"), timeout_s=LAB_TIMEOUT_S),
    ]


Status = Literal["success", "degraded", "failed"]


@dataclass
class RunReport:
    prefix: str
    results: dict[str, Status] = field(default_factory=dict)

    @property
    def failed(self) -> list[str]:
        return [n for n, s in self.results.items() if s == "failed"]

    @property
    def degraded(self) -> list[str]:
        return [n for n, s in self.results.items() if s == "degraded"]


class StepFailed(RuntimeError):
    pass


def run_steps(
    conn: sqlite3.Connection,
    steps: Sequence[Step],
    *,
    prefix: str,
    business_date: date,
    runner: Runner = subprocess_runner,
    echo: Callable[[str], None] = lambda _m: None,
) -> RunReport:
    """Run ``steps`` in order, recording each. Returns what happened; never raises for a step."""
    report = RunReport(prefix)
    for step in steps:
        blockers = [n for n in step.needs if report.results.get(n) == "failed"]
        job = f"{prefix}.{step.name}"
        try:
            with job_run(conn, job, business_date=business_date) as handle:
                if blockers:
                    raise StepFailed(f"not run: {', '.join(blockers)} failed first")
                echo(f"  {step.name}: stk {' '.join(step.args)}")
                outcome = runner(step.args, step.timeout_s)
                handle.metrics = {"returncode": outcome.returncode}
                if outcome.returncode in step.degraded_codes:
                    handle.degraded = True
                elif outcome.returncode != 0:
                    raise StepFailed(f"exit {outcome.returncode}: {outcome.tail.strip()}")
        except Exception:  # the job_run row is written; keep going with the next step
            report.results[step.name] = "failed"
            echo(f"  {step.name}: FAILED")
            continue
        report.results[step.name] = "degraded" if handle.degraded else "success"
        echo(f"  {step.name}: {report.results[step.name]}")
    return report
