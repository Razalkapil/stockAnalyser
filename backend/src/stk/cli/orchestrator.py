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
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from stk.ingest.calendar import latest_ingested_trading_day, trading_days_between
from stk.ingest.jobs import job_run

# Output kept when a step fails: enough to see the error, not a whole traceback log.
TAIL_CHARS = 1500

#: Beyond this many missing days, a subprocess-per-step-per-day catch-up would be slow and the
#: cheaper `stk backfill` path (built for exactly this) should be used instead.
CATCH_UP_MAX_DAYS = 10

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
        # Informational only -- what the strategies the gate has NOT approved would pick.
        # Nothing depends on it, so its failure costs the run nothing.
        Step("preview", ("strategies", "preview", "--date", d), needs=("prices",)),
        Step("track", ("picks", "track"), needs=("prices",)),
        Step("playground_eod", ("playground", "eod", "--date", d), needs=("prices",)),
        # Never blocks and never fails the run (it exits 0); its failures live in ai_runs.
        Step("ai_evening", ("ai", "evening", "--date", d), needs=("prices", "indices")),
    ]


def weekly_steps() -> list[Step]:
    return [
        Step("master", ("ingest", "master")),
        Step("symbol_changes", ("ingest", "symbol-changes"), needs=("master",)),
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


def catch_up_day_steps(day: date) -> list[Step]:
    """The subset of ``nightly_steps`` that must run for EVERY missed day, in order.

    ``prices`` and ``indices`` so nothing downstream ever reads a gap in the lake or the
    benchmark, and ``playground_eod`` so a stop/target/time exit is evaluated on ITS OWN day's
    bar -- skipping straight to a later day's price would fire (or miss) an exit at the wrong
    price. Deliberately NOT here: ``liquidity``, ``scan``, ``preview``, ``track``, ``ai_evening``
    -- each reflects only the newest day and is about to be superseded by the next day in the
    loop, so running it for an intermediate day would load the backtest panel for nothing (the
    memory constraint this machine has -- see CLAUDE.md). ``corpactions`` is also not here: it is
    not date-scoped (the provider's own rolling window), so one fetch before the whole catch-up
    covers every missed day's ex-dates -- see ``run_catch_up``.
    """
    d = day.isoformat()
    return [
        Step("prices", ("ingest", "daily", "--date", d)),
        Step("indices", ("ingest", "indices", "--date", d)),
        Step("playground_eod", ("playground", "eod", "--date", d), needs=("prices",)),
    ]


@dataclass
class CatchUpReport:
    """What happened across a multi-day catch-up. Unlike a single ``RunReport``, failures must
    say WHICH day they belong to -- "prices failed" is ambiguous across five days."""

    days: list[date]
    corpactions: RunReport | None = None
    per_day: list[RunReport] = field(default_factory=list)
    final: RunReport | None = None
    #: Set when there were too many missing days for this path; see CATCH_UP_MAX_DAYS.
    fell_back_to_backfill: bool = False

    def _tagged(self, attr: str) -> list[str]:
        out = []
        if self.corpactions is not None:
            out += [f"corpactions:{n}" for n in getattr(self.corpactions, attr)]
        for day, report in zip(self.days[:-1], self.per_day, strict=True):
            out += [f"{day.isoformat()}:{n}" for n in getattr(report, attr)]
        if self.final is not None:
            out += [f"{self.days[-1].isoformat()}:{n}" for n in getattr(self.final, attr)]
        return out

    @property
    def failed(self) -> list[str]:
        return self._tagged("failed")

    @property
    def degraded(self) -> list[str]:
        return self._tagged("degraded")


def run_catch_up(
    conn: sqlite3.Connection,
    *,
    exchange: str,
    parquet_root: Path,
    expected: date,
    runner: Runner = subprocess_runner,
    echo: Callable[[str], None] = lambda _m: None,
) -> CatchUpReport:
    """Ingest every trading day missed since the lake was last updated, then ALWAYS run the
    full nightly steps for ``expected`` (today, or the most recent trading day) -- whether or
    not there was a price gap to begin with.

    This is what makes the nightly timer safe on a machine that is not always on: a missed
    20:30 firing used to mean those business days were simply never ingested (``stk nightly``
    with no ``--date`` only ever does ONE day), and the stale banner would go green the moment
    the newest day landed -- a hole in the middle of the lake, invisible. See CLAUDE.md's
    "Caveat 1" for the incident this closes.

    Running the final day's full steps unconditionally, even with an empty gap, matters for a
    real case: prices for ``expected`` ingested by hand (``stk ingest daily``) satisfy
    ``latest_ingested_trading_day``, but scan/preview/track/ai_evening never ran for that day --
    a "no gap" verdict must not be read as "nothing to do". This is also what makes
    ``--catch-up`` a safe drop-in replacement for a bare ``stk nightly`` on every call, not just
    the ones that happen to follow an outage.
    """
    missing: list[date]
    latest = latest_ingested_trading_day(parquet_root, exchange)
    if latest is None:
        missing = [expected]
    elif latest >= expected:
        # Prices already reach `expected` -- e.g. `stk ingest daily` was run by hand. There is
        # NO price gap, but that is not the same as "nothing to do": scan/preview/track/
        # ai_evening for `expected` may never have run. Falling through with missing=[] and
        # letting the code below always process `expected` in full is what makes --catch-up a
        # safe drop-in replacement for a bare `stk nightly` even when there is no gap at all.
        missing = []
    else:
        covered = trading_days_between(conn, latest + timedelta(days=1), expected, exchange)
        if covered is None:
            # The calendar does not fully cover the gap. Guessing which days to skip is exactly
            # the silent-default this codebase refuses to do -- fall back to the single most
            # recent day, same as a plain `stk nightly` always has, and say why.
            echo("catch-up: trading calendar does not cover the missing range -- run "
                 "`stk ingest calendar` first. Falling back to today only.")
            missing = [expected]
        else:
            missing = covered

    if len(missing) > CATCH_UP_MAX_DAYS:
        echo(
            f"catch-up: {len(missing)} trading days missing ({missing[0].isoformat()} to "
            f"{missing[-1].isoformat()}) -- too many for a subprocess-per-step-per-day loop. "
            f"Run `stk backfill prices --exchange {exchange} --from {missing[0].isoformat()} "
            f"--to {missing[-2].isoformat()}` and the matching `stk backfill indices`, then "
            f"`stk nightly --date {missing[-1].isoformat()}` (or re-run `--catch-up`, which will "
            "then see a short enough gap to finish the rest)."
        )
        return CatchUpReport(days=missing, fell_back_to_backfill=True)

    # Every earlier day that needs the reduced step set -- `expected` itself ALWAYS gets the
    # full step list below (via `final`), whether or not it happened to be in `missing`.
    earlier_days = [d for d in missing if d != expected]
    all_days = [*earlier_days, expected]

    if earlier_days:
        echo(f"catch-up: {len(earlier_days)} earlier day(s) missing -- "
             f"{', '.join(d.isoformat() for d in earlier_days)}")
    else:
        echo(f"catch-up: prices already reach {expected.isoformat()}; "
             "running today's full steps")

    # Not date-scoped (the provider's own rolling window): one fetch, before any day's EOD pass,
    # covers every missed day's ex-dates. --since guarantees the window reaches the oldest gap
    # even if the provider's own default window is narrower than the outage (or than `expected`
    # itself, when there is no gap at all).
    since = earlier_days[0] if earlier_days else expected
    corpactions = run_steps(
        conn, [Step("corpactions", ("ingest", "corpactions", "--since", since.isoformat()))],
        prefix="nightly", business_date=expected, runner=runner, echo=echo,
    )

    per_day = []
    for day in earlier_days:
        echo(f"catch-up {day.isoformat()}:")
        per_day.append(run_steps(conn, catch_up_day_steps(day), prefix="nightly",
                                 business_date=day, runner=runner, echo=echo))

    echo(f"nightly {expected.isoformat()} (final day, full steps):")
    final_steps = [s for s in nightly_steps(expected) if s.name != "corpactions"]
    final = run_steps(conn, final_steps, prefix="nightly", business_date=expected,
                      runner=runner, echo=echo)

    return CatchUpReport(days=all_days, corpactions=corpactions, per_day=per_day, final=final)
