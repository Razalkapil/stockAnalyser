"""Unit tests for the individual `stk doctor` checks.

Each check is exercised against a hand-built tmp database and parquet
tree. The recurring theme in these tests is the NEGATIVE case: a check
that fires on a fresh install, or on history we simply have not
backfilled yet, trains the reader to ignore the report -- which is
worse than not having the check.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pytest

from integration.lake import write_index_by_year
from stk.ingest.adjustments import rebuild_adjusted_bars
from stk.ingest.calendar import expected_data_date
from stk.ingest.health import (
    check_adjusted_freshness,
    check_adjusted_jumps,
    check_ai_runs,
    check_backup_age,
    check_calendar_coverage,
    check_fundamentals_freshness,
    check_index_coverage,
    check_job_runs,
    check_partition_manifests,
    check_poller,
    check_security_lifecycle,
    check_stale_symbols,
    check_unparsed_corporate_actions,
)
from stk.store.db.engine import connect, migrate
from stk.store.parquet.layout import bars_daily_partition
from stk.store.parquet.schema import BARS_DAILY_SCHEMA
from stk.store.parquet.writer import upsert_partition

TODAY = date(2026, 9, 18)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "app.db"
    migrate(path)
    conn = connect(path)
    yield conn
    conn.close()


def _write_bars(
    parquet_root: Path, symbol: str, days: list[date], *, with_manifest: bool = True,
    close: float = 100.0,
) -> None:
    n = len(days)
    table = pa.table(
        {
            "date": pa.array(days, type=pa.date32()),
            "exchange": pa.array(["NSE"] * n).dictionary_encode(),
            "symbol": [symbol] * n,
            "security_id": pa.array([None] * n, type=pa.int32()),
            "isin": pa.array([None] * n, type=pa.string()),
            "series": pa.array(["EQ"] * n).dictionary_encode(),
            "instrument_type": pa.array(["EQ"] * n).dictionary_encode(),
            "open": [close] * n, "high": [close] * n, "low": [close] * n, "close": [close] * n,
            "prev_close": [close] * n, "last": [close] * n,
            "vwap": pa.array([None] * n, type=pa.float64()),
            "volume": [1000] * n, "turnover": [100_000.0] * n,
            "trades": pa.array([50] * n, type=pa.int64()),
            "delivery_qty": pa.array([None] * n, type=pa.int64()),
            "delivery_pct": pa.array([None] * n, type=pa.float64()),
            "settle_price": pa.array([None] * n, type=pa.float64()),
            "source": pa.array(["test"] * n).dictionary_encode(),
            "ingested_at": pa.array([datetime.now(UTC)] * n, type=pa.timestamp("us", tz="UTC")),
        },
        schema=BARS_DAILY_SCHEMA,
    )
    for year in {d.year for d in days}:
        year_days = [d for d in days if d.year == year]
        kwargs = (
            {"manifest_root": parquet_root, "dataset": "bars_daily", "exchange": "NSE",
             "year": year}
            if with_manifest
            else {}
        )
        upsert_partition(
            bars_daily_partition(parquet_root, "NSE", year),
            table.filter(pa.compute.field("date").isin(year_days)),
            schema=BARS_DAILY_SCHEMA,
            replace_dates=set(year_days),
            **kwargs,
        )


def _add_calendar(conn, days: list[date], *, trading: bool = True) -> None:
    for day in days:
        conn.execute(
            "INSERT INTO trading_calendar (cal_date, exchange, segment, is_trading_day, "
            "source, captured_at) VALUES (?, 'NSE', 'CM', ?, 'test', ?)",
            (day.isoformat(), int(trading), datetime.now(UTC).isoformat()),
        )


def _add_to_universe(conn, symbol: str, *, liquid: bool = True) -> None:
    """Put a symbol in the current universe snapshot (securities + NSE listing + universe row)."""
    now = datetime.now(UTC).isoformat()
    sid = conn.execute(
        "INSERT INTO securities (isin, canonical_symbol, company_name, primary_exchange, "
        "first_seen_on, last_seen_on, updated_at) VALUES (?, ?, ?, 'NSE', '2021-01-01', "
        "'2026-09-18', ?)", (f"INE{symbol:0<9}"[:12], symbol, symbol, now)).lastrowid
    conn.execute(
        "INSERT INTO listings (security_id, exchange, symbol, source, updated_at) "
        "VALUES (?, 'NSE', ?, 'test', ?)", (sid, symbol, now))
    conn.execute(
        "INSERT INTO universe_current (security_id, as_of_date, is_liquid, reason) "
        "VALUES (?, '2026-09-18', ?, 'test')", (sid, int(liquid)))


def _weekdays(end: date, n: int) -> list[date]:
    days, current = [], end
    while len(days) < n:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return sorted(days)


class TestJobRuns:
    def test_clean_db_reports_nothing(self, db):
        assert check_job_runs(db, today=TODAY) == []

    def test_a_failed_run_is_reported(self, db):
        db.execute(
            "INSERT INTO job_runs (job_name, business_date, status, started_at, attempt, "
            "code_version) VALUES ('ingest_nse_prices', ?, 'failed', ?, 1, 'test')",
            (TODAY.isoformat(), datetime.now(UTC).isoformat()),
        )
        problems = check_job_runs(db, today=TODAY)
        assert len(problems) == 1
        assert problems[0].code == "job_run_unhealthy"

    def test_a_failure_fixed_by_a_retry_is_not_reported(self, db):
        """job_runs is observability, not a lock -- repeated attempts
        are expected, and only the latest one describes reality."""
        for attempt, status in ((1, "failed"), (2, "success")):
            db.execute(
                "INSERT INTO job_runs (job_name, business_date, status, started_at, attempt, "
                "code_version) VALUES ('ingest_nse_prices', ?, ?, ?, ?, 'test')",
                (TODAY.isoformat(), status, datetime.now(UTC).isoformat(), attempt),
            )
        assert check_job_runs(db, today=TODAY) == []

    def test_a_failure_older_than_the_window_is_not_reported(self, db):
        db.execute(
            "INSERT INTO job_runs (job_name, business_date, status, started_at, attempt, "
            "code_version) VALUES ('ingest_nse_prices', ?, 'failed', ?, 1, 'test')",
            ((TODAY - timedelta(days=200)).isoformat(), datetime.now(UTC).isoformat()),
        )
        assert check_job_runs(db, today=TODAY) == []

    def test_a_degraded_run_is_reported(self, db):
        db.execute(
            "INSERT INTO job_runs (job_name, business_date, status, started_at, attempt, "
            "code_version) VALUES ('rebuild_adjustments_nse', ?, 'degraded', ?, 1, 'test')",
            (TODAY.isoformat(), datetime.now(UTC).isoformat()),
        )
        assert len(check_job_runs(db, today=TODAY)) == 1


    def test_a_failure_on_a_day_later_known_to_be_a_holiday_is_not_reported(self, db):
        """On NSE holidays the archive serves the previous session's file and the ingest's
        wrong-date guard refuses it -- correctly. Once the holiday master arrives the day is
        known not to have traded; the failed row is not a problem to alert on forever."""
        holiday = TODAY - timedelta(days=4)
        _add_calendar(db, [holiday], trading=False)
        db.execute(
            "INSERT INTO job_runs (job_name, business_date, status, started_at, attempt, "
            "code_version) VALUES ('ingest_nse_prices', ?, 'failed', ?, 1, 'test')",
            (holiday.isoformat(), datetime.now(UTC).isoformat()),
        )
        assert check_job_runs(db, today=TODAY) == []

    def test_a_failure_on_a_trading_day_is_still_reported_when_the_calendar_knows_it(self, db):
        traded = TODAY - timedelta(days=1)
        _add_calendar(db, [traded], trading=True)
        db.execute(
            "INSERT INTO job_runs (job_name, business_date, status, started_at, attempt, "
            "code_version) VALUES ('ingest_nse_prices', ?, 'failed', ?, 1, 'test')",
            (traded.isoformat(), datetime.now(UTC).isoformat()),
        )
        assert len(check_job_runs(db, today=TODAY)) == 1


class TestUnparsedCorporateActions:
    def test_clean_db_reports_nothing(self, db):
        assert check_unparsed_corporate_actions(db) == []

    def test_unparsed_action_is_reported(self, db):
        db.execute(
            "INSERT INTO corporate_actions (symbol, exchange, subject_raw, parse_status, "
            "parser_version, source, source_hash, captured_at) "
            "VALUES ('AAA', 'NSE', 'Something Odd', 'unparsed', 1, 'nse', 'h1', ?)",
            (datetime.now(UTC).isoformat(),),
        )
        problems = check_unparsed_corporate_actions(db)
        assert len(problems) == 1
        assert problems[0].code == "corporate_action_unparsed"


class TestCalendarCoverage:
    def test_a_missing_trading_day_is_reported(self, db, tmp_parquet_root):
        days = _weekdays(TODAY, 5)
        _add_calendar(db, days)
        _write_bars(tmp_parquet_root, "AAA", [d for d in days if d != days[2]])

        problems = check_calendar_coverage(
            db, tmp_parquet_root, exchange="NSE", today=TODAY
        )
        assert len(problems) == 1
        assert days[2].isoformat() in problems[0].message

    def test_full_coverage_reports_nothing(self, db, tmp_parquet_root):
        days = _weekdays(TODAY, 5)
        _add_calendar(db, days)
        _write_bars(tmp_parquet_root, "AAA", days)

        assert check_calendar_coverage(db, tmp_parquet_root, exchange="NSE", today=TODAY) == []

    def test_history_older_than_the_lake_is_not_a_gap(self, db, tmp_parquet_root):
        """Trading days before the first ingested bar are history we
        have not backfilled -- reporting them would bury the real
        signal under thousands of rows."""
        days = _weekdays(TODAY, 10)
        _add_calendar(db, days)
        _write_bars(tmp_parquet_root, "AAA", days[5:])

        assert check_calendar_coverage(db, tmp_parquet_root, exchange="NSE", today=TODAY) == []

    def test_empty_lake_reports_nothing(self, db, tmp_parquet_root):
        _add_calendar(db, _weekdays(TODAY, 5))
        assert check_calendar_coverage(db, tmp_parquet_root, exchange="NSE", today=TODAY) == []

    def test_holidays_are_not_expected_to_have_bars(self, db, tmp_parquet_root):
        days = _weekdays(TODAY, 5)
        _add_calendar(db, [d for d in days if d != days[2]])
        _add_calendar(db, [days[2]], trading=False)
        _write_bars(tmp_parquet_root, "AAA", [d for d in days if d != days[2]])

        assert check_calendar_coverage(db, tmp_parquet_root, exchange="NSE", today=TODAY) == []


class TestCalendarCoverageBeforeTheDataIsDue:
    def test_todays_missing_bhavcopy_is_not_a_gap_until_it_is_due(self, db, tmp_parquet_root):
        """At 11am on a trading day today's file does not exist yet. Doctor used to report the
        day as missing while the dashboard's stale banner correctly said nothing was late."""
        days = _weekdays(TODAY, 5)
        _add_calendar(db, days)
        _write_bars(tmp_parquet_root, "AAA", days[:-1])  # today (days[-1]) has no bars

        assert check_calendar_coverage(db, tmp_parquet_root, exchange="NSE", today=TODAY) != []
        before_publish = datetime(2026, 9, 18, 11, 0)
        assert check_calendar_coverage(
            db, tmp_parquet_root, exchange="NSE", today=TODAY,
            expected_through=expected_data_date(db, before_publish)) == []

    def test_after_publish_time_the_same_missing_day_is_a_gap(self, db, tmp_parquet_root):
        days = _weekdays(TODAY, 5)
        _add_calendar(db, days)
        _write_bars(tmp_parquet_root, "AAA", days[:-1])

        after_publish = datetime(2026, 9, 18, 19, 0)
        problems = check_calendar_coverage(
            db, tmp_parquet_root, exchange="NSE", today=TODAY,
            expected_through=expected_data_date(db, after_publish))
        assert len(problems) == 1 and days[-1].isoformat() in problems[0].message


class TestStaleSymbols:
    def test_a_universe_symbol_that_stopped_updating_is_reported(self, db, tmp_parquet_root):
        days = _weekdays(TODAY, 20)
        _add_calendar(db, days)
        _write_bars(tmp_parquet_root, "FRESH", days)
        _write_bars(tmp_parquet_root, "STALE", days[:3])
        _add_to_universe(db, "FRESH")
        _add_to_universe(db, "STALE")

        problems = check_stale_symbols(db, tmp_parquet_root, exchange="NSE", today=TODAY)
        assert len(problems) == 1
        assert "STALE" in problems[0].message
        assert "FRESH" not in problems[0].message

    def test_a_symbol_outside_the_universe_is_not_reported(self, db, tmp_parquet_root):
        """A name delisted years ago, a matured rights line: the lake holds ~1,000 of them and
        listing them buried the one thing worth seeing -- a symbol we DO scan going quiet."""
        days = _weekdays(TODAY, 20)
        _add_calendar(db, days)
        _write_bars(tmp_parquet_root, "FRESH", days)
        _write_bars(tmp_parquet_root, "DELISTED", days[:3])
        _write_bars(tmp_parquet_root, "ILLIQUID", days[:3])
        _add_to_universe(db, "FRESH")
        _add_to_universe(db, "ILLIQUID", liquid=False)  # in the snapshot, but not scanned

        assert check_stale_symbols(db, tmp_parquet_root, exchange="NSE", today=TODAY) == []

    def test_says_nothing_without_a_universe_snapshot(self, db, tmp_parquet_root):
        days = _weekdays(TODAY, 20)
        _add_calendar(db, days)
        _write_bars(tmp_parquet_root, "STALE", days[:3])

        assert check_stale_symbols(db, tmp_parquet_root, exchange="NSE", today=TODAY) == []

    def test_says_nothing_without_enough_calendar_to_judge(self, db, tmp_parquet_root):
        """A fresh install must not report every symbol as stale."""
        days = _weekdays(TODAY, 3)
        _add_calendar(db, days)
        _write_bars(tmp_parquet_root, "AAA", days)
        _add_to_universe(db, "AAA")

        assert check_stale_symbols(db, tmp_parquet_root, exchange="NSE", today=TODAY) == []


class TestIndexCoverage:
    """The benchmark is forward-filled by the backtest, so a hole in it never fails loudly: a
    month with no index data reads as a month of a perfectly flat market."""

    def _setup(self, tmp_parquet_root, price_days, bench_days):
        _write_bars(tmp_parquet_root, "AAA", price_days)
        write_index_by_year(tmp_parquet_root, "NIFTY_500", "Nifty 500", bench_days,
                            [100.0 + i for i in range(len(bench_days))])

    def test_a_day_with_prices_but_no_benchmark_is_reported(self, tmp_parquet_root):
        days = _weekdays(TODAY, 6)
        self._setup(tmp_parquet_root, days, [d for d in days if d != days[3]])

        (problem,) = check_index_coverage(tmp_parquet_root, exchange="NSE",
                                          index_code="NIFTY_500")
        assert problem.code == "benchmark_gap" and days[3].isoformat() in problem.message

    def test_full_coverage_reports_nothing(self, tmp_parquet_root):
        days = _weekdays(TODAY, 6)
        self._setup(tmp_parquet_root, days, days)
        assert check_index_coverage(tmp_parquet_root, exchange="NSE",
                                    index_code="NIFTY_500") == []

    def test_history_before_the_benchmark_begins_is_not_a_gap(self, tmp_parquet_root):
        """The free archive starts two years after the price lake: a known limit, not a hole."""
        days = _weekdays(TODAY, 8)
        self._setup(tmp_parquet_root, days, days[4:])
        assert check_index_coverage(tmp_parquet_root, exchange="NSE",
                                    index_code="NIFTY_500") == []

    def test_no_benchmark_at_all_says_nothing(self, tmp_parquet_root):
        _write_bars(tmp_parquet_root, "AAA", _weekdays(TODAY, 4))
        assert check_index_coverage(tmp_parquet_root, exchange="NSE",
                                    index_code="NIFTY_500") == []


class TestPartitionManifests:
    def test_a_matching_partition_reports_nothing(self, tmp_parquet_root):
        _write_bars(tmp_parquet_root, "AAA", _weekdays(TODAY, 3))
        assert check_partition_manifests(tmp_parquet_root) == []

    def test_a_partition_changed_out_of_band_is_detected(self, tmp_parquet_root):
        """The whole point of the manifest: a file rewritten without
        going through upsert_partition."""
        days = _weekdays(TODAY, 3)
        _write_bars(tmp_parquet_root, "AAA", days)

        # Rewrite with fewer rows, bypassing the manifest update.
        _write_bars(tmp_parquet_root, "AAA", days[:1], with_manifest=False)

        problems = check_partition_manifests(tmp_parquet_root)
        assert len(problems) == 1
        assert problems[0].code == "manifest_mismatch"

    def test_a_partition_with_no_manifest_is_reported(self, tmp_parquet_root):
        _write_bars(tmp_parquet_root, "AAA", _weekdays(TODAY, 3), with_manifest=False)

        problems = check_partition_manifests(tmp_parquet_root)
        assert len(problems) == 1
        assert problems[0].code == "manifest_missing"

    def test_empty_lake_reports_nothing(self, tmp_parquet_root):
        assert check_partition_manifests(tmp_parquet_root) == []


class TestAdjustedFreshness:
    def test_no_corporate_actions_means_nothing_to_check(self, db, tmp_parquet_root):
        assert check_adjusted_freshness(db, tmp_parquet_root) == []

    def test_actions_with_no_adjusted_dataset_is_reported(self, db, tmp_parquet_root):
        db.execute(
            "INSERT INTO corporate_actions (symbol, exchange, ex_date, subject_raw, "
            "action_type, price_factor, volume_factor, parse_status, parser_version, "
            "source, source_hash, captured_at) "
            "VALUES ('AAA','NSE','2026-06-15','Bonus 1:1','BONUS',0.5,2.0,'parsed',1,"
            "'nse','h1',?)",
            (datetime.now(UTC).isoformat(),),
        )
        problems = check_adjusted_freshness(db, tmp_parquet_root)
        assert len(problems) == 1
        assert problems[0].code == "adjusted_missing"

    def test_a_dividend_alone_does_not_demand_a_rebuild(self, db, tmp_parquet_root):
        """Dividends carry no price factor by this project's
        convention, so they cannot make an adjusted series stale."""
        db.execute(
            "INSERT INTO corporate_actions (symbol, exchange, ex_date, subject_raw, "
            "action_type, parse_status, parser_version, source, source_hash, captured_at) "
            "VALUES ('AAA','NSE','2026-06-15','Dividend Rs 5','DIVIDEND','parsed',1,"
            "'nse','h1',?)",
            (datetime.now(UTC).isoformat(),),
        )
        assert check_adjusted_freshness(db, tmp_parquet_root) == []


class TestAdjustedJumps:
    """A phantom crash left in the adjusted series: the check that would have caught
    BAJAJFINSV's half-applied split + bonus and AJANTPHARM's unparsed bonus."""

    D1, D2 = date(2026, 6, 12), date(2026, 6, 15)

    def _halve(self, root, symbol):
        _write_bars(root, symbol, [self.D1])
        _write_bars(root, symbol, [self.D2], close=50.0)

    def _action(self, db, symbol, action_type, price_factor):
        db.execute(
            "INSERT INTO corporate_actions (symbol, exchange, ex_date, subject_raw, action_type, "
            "price_factor, volume_factor, parse_status, parser_version, source, source_hash, "
            "captured_at) VALUES (?, 'NSE', ?, 'x', ?, ?, ?, ?, 3, 'nse', ?, ?)",
            (symbol, self.D2.isoformat(), action_type, price_factor,
             None if price_factor is None else 1 / price_factor,
             "parsed" if price_factor else "ambiguous", f"h-{symbol}",
             datetime.now(UTC).isoformat()),
        )

    def _check(self, db, tmp_path, root):
        rebuild_adjusted_bars(exchange="NSE", sqlite_path=tmp_path / "app.db", parquet_root=root)
        return check_adjusted_jumps(db, root)

    def test_an_adjusted_split_leaves_no_jump(self, db, tmp_path, tmp_parquet_root):
        self._halve(tmp_parquet_root, "AAA")
        self._action(db, "AAA", "SPLIT", 0.5)
        assert self._check(db, tmp_path, tmp_parquet_root) == []

    def test_an_unexplained_halving_is_a_problem(self, db, tmp_path, tmp_parquet_root):
        self._halve(tmp_parquet_root, "AAA")
        (problem,) = self._check(db, tmp_path, tmp_parquet_root)
        assert problem.code == "adjusted_jump" and problem.is_problem
        assert "AAA 2026-06-15 x0.50 (no action found)" in problem.message

    def test_a_demerger_is_a_known_hole_not_a_problem(self, db, tmp_path, tmp_parquet_root):
        self._halve(tmp_parquet_root, "AAA")
        self._action(db, "AAA", "DEMERGER", None)
        (problem,) = self._check(db, tmp_path, tmp_parquet_root)
        assert problem.code == "adjusted_jump_known" and not problem.is_problem
        assert "(DEMERGER)" in problem.message

    def test_funds_are_ignored(self, db, tmp_path, tmp_parquet_root):
        self._halve(tmp_parquet_root, "GOLDETF")
        db.execute("INSERT INTO instrument_class (exchange, symbol, isin, class, source_date, "
                   "updated_at) VALUES ('NSE', 'GOLDETF', 'INF000', 'fund', '2026-09-18', 'x')")
        assert self._check(db, tmp_path, tmp_parquet_root) == []


def _ai_run(db, kind, status, *, error=None):
    db.execute(
        "INSERT INTO ai_runs (kind, model, status, started_at, error) VALUES (?,?,?,?,?)",
        (kind, "m", status, "2026-09-18T00:00:00+00:00", error))


class TestAiRuns:
    def test_a_single_failure_is_not_a_problem(self, db):
        _ai_run(db, "evening_review", "success")
        _ai_run(db, "evening_review", "failed", error="529")
        assert check_ai_runs(db) == []

    def test_a_streak_of_failures_is_a_problem_naming_the_latest_error(self, db):
        for err in ("a", "b", "lapsed key"):
            _ai_run(db, "evening_review", "failed", error=err)
        (p,) = check_ai_runs(db)
        assert p.code == "ai_failing" and "lapsed key" in p.message and p.is_problem

    def test_invalid_output_counts_as_failing(self, db):
        for _ in range(3):
            _ai_run(db, "strategy_lab", "invalid_output")
        assert [p.code for p in check_ai_runs(db)] == ["ai_failing"]

    def test_a_success_in_the_streak_clears_it(self, db):
        for st in ("failed", "success", "failed"):
            _ai_run(db, "evening_review", st)
        assert check_ai_runs(db) == []

    def test_skipped_runs_neither_count_nor_break_a_streak(self, db):
        for st in ("failed", "skipped", "failed", "failed"):
            _ai_run(db, "evening_review", st)
        assert [p.code for p in check_ai_runs(db)] == ["ai_failing"]

    def test_kinds_are_judged_separately(self, db):
        _ai_run(db, "evening_review", "failed")
        _ai_run(db, "strategy_lab", "failed")
        _ai_run(db, "evening_review", "failed")
        assert check_ai_runs(db) == []

    def test_no_runs_no_problem(self, db):
        assert check_ai_runs(db) == []


class TestPoller:
    NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)

    def _poll(self, db, status, when):
        db.execute("INSERT INTO poller_runs (started_at, status) VALUES (?,?)",
                   (when.isoformat(), status))

    def test_quiet_when_nothing_happened(self, db):
        assert check_poller(db, now=self.NOW) == []

    def test_recent_stale_polls_are_reported_as_info_not_problems(self, db):
        self._poll(db, "stale", self.NOW - timedelta(hours=2))
        (p,) = check_poller(db, now=self.NOW)
        assert p.code == "poller_feed_stale" and not p.is_problem

    def test_last_months_outage_is_history(self, db):
        self._poll(db, "failed", self.NOW - timedelta(days=30))
        assert check_poller(db, now=self.NOW) == []

    def test_orders_parked_for_eod_are_surfaced(self, db):
        db.execute("INSERT INTO portfolios (name, start_capital, created_at) "
                   "VALUES ('p','100000','2026-01-01')")
        db.execute(
            "INSERT INTO orders (portfolio_id, exchange, symbol, side, order_type, qty, status, "
            "created_at, updated_at) VALUES (1,'NSE','X','buy','MARKET',1,'pending_eod','t','t')")
        (p,) = check_poller(db, now=self.NOW)
        assert p.code == "orders_pending_eod" and "1 order" in p.message


class TestBackupAge:
    def test_missing_backup_is_a_problem(self):
        (p,) = check_backup_age(None)
        assert p.code == "backup_missing" and p.is_problem

    def test_stale_backup_is_a_problem(self):
        assert [p.code for p in check_backup_age(5)] == ["backup_stale"]

    def test_fresh_backup_is_fine(self):
        assert check_backup_age(0) == [] and check_backup_age(2) == []

    def test_not_expected_means_not_checked(self):
        assert check_backup_age(None, expected=False) == []


class TestSecurityLifecycle:
    def _sec(self, db, i, status):
        db.execute(
            "INSERT INTO securities (isin, canonical_symbol, company_name, primary_exchange, "
            "status, first_seen_on, last_seen_on, updated_at) VALUES (?,?,?,'NSE',?,'a','a','a')",
            (f"INE{i:03d}A01010", f"S{i}", "n", status))

    def _master(self, db, when, status="success"):
        db.execute("INSERT INTO job_runs (job_name, status, started_at, attempt, code_version) "
                   "VALUES ('ingest_security_master', ?, ?, 1, 'v')", (status, when))

    def test_quiet_on_a_fresh_install(self, db):
        assert check_security_lifecycle(db, today=TODAY) == []

    def test_reports_inactive_counts_as_info(self, db):
        self._sec(db, 1, "SUSPENDED")
        self._sec(db, 2, "DELISTED")
        self._sec(db, 3, "DELISTED")
        self._sec(db, 4, "ACTIVE")
        (p,) = check_security_lifecycle(db, today=TODAY)
        assert p.code == "securities_inactive" and not p.is_problem
        assert "2 delisted" in p.message and "1 suspended" in p.message

    def test_a_stale_master_is_a_problem(self, db):
        self._master(db, "2026-08-01T00:00:00+00:00")
        (p,) = check_security_lifecycle(db, today=TODAY)
        assert p.code == "master_stale" and p.is_problem

    def test_a_recent_master_is_fine_even_when_degraded(self, db):
        self._master(db, "2026-09-10T00:00:00+00:00", status="degraded")
        assert check_security_lifecycle(db, today=TODAY) == []

    def test_only_successful_runs_count_as_fresh(self, db):
        self._master(db, "2026-08-01T00:00:00+00:00")
        self._master(db, "2026-09-17T00:00:00+00:00", status="failed")
        assert [p.code for p in check_security_lifecycle(db, today=TODAY)] == ["master_stale"]


class TestFundamentalsFreshness:
    def _snap(self, db, broadcast, i=1):
        db.execute(
            "INSERT OR IGNORE INTO securities (security_id, isin, canonical_symbol, company_name, "
            "primary_exchange, status, first_seen_on, last_seen_on, updated_at) "
            "VALUES (1,'INE001A01010','S1','n','NSE','ACTIVE','a','a','a')")
        db.execute(
            "INSERT INTO fundamentals_snapshots (security_id, provider, statement_type, "
            "period_type, period_end, consolidated, broadcast_at, captured_at, is_approximate, "
            "is_restated, currency, unit_multiplier, data_json, source_hash, parser_version) "
            "VALUES (1,'nse_filings','meta','Q',?,1,?,'c',0,0,'INR',1,'{}',?,1)",
            (f"2026-0{i}-01", broadcast, f"h{i}"))

    def test_nothing_ingested_is_not_stale(self, db):
        assert check_fundamentals_freshness(db, today=TODAY) == []

    def test_a_recent_filing_is_fresh(self, db):
        self._snap(db, "2026-09-01T10:00:00")
        assert check_fundamentals_freshness(db, today=TODAY) == []

    def test_a_feed_that_stopped_is_a_problem(self, db):
        self._snap(db, "2025-04-09T12:53:26")  # the legacy feed's real last broadcast
        (p,) = check_fundamentals_freshness(db, today=TODAY)
        assert p.code == "fundamentals_stale" and p.is_problem and "2025-04-09" in p.message

    def test_one_old_and_one_new_filing_is_fresh(self, db):
        self._snap(db, "2025-04-09T12:53:26", 1)
        self._snap(db, "2026-08-01T00:00:00", 2)
        assert check_fundamentals_freshness(db, today=TODAY) == []
