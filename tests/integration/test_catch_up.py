"""`stk nightly --catch-up`: what runs when the machine was off for one or more trading days.

The property this exists for: a plain `stk nightly` only ever does ONE day, so a missed timer
firing on a machine that is not always on used to leave a silent hole in the middle of the lake
-- the stale banner would go green the moment the newest day landed. See CLAUDE.md's "Caveat 1".
"""

from __future__ import annotations

from datetime import date

import pytest

from integration.lake import write_bars_daily_only
from stk.cli.orchestrator import (
    CATCH_UP_MAX_DAYS,
    StepOutcome,
    catch_up_day_steps,
    nightly_steps,
    run_catch_up,
)
from stk.store.db.engine import connect, migrate

EXCHANGE = "NSE"
# A real, contiguous trading week -- no weekends, no holidays to account for.
MON, TUE, WED, THU, FRI = (
    date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)
)


@pytest.fixture
def env(tmp_path):
    sqlite_path = tmp_path / "app.db"
    migrate(sqlite_path)
    return sqlite_path, tmp_path / "parquet"


def _mark_trading_days(sqlite_path, days: list[date]) -> None:
    conn = connect(sqlite_path)
    try:
        for d in days:
            conn.execute(
                "INSERT INTO trading_calendar (cal_date, exchange, segment, is_trading_day, "
                "source, captured_at) VALUES (?, ?, 'CM', 1, 'test', '2026-01-01')",
                (d.isoformat(), EXCHANGE),
            )
        conn.commit()
    finally:
        conn.close()


def _set_latest_bar(parquet_root, day: date) -> None:
    write_bars_daily_only(parquet_root, "AAA", [day], [100.0])


class Script:
    """Mirrors test_nightly.py's Script: records what ran, keyed by the first two args."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.codes = codes or {}
        self.ran: list[tuple[str, ...]] = []

    def __call__(self, args, _timeout):
        key = " ".join(args[:2])
        self.ran.append(tuple(args))
        code = self.codes.get(key, 0)
        return StepOutcome(code, f"boom in {key}" if code else "")


def _run(sqlite_path, parquet_root, expected: date, script: Script):
    conn = connect(sqlite_path)
    try:
        return run_catch_up(
            conn, exchange=EXCHANGE, parquet_root=parquet_root, expected=expected, runner=script,
        )
    finally:
        conn.close()


class TestCatchUpDaySteps:
    def test_is_a_strict_subset_of_the_full_nightly_steps(self):
        """Every step name in the reduced set must be a real nightly step -- a typo here would
        silently stop mattering to `needs=` dependency resolution."""
        full_names = {s.name for s in nightly_steps(WED)}
        reduced_names = {s.name for s in catch_up_day_steps(WED)}
        assert reduced_names <= full_names
        assert reduced_names == {"prices", "indices", "playground_eod"}

    def test_playground_eod_needs_prices(self):
        (step,) = [s for s in catch_up_day_steps(WED) if s.name == "playground_eod"]
        assert step.needs == ("prices",)


class TestRunCatchUp:
    def test_no_price_gap_still_runs_todays_full_steps(self, env):
        """No price gap is not the same as nothing to do: prices for `expected` might have been
        ingested by hand (`stk ingest daily`) while scan/preview/track/ai_evening never ran for
        that day. This is what makes --catch-up a safe drop-in replacement for a bare
        `stk nightly`, not just useful after an outage."""
        sqlite_path, parquet_root = env
        _mark_trading_days(sqlite_path, [FRI])
        _set_latest_bar(parquet_root, FRI)
        script = Script()
        report = _run(sqlite_path, parquet_root, FRI, script)

        assert report.days == [FRI]
        assert not report.per_day  # no EARLIER days to reduce
        assert report.final is not None
        assert set(report.final.results) == {s.name for s in nightly_steps(FRI)} - {"corpactions"}
        assert not report.final.failed
        corp_calls = [a for a in script.ran if a[:2] == ("ingest", "corpactions")]
        assert corp_calls == [("ingest", "corpactions", "--since", "2026-09-18")]

    def test_a_single_missing_day_runs_only_the_final_full_steps(self, env):
        """No earlier days to reduce -- this must look just like a plain `stk nightly THU`."""
        sqlite_path, parquet_root = env
        _mark_trading_days(sqlite_path, [WED, THU])
        _set_latest_bar(parquet_root, WED)
        script = Script()
        report = _run(sqlite_path, parquet_root, THU, script)

        assert report.days == [THU]
        assert not report.per_day
        assert report.final is not None and not report.final.failed
        step_names = [args[:2] for args in script.ran]
        assert ("ingest", "corpactions") in step_names
        assert ("ai", "evening") in [a[:2] for a in script.ran]  # the full step list ran

    def test_a_multi_day_gap_runs_reduced_steps_then_full_steps_for_the_last_day(self, env):
        sqlite_path, parquet_root = env
        _mark_trading_days(sqlite_path, [TUE, WED, THU, FRI])
        _set_latest_bar(parquet_root, TUE)
        script = Script()
        report = _run(sqlite_path, parquet_root, FRI, script)

        assert report.days == [WED, THU, FRI]
        assert len(report.per_day) == 2  # WED, THU
        assert report.final is not None

        # WED and THU (the intermediate days) each got ONLY the reduced step set.
        for intermediate in report.per_day:
            assert set(intermediate.results) == {"prices", "indices", "playground_eod"}
            assert not intermediate.failed

        # FRI (the final day) got the FULL nightly step list minus corpactions (which ran
        # once, separately, before the loop -- see below) -- report.final tracks by step NAME,
        # independent of how the runner's args happen to be spelled.
        assert set(report.final.results) == {s.name for s in nightly_steps(FRI)} - {"corpactions"}
        assert not report.final.failed

        # And WED's --date was actually 2026-09-16, not e.g. the final day's date reused by
        # mistake -- checked against the runner's recorded args. (corpactions also carries
        # "2026-09-16" as its --since value, so it is excluded here on purpose.)
        wed_calls = {a for a in script.ran
                    if "2026-09-16" in a and a[:2] != ("ingest", "corpactions")}
        assert {a[:2] for a in wed_calls} == {("ingest", "daily"), ("ingest", "indices"),
                                              ("playground", "eod")}

    def test_corpactions_runs_exactly_once_with_since_the_oldest_missing_day(self, env):
        sqlite_path, parquet_root = env
        _mark_trading_days(sqlite_path, [TUE, WED, THU, FRI])
        _set_latest_bar(parquet_root, TUE)
        script = Script()
        _run(sqlite_path, parquet_root, FRI, script)

        corp_calls = [a for a in script.ran if a[:2] == ("ingest", "corpactions")]
        assert len(corp_calls) == 1
        assert corp_calls[0] == ("ingest", "corpactions", "--since", "2026-09-16")  # WED

    def test_an_early_days_failure_does_not_block_a_later_day(self, env):
        """Each day is a SEPARATE run_steps() call -- a bad day in the middle of a catch-up must
        not silently swallow the rest, the way a `needs=` chain within one day correctly does."""
        sqlite_path, parquet_root = env
        _mark_trading_days(sqlite_path, [TUE, WED, THU, FRI])
        _set_latest_bar(parquet_root, TUE)

        def runner(args, _timeout):
            # Only WED's `ingest daily` fails -- THU and FRI's must be unaffected.
            if args[:2] == ("ingest", "daily") and "2026-09-16" in args:
                return StepOutcome(1, "boom")
            return StepOutcome(0, "")

        report = _run(sqlite_path, parquet_root, FRI, runner)

        assert "2026-09-16:prices" in report.failed
        assert "2026-09-16:playground_eod" in report.failed  # blocked by prices, same day
        # THU (the other reduced day) and FRI (the final day) were unaffected.
        assert "2026-09-17:prices" not in report.failed
        assert "2026-09-18:ai_evening" not in report.failed

    def test_no_lake_at_all_treats_it_as_a_single_day(self, env):
        """A fresh install has no bars_daily yet -- nothing to compute a gap FROM, so this
        behaves like a plain first run for the expected day."""
        sqlite_path, parquet_root = env
        _mark_trading_days(sqlite_path, [FRI])
        script = Script()
        report = _run(sqlite_path, parquet_root, FRI, script)
        assert report.days == [FRI]
        assert not report.per_day

    def test_a_calendar_that_does_not_cover_the_gap_falls_back_to_one_day(self, env):
        """Guessing which of the uncovered days were trading days would be exactly the kind of
        silent default this codebase refuses -- fall back to the single most recent day, the way
        a plain `stk nightly` (no --catch-up) always has."""
        sqlite_path, parquet_root = env
        # No trading_calendar rows at all for the gap.
        _set_latest_bar(parquet_root, TUE)
        script = Script()
        report = _run(sqlite_path, parquet_root, FRI, script)
        assert report.days == [FRI]
        assert not report.per_day

    def test_too_many_missing_days_falls_back_to_a_backfill_suggestion(self, env):
        sqlite_path, parquet_root = env
        far_past = date(2026, 1, 1)
        days = [far_past]
        # Build a long run of consecutive weekday trading days > CATCH_UP_MAX_DAYS.
        d = far_past
        while len(days) <= CATCH_UP_MAX_DAYS + 3:
            d = date.fromordinal(d.toordinal() + 1)
            if d.weekday() < 5:
                days.append(d)
        _mark_trading_days(sqlite_path, days)
        _set_latest_bar(parquet_root, days[0])
        script = Script()
        report = _run(sqlite_path, parquet_root, days[-1], script)

        assert report.fell_back_to_backfill
        assert len(report.days) > CATCH_UP_MAX_DAYS
        assert script.ran == []  # nothing was actually run -- advice only


class TestNightlyCatchUpCli:
    """`stk nightly --catch-up` end to end through the real CLI, pointed at a temp data root."""

    @pytest.fixture
    def cli(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner  # noqa: PLC0415

        from stk.cli.main import app  # noqa: PLC0415
        from stk.config.settings import get_settings  # noqa: PLC0415

        root = tmp_path / "data"
        (root / "parquet").mkdir(parents=True)
        db = root / "app.db"
        migrate(db)
        monkeypatch.setenv("STK_PATHS__DATA_ROOT", str(root))
        get_settings(force_reload=True)
        yield lambda *args: CliRunner().invoke(app, ["nightly", *args]), root
        monkeypatch.undo()
        get_settings(force_reload=True)

    def test_catch_up_and_date_together_are_rejected(self, cli):
        """Guarded in the CLI layer, before run_catch_up (which has no --date concept) is ever
        reached -- the two options ask for genuinely different things."""
        invoke, _root = cli
        result = invoke("--catch-up", "--date", "2026-09-18")
        assert result.exit_code != 0
        assert "mutually exclusive" in str(result.output) + str(result.exception)
