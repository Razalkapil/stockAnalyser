"""The nightly/weekly orchestrator: isolation, dependency blocking, and visibility."""

from __future__ import annotations

import subprocess
from datetime import date

import pytest
from typer.testing import CliRunner

from stk.api.services import _job_alerts
from stk.cli import orchestrator
from stk.cli.main import app
from stk.cli.orchestrator import (
    StepOutcome,
    nightly_steps,
    run_steps,
    subprocess_runner,
    weekly_steps,
)
from stk.store.db.engine import connect, migrate

DAY = date(2026, 9, 18)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "app.db"
    migrate(path)
    c = connect(path)
    yield c
    c.close()


class Script:
    """A runner that records what ran and answers from a table of exit codes by first arg pair."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.codes = codes or {}
        self.ran: list[str] = []

    def __call__(self, args, _timeout):
        key = " ".join(args[:2])
        self.ran.append(key)
        code = self.codes.get(key, 0)
        return StepOutcome(code, f"boom in {key}" if code else "")


def rows(conn):
    return {r["job_name"]: r for r in conn.execute("SELECT * FROM job_runs")}


def test_a_clean_night_records_every_step_as_success(conn):
    script = Script()
    report = run_steps(conn, nightly_steps(DAY), prefix="nightly", business_date=DAY,
                       runner=script)
    assert not report.failed and not report.degraded
    assert {r["status"] for r in rows(conn).values()} == {"success"}
    assert len(rows(conn)) == len(nightly_steps(DAY))
    assert script.ran[0] == "ingest corpactions" and script.ran[-1] == "ai evening"


def test_a_price_failure_blocks_what_reads_prices_but_not_the_rest(conn):
    script = Script({"ingest daily": 1})
    report = run_steps(conn, nightly_steps(DAY), prefix="nightly", business_date=DAY,
                       runner=script)
    assert set(report.failed) == {"prices", "liquidity", "scan", "preview", "track",
                                  "playground_eod", "ai_evening"}
    # independent steps still ran
    assert "ingest corpactions" in script.ran and "ingest indices" in script.ran
    # blocked steps were NOT executed, and say why -- they are recorded, never omitted
    assert all(s not in script.ran for s in ("scan --date", "picks track", "playground eod"))
    r = rows(conn)
    assert "not run: prices failed first" in r["nightly.scan"]["error_message"]
    assert "boom in ingest daily" in r["nightly.prices"]["error_message"]
    assert r["nightly.indices"]["status"] == "success"


def test_an_independent_failure_does_not_block_others(conn):
    script = Script({"ingest corpactions": 1})
    report = run_steps(conn, nightly_steps(DAY), prefix="nightly", business_date=DAY,
                       runner=script)
    assert report.failed == ["corpactions"]
    assert report.results["scan"] == "success"


def test_a_partial_xbrl_run_is_degraded_not_failed(conn):
    report = run_steps(conn, weekly_steps(), prefix="weekly", business_date=DAY,
                       runner=Script({"ingest xbrl": 2}))
    assert report.degraded == ["xbrl"] and not report.failed
    assert rows(conn)["weekly.xbrl"]["status"] == "degraded"


def test_a_failed_upstream_blocks_xbrl(conn):
    report = run_steps(conn, weekly_steps(), prefix="weekly", business_date=DAY,
                       runner=Script({"ingest fundamentals-sweep": 1}))
    assert report.results["fundamentals_sweep"] == "failed" and report.results["xbrl"] == "failed"
    assert report.results["ai_lab"] == "success"


def test_a_runner_that_raises_is_recorded_and_the_run_continues(conn):
    def runner(args, _t):
        if args[:2] == ("ingest", "indices"):
            raise OSError("cannot spawn")
        return StepOutcome(0, "")

    report = run_steps(conn, nightly_steps(DAY), prefix="nightly", business_date=DAY,
                       runner=runner)
    # ai_evening declares `indices` as a dependency: a brief written without today's index close
    # would describe another session (2026-09-24), so it is recorded as blocked, never omitted.
    assert report.failed == ["indices", "ai_evening"]
    assert "cannot spawn" in rows(conn)["nightly.indices"]["error_message"]
    assert "indices" in rows(conn)["nightly.ai_evening"]["error_message"]


def test_a_timeout_is_a_failure(monkeypatch):
    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired("stk", 5)

    monkeypatch.setattr(orchestrator.subprocess, "run", boom)
    out = subprocess_runner(("ingest", "daily"), 5)
    assert out.returncode == 124 and "timed out" in out.tail


def _insert(conn, job, business_date, status, *, started_at="2026-09-18T20:00:00+00:00",
            attempt=1):
    conn.execute(
        "INSERT INTO job_runs (job_name, business_date, status, started_at, attempt, "
        "code_version) VALUES (?,?,?,?,?,'v')",
        (job, business_date, status, started_at, attempt))


class TestAlerts:
    def test_a_failure_alerts_until_a_rerun_succeeds(self, conn):
        run_steps(conn, nightly_steps(DAY)[:2], prefix="nightly", business_date=DAY,
                  runner=Script({"ingest daily": 1}))
        alerts = _job_alerts(conn, DAY)
        assert [a.job for a in alerts] == ["nightly.prices"]
        assert "boom" in alerts[0].message
        run_steps(conn, nightly_steps(DAY)[:2], prefix="nightly", business_date=DAY,
                  runner=Script())
        assert _job_alerts(conn, DAY) == []

    def test_old_failures_are_history(self, conn):
        run_steps(conn, nightly_steps(DAY)[:2], prefix="nightly", business_date=DAY,
                  runner=Script({"ingest daily": 1}))
        assert _job_alerts(conn, date(2026, 9, 30)) == []

    def test_an_ingest_job_is_not_double_reported_when_its_scheduled_step_is(self, conn):
        """The orchestrator runs `ingest daily` as a subprocess and records BOTH the inner
        ingest_nse_prices row and its own nightly.prices row -- one failure, one alert."""
        _insert(conn, "ingest_nse_prices", "2026-09-18", "failed")
        _insert(conn, "nightly.prices", "2026-09-18", "failed")
        assert [a.job for a in _job_alerts(conn, DAY)] == ["nightly.prices"]

    def test_a_hand_run_failure_is_reported_when_no_scheduled_step_covers_it(self, conn):
        """`stk ingest ...` run by hand leaves no nightly.* row. The banner used to stay green
        for those while `stk doctor` listed them."""
        _insert(conn, "ingest_nse_prices", "2026-09-18", "failed")
        assert [a.job for a in _job_alerts(conn, DAY)] == ["ingest_nse_prices"]

    def test_a_job_with_no_business_date_is_placed_by_when_it_started(self, conn):
        _insert(conn, "ingest_xbrl", None, "degraded", started_at="2026-09-18T16:55:00+00:00")
        _insert(conn, "rebuild_adjustments_nse", None, "degraded",
                     started_at="2026-06-01T10:00:00+00:00")
        alerts = _job_alerts(conn, DAY)
        assert [(a.job, a.business_date, a.status) for a in alerts] == [
            ("ingest_xbrl", "2026-09-18", "degraded")]  # the June one is history

    def test_a_degraded_run_says_why_from_its_metrics(self, conn):
        _insert(conn, "rebuild_adjustments_nse", "2026-09-18", "degraded")
        conn.execute("UPDATE job_runs SET metrics_json=? WHERE job_name='rebuild_adjustments_nse'",
                     ('{"factor_rows": 620, "excluded_actions": 293, "unresolved_actions": 0}',))
        (alert,) = _job_alerts(conn, DAY)
        assert alert.message == "factor_rows=620, excluded_actions=293"  # zeros are noise

    def test_a_degraded_runs_string_metric_names_which_symbol_failed(self, conn):
        """`failures=1` alone forces a log-grep to find who; a string metric says it inline."""
        _insert(conn, "ingest_fundamentals_sweep", "2026-09-18", "degraded")
        conn.execute(
            "UPDATE job_runs SET metrics_json=? WHERE job_name='ingest_fundamentals_sweep'",
            ('{"securities": 1270, "failures": 1, "failed_symbols": "RELIANCE"}',))
        (alert,) = _job_alerts(conn, DAY)
        assert alert.message == "securities=1270, failures=1, failed_symbols=RELIANCE"

    def test_a_failure_on_a_known_holiday_is_not_an_alert(self, conn):
        conn.execute(
            "INSERT INTO trading_calendar (cal_date, exchange, segment, is_trading_day, source, "
            "captured_at) VALUES ('2026-09-18','NSE','CM',0,'test','x')")
        _insert(conn, "ingest_nse_prices", "2026-09-18", "failed")
        assert _job_alerts(conn, DAY) == []

    def test_a_rerun_that_succeeded_stops_a_hand_run_alert(self, conn):
        _insert(conn, "ingest_nse_prices", "2026-09-18", "failed", attempt=1)
        _insert(conn, "ingest_nse_prices", "2026-09-18", "success", attempt=2)
        assert _job_alerts(conn, DAY) == []


class TestStepsAreRealCommands:
    """A renamed command or option must fail here, not at 20:30 on a weeknight."""

    @pytest.mark.parametrize("step", nightly_steps(DAY) + weekly_steps(), ids=lambda s: s.name)
    def test_step_resolves(self, step):
        result = CliRunner().invoke(app, [*step.args, "--help"])
        assert result.exit_code == 0, result.output

    def test_step_names_are_unique(self):
        names = [s.name for s in nightly_steps(DAY)]
        assert len(names) == len(set(names))

    def test_needs_only_reference_earlier_steps(self):
        for steps in (nightly_steps(DAY), weekly_steps()):
            seen: set[str] = set()
            for s in steps:
                assert set(s.needs) <= seen, s.name
                seen.add(s.name)
