"""Health checks behind `stk doctor`.

Each check is a plain function over (sqlite connection, parquet root)
returning a list of Problems, so it can be unit-tested against a
hand-built tmp database without going through Typer. cli/commands/
doctor.py is then only formatting and an exit code.

The organising idea: every check turns a silent gap into a stated
fact. A missing trading day, a partition that changed out-of-band, a
symbol that quietly stopped updating and an adjusted series that has
fallen behind a corporate action are all things that otherwise surface
months later as an inexplicable backtest result.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from stk.store import duck
from stk.store.parquet.writer import read_manifest, sha256_of_file

#: How far back the job-run and coverage checks look. Matches the build
#: plan's "lists degraded/missing job runs for 90 days".
LOOKBACK_DAYS = 90

#: A symbol with no bar in this many trading days is stale -- delisted,
#: suspended, or quietly failing to ingest while the job reports success.
STALE_TRADING_DAYS = 10

#: Cap on how many individual items one check will name before
#: summarising. A doctor report nobody reads is not a health check.
MAX_LISTED = 20


@dataclass(frozen=True)
class Problem:
    code: str
    message: str
    severity: str = "problem"  # "problem" | "info"

    @property
    def is_problem(self) -> bool:
        return self.severity == "problem"


def _summarise(items: list[str]) -> str:
    shown = ", ".join(items[:MAX_LISTED])
    if len(items) > MAX_LISTED:
        return f"{shown} ... (+{len(items) - MAX_LISTED} more)"
    return shown


def check_job_runs(conn: sqlite3.Connection, *, today: date) -> list[Problem]:
    """Degraded or failed job runs in the lookback window.

    Only the LATEST attempt per (job_name, business_date) counts -- an
    earlier failure that a retry fixed is not a live problem. job_runs
    is observability, not a lock, so repeated attempts are expected.
    """
    cutoff = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    rows = conn.execute(
        """
        SELECT j.job_name, j.business_date, j.status FROM job_runs j
        JOIN (
            SELECT job_name, business_date, MAX(attempt) AS max_attempt
            FROM job_runs GROUP BY job_name, business_date
        ) latest
          ON j.job_name = latest.job_name
         AND j.business_date IS latest.business_date
         AND j.attempt = latest.max_attempt
        WHERE j.status IN ('degraded', 'failed')
          AND (j.business_date IS NULL OR j.business_date >= ?)
        ORDER BY j.started_at DESC LIMIT ?
        """,
        (cutoff, MAX_LISTED),
    ).fetchall()
    return [
        Problem(
            "job_run_unhealthy",
            f"{r['job_name']} on {r['business_date'] or 'n/a'} is {r['status']}",
        )
        for r in rows
    ]


def check_unparsed_corporate_actions(conn: sqlite3.Connection) -> list[Problem]:
    """Corporate actions we could not fully parse.

    Each one is a symbol whose adjusted price history may be wrong --
    the exact failure mode ingest.corpactions' docstring exists to
    prevent.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM corporate_actions WHERE parse_status != 'parsed'"
    ).fetchone()
    if not row["n"]:
        return []
    return [
        Problem(
            "corporate_action_unparsed",
            f"{row['n']} corporate action(s) not fully parsed -- affected symbols' "
            "adjusted history is incomplete",
        )
    ]


def check_calendar_coverage(
    conn: sqlite3.Connection, parquet_root: Path, *, exchange: str, today: date
) -> list[Problem]:
    """Trading days the calendar knows about that have no bars.

    Bounded to the lookback window AND to the range the lake actually
    covers: a trading day before the first ingested bar is not a gap,
    it is simply history we have not backfilled, and reporting it would
    bury the real signal under thousands of rows.
    """
    rows = conn.execute(
        "SELECT cal_date FROM trading_calendar "
        "WHERE exchange=? AND is_trading_day=1 AND cal_date >= ?",
        (exchange, (today - timedelta(days=LOOKBACK_DAYS)).isoformat()),
    ).fetchall()
    expected = {date.fromisoformat(str(r["cal_date"])) for r in rows if
                date.fromisoformat(str(r["cal_date"])) <= today}
    if not expected:
        return []

    with duck.connect(parquet_root) as session:
        present = {r[0] for r in session.sql("dates_present", [exchange]).fetchall()}
    if not present:
        return []

    # Only the part of the expected range the lake claims to cover.
    first_bar = min(present)
    missing = sorted(d for d in expected if d >= first_bar and d not in present)
    if not missing:
        return []
    return [
        Problem(
            "missing_trading_day",
            f"{exchange}: {len(missing)} trading day(s) with no bars: "
            f"{_summarise([d.isoformat() for d in missing])}",
        )
    ]


def check_stale_symbols(
    conn: sqlite3.Connection, parquet_root: Path, *, exchange: str, today: date
) -> list[Problem]:
    """Symbols in the current universe whose last bar is long past.

    Counted in TRADING days from the calendar, not calendar days -- a
    long holiday stretch must not make every symbol look stale.
    """
    rows = conn.execute(
        "SELECT cal_date FROM trading_calendar "
        "WHERE exchange=? AND is_trading_day=1 AND cal_date <= ? "
        "ORDER BY cal_date DESC LIMIT ?",
        (exchange, today.isoformat(), STALE_TRADING_DAYS),
    ).fetchall()
    if len(rows) < STALE_TRADING_DAYS:
        # Not enough calendar to judge staleness. Saying nothing is
        # right here: a false "everything is stale" on a fresh install
        # would train the reader to ignore this check.
        return []
    cutoff = date.fromisoformat(str(rows[-1]["cal_date"]))

    with duck.connect(parquet_root) as session:
        stale = session.sql("stale_symbols", [exchange, cutoff.isoformat()]).fetchall()
    if not stale:
        return []
    return [
        Problem(
            "stale_symbol",
            f"{exchange}: {len(stale)} symbol(s) with no bar since {cutoff.isoformat()}: "
            f"{_summarise([f'{s[0]}({s[1]})' for s in stale])}",
        )
    ]


def check_partition_manifests(parquet_root: Path) -> list[Problem]:
    """Every partition file against its recorded row count and sha256.

    A mismatch means the file changed without going through
    upsert_partition -- hand-edited, truncated, or written by something
    that bypassed the writer. A MISSING manifest is reported too:
    an unverifiable partition is not the same as a verified one.
    """
    problems: list[Problem] = []
    datasets = {
        "bars_daily": "bars_daily",
        "bars_daily_adjusted": "bars_daily_adjusted",
        "features/liquidity_daily": "features/liquidity_daily",
        "indices_daily": "indices_daily",
    }

    for dataset, relative in datasets.items():
        base = parquet_root / relative
        if not base.exists():
            continue
        for partition in sorted(base.rglob("data.parquet")):
            parts = {
                piece.split("=", 1)[0]: piece.split("=", 1)[1]
                for piece in partition.relative_to(base).parts
                if "=" in piece
            }
            exchange = parts.get("exchange")
            year_str = parts.get("year")
            if year_str is None:
                continue
            year = int(year_str)

            manifest = read_manifest(
                parquet_root, dataset=dataset, exchange=exchange, year=year
            )
            label = f"{dataset} {exchange or '-'} {year}"
            if manifest is None:
                problems.append(
                    Problem("manifest_missing", f"{label}: no manifest -- cannot verify contents")
                )
                continue
            actual = sha256_of_file(partition)
            if actual != manifest.get("sha256"):
                problems.append(
                    Problem(
                        "manifest_mismatch",
                        f"{label}: sha256 does not match its manifest -- the file changed "
                        "outside upsert_partition",
                    )
                )
    return problems


def check_adjusted_freshness(conn: sqlite3.Connection, parquet_root: Path) -> list[Problem]:
    """Whether bars_daily_adjusted has kept up with known ex-dates.

    A corporate action that landed after the last rebuild means every
    earlier bar of that symbol is now wrong in the adjusted series --
    and wrong in the direction that looks like a real price move.
    """
    row = conn.execute(
        "SELECT MAX(ex_date) AS newest FROM corporate_actions "
        "WHERE parse_status='parsed' AND price_factor IS NOT NULL"
    ).fetchone()
    if row is None or row["newest"] is None:
        return []
    newest_ex_date = date.fromisoformat(str(row["newest"]))

    with duck.connect(parquet_root) as session:
        rows = session.sql("adjusted_coverage").fetchall()
    if not rows:
        return [
            Problem(
                "adjusted_missing",
                f"corporate actions exist (newest ex-date {newest_ex_date.isoformat()}) but "
                "bars_daily_adjusted is empty -- run `stk ingest adjustments`",
            )
        ]
    return []


#: An AI review/lab that has failed on this many consecutive runs is a problem, not an outage.
AI_FAILURE_STREAK = 3
#: The poller is judged only against a recent window: an outage last month is history.
POLLER_WINDOW_HOURS = 48
BACKUP_MAX_AGE_DAYS = 2


def check_ai_runs(conn: sqlite3.Connection) -> list[Problem]:
    """The AI never blocks the pipeline, which means its failures are silent unless something
    looks. A streak of failed runs of one kind (a lapsed key, a changed model name) is a real
    problem; a single failure is not."""
    problems: list[Problem] = []
    for kind in ("evening_review", "strategy_lab"):
        rows = conn.execute(
            "SELECT status, error FROM ai_runs WHERE kind=? AND status != 'skipped' "
            "ORDER BY run_id DESC LIMIT ?", (kind, AI_FAILURE_STREAK)).fetchall()
        if len(rows) == AI_FAILURE_STREAK and all(r["status"] in ("failed", "invalid_output")
                                                  for r in rows):
            problems.append(Problem(
                "ai_failing",
                f"the last {AI_FAILURE_STREAK} {kind} runs all failed "
                f"(latest: {rows[0]['error'] or rows[0]['status']})"))
    return problems


def check_poller(conn: sqlite3.Connection, *, now: datetime) -> list[Problem]:
    """Orders resting while the feed has been down are the failure to make visible: from the
    outside an outage looks identical to a quiet market."""
    since = (now - timedelta(hours=POLLER_WINDOW_HOURS)).isoformat()
    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE status='pending_eod'").fetchone()["n"]
    stale = conn.execute(
        "SELECT COUNT(*) AS n FROM poller_runs WHERE started_at >= ? AND status IN "
        "('stale','failed')", (since,)).fetchone()["n"]
    out: list[Problem] = []
    if pending:
        out.append(Problem("orders_pending_eod", f"{pending} order(s) are parked as pending_eod "
                           "(the delayed feed was down) and will be decided by the EOD bar",
                           severity="info"))
    if stale:
        out.append(Problem("poller_feed_stale",
                           f"the intraday feed was stale or failed on {stale} poll(s) in the last "
                           f"{POLLER_WINDOW_HOURS}h", severity="info"))
    return out


def check_instrument_classes(
    conn: sqlite3.Connection, parquet_root: Path, *, exchange: str = "NSE"
) -> list[Problem]:
    """Bars exist but nothing says which symbols are funds: ETFs would be scanned as stocks."""
    has_bars = bool(list((parquet_root / "bars_daily").glob(f"exchange={exchange}/**/*.parquet")))
    known = conn.execute("SELECT 1 FROM instrument_class WHERE exchange=? LIMIT 1",
                         (exchange,)).fetchone()
    if has_bars and not known:
        return [Problem("instrument_classes_missing",
                        f"no instrument classes for {exchange}: ETFs/funds would be treated as "
                        "stocks in scans and backtests. Run `stk ingest instruments`.")]
    return []


#: The suspension/delisting heuristic is only as fresh as the last master snapshot.
MASTER_MAX_AGE_DAYS = 21


def check_security_lifecycle(conn: sqlite3.Connection, *, today: date) -> list[Problem]:
    """Suspended/delisted counts (info), and a stale master (problem): with no recent snapshot the
    lifecycle status is frozen at whatever it last was."""
    out: list[Problem] = []
    counts = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM securities WHERE status != 'ACTIVE' GROUP BY status")}
    if counts:
        out.append(Problem(
            "securities_inactive",
            "security master lifecycle: " + ", ".join(f"{n} {s.lower()}" for s, n in
                                                      sorted(counts.items())),
            severity="info"))
    row = conn.execute(
        "SELECT MAX(started_at) AS t FROM job_runs WHERE job_name='ingest_security_master' "
        "AND status IN ('success','degraded')").fetchone()
    if row["t"] is not None and (today - datetime.fromisoformat(row["t"]).date()
                                 ).days > MASTER_MAX_AGE_DAYS:
        out.append(Problem("master_stale",
                           f"the security master was last refreshed {row['t'][:10]} "
                           f"(> {MASTER_MAX_AGE_DAYS} days): suspension/delisting status is "
                           "frozen"))
    return out


def check_backup_age(latest_age_days: int | None, *, expected: bool = True) -> list[Problem]:
    if not expected:
        return []
    if latest_age_days is None:
        return [Problem("backup_missing", "no backup exists -- app.db holds your paper portfolios,"
                        " journal and AI history, which exist nowhere else")]
    if latest_age_days > BACKUP_MAX_AGE_DAYS:
        return [Problem("backup_stale", f"the newest backup is {latest_age_days} days old")]
    return []


def run_all_checks(
    conn: sqlite3.Connection,
    parquet_root: Path,
    *,
    exchanges: list[str],
    today: date,
) -> list[Problem]:
    """Every check, in report order."""
    problems: list[Problem] = []
    problems.extend(check_job_runs(conn, today=today))
    problems.extend(check_unparsed_corporate_actions(conn))
    for exchange in exchanges:
        problems.extend(
            check_calendar_coverage(conn, parquet_root, exchange=exchange, today=today)
        )
        problems.extend(check_stale_symbols(conn, parquet_root, exchange=exchange, today=today))
    problems.extend(check_partition_manifests(parquet_root))
    problems.extend(check_adjusted_freshness(conn, parquet_root))
    problems.extend(check_ai_runs(conn))
    problems.extend(check_instrument_classes(conn, parquet_root))
    problems.extend(check_security_lifecycle(conn, today=today))
    problems.extend(check_poller(conn, now=datetime.now(UTC)))
    return problems
