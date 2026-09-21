"""Integration tests for the adjusted-bars rebuild.

Builds bars_daily and corporate_actions directly (this is a pure
derived step over already-ingested data -- no network, no respx) and
checks the end-to-end result: factor timeline, adjusted parquet,
idempotency, and the two ways this step is allowed to be incomplete
(excluded and unresolved actions), which must show up as `degraded`
rather than as a silently smooth price series.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stk.ingest.adjustments import rebuild_adjusted_bars, rebuild_adjusted_bars_job
from stk.store.db.engine import connect, migrate
from stk.store.parquet.layout import (
    adjustment_factors_path,
    bars_daily_adjusted_partition,
    bars_daily_partition,
)
from stk.store.parquet.schema import BARS_DAILY_SCHEMA
from stk.store.parquet.writer import upsert_partition

EX_DATE = date(2026, 6, 15)
BEFORE = date(2026, 6, 12)
AFTER = date(2026, 6, 16)


@pytest.fixture
def env(tmp_path):
    sqlite_path = tmp_path / "app.db"
    migrate(sqlite_path)
    return sqlite_path, tmp_path / "parquet"


def _write_bars(parquet_root: Path, symbol: str, days: list[date], close: float = 100.0) -> None:
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
            "volume": [1000] * n,
            "turnover": [close * 1000] * n,
            "trades": pa.array([50] * n, type=pa.int64()),
            "delivery_qty": pa.array([400] * n, type=pa.int64()),
            "delivery_pct": pa.array([40.0] * n, type=pa.float64()),
            "settle_price": pa.array([None] * n, type=pa.float64()),
            "source": pa.array(["test"] * n).dictionary_encode(),
            "ingested_at": pa.array([datetime.now(UTC)] * n, type=pa.timestamp("us", tz="UTC")),
        },
        schema=BARS_DAILY_SCHEMA,
    )
    for year in {d.year for d in days}:
        year_days = [d for d in days if d.year == year]
        upsert_partition(
            bars_daily_partition(parquet_root, "NSE", year),
            table.filter(pa.compute.field("date").isin(year_days)),
            schema=BARS_DAILY_SCHEMA,
            replace_dates=set(year_days),
        )


def _insert_action(
    sqlite_path: Path,
    *,
    symbol: str = "AAA",
    ex_date: date = EX_DATE,
    price_factor: float | None = 0.5,
    volume_factor: float | None = 2.0,
    parse_status: str = "parsed",
    action_type: str = "BONUS",
    security_id: int | None = None,
    source_hash: str | None = None,
    captured_at: str = "2026-06-01T00:00:00+00:00",
) -> None:
    conn = connect(sqlite_path)
    try:
        conn.execute(
            """INSERT INTO corporate_actions
                   (security_id, symbol, exchange, ex_date, subject_raw, action_type,
                    ratio_numerator, ratio_denominator, price_factor, volume_factor,
                    parse_status, parser_version, source, source_hash, captured_at)
               VALUES (?,?,'NSE',?,?,?,1,1,?,?,?,1,'nse_corp_actions',?,?)""",
            (
                security_id, symbol, ex_date.isoformat(), f"{action_type} 1:1", action_type,
                price_factor, volume_factor, parse_status,
                source_hash or hashlib.sha256(
                    f"{symbol}{ex_date}{action_type}{captured_at}".encode()
                ).hexdigest(),
                captured_at,
            ),
        )
    finally:
        conn.close()


def _adjusted(parquet_root: Path, year: int = 2026):
    path = bars_daily_adjusted_partition(parquet_root, "NSE", year)
    assert path.exists(), "expected an adjusted partition"
    return {
        (r["symbol"], r["date"]): r for r in pq.read_table(path).to_pylist()
    }


class TestRebuild:
    def test_bonus_halves_pre_ex_prices_and_doubles_volumes(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER])
        _insert_action(sqlite_path)

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        rows = _adjusted(parquet_root)
        assert rows[("AAA", BEFORE)]["close"] == 50.0
        assert rows[("AAA", BEFORE)]["volume"] == 2000
        assert rows[("AAA", BEFORE)]["delivery_qty"] == 800

    def test_bar_on_the_ex_date_is_untouched(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER])
        _insert_action(sqlite_path)

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        rows = _adjusted(parquet_root)
        assert rows[("AAA", EX_DATE)]["close"] == 100.0
        assert rows[("AAA", EX_DATE)]["cumulative_price_factor"] == 1.0
        assert rows[("AAA", AFTER)]["close"] == 100.0

    def test_turnover_is_never_scaled(self, env):
        """Rupees traded on the day is a historical fact, and since
        price_factor * volume_factor == 1 it is conserved anyway."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path)

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        rows = _adjusted(parquet_root)
        assert rows[("AAA", BEFORE)]["turnover"] == 100_000.0

    def test_factors_ride_along_on_every_row(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path)

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        rows = _adjusted(parquet_root)
        before = rows[("AAA", BEFORE)]
        assert before["cumulative_price_factor"] == 0.5
        assert before["cumulative_volume_factor"] == 2.0
        # Self-describing: the unadjusted price is recoverable.
        assert before["close"] / before["cumulative_price_factor"] == 100.0

    def test_bars_daily_is_left_byte_identical(self, env):
        """The derived step must never touch the source of truth."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER])
        _insert_action(sqlite_path)

        source = bars_daily_partition(parquet_root, "NSE", 2026)
        before_hash = hashlib.sha256(source.read_bytes()).hexdigest()

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        assert hashlib.sha256(source.read_bytes()).hexdigest() == before_hash

    def test_rerunning_is_idempotent(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER])
        _insert_action(sqlite_path)

        def run_and_hash():
            rebuild_adjusted_bars(
                exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
            )
            path = bars_daily_adjusted_partition(parquet_root, "NSE", 2026)
            table = pq.read_table(path)
            return table.num_rows, table.to_pylist()

        first = run_and_hash()
        second = run_and_hash()
        assert first == second

    def test_writes_the_factor_timeline(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path)

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        rows = pq.read_table(adjustment_factors_path(parquet_root, "NSE")).to_pylist()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAA"
        assert rows[0]["effective_date"] == EX_DATE
        assert rows[0]["cumulative_price_factor"] == 0.5

    def test_no_actions_leaves_prices_unchanged(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        rows = _adjusted(parquet_root)
        assert rows[("AAA", BEFORE)]["close"] == 100.0
        assert rows[("AAA", BEFORE)]["cumulative_price_factor"] == 1.0


class TestDuplicateActions:
    def test_a_republished_action_is_applied_once(self, env):
        """NSE republishing an action with a corrected field creates a
        SECOND corporate_actions row by design (the table is keyed on
        source_hash). Composing both would apply the bonus twice and
        quarter the pre-ex prices."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path, source_hash="hash-one", captured_at="2026-06-01T00:00:00+00:00")
        _insert_action(sqlite_path, source_hash="hash-two", captured_at="2026-06-02T00:00:00+00:00")

        conn = connect(sqlite_path)
        try:
            count = conn.execute("SELECT count(*) AS n FROM corporate_actions").fetchone()["n"]
        finally:
            conn.close()
        assert count == 2, "both rows must survive -- that is the schema's design"

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        rows = _adjusted(parquet_root)
        assert rows[("AAA", BEFORE)]["close"] == 50.0, "applied twice would give 25.0"


class TestRenamesAcrossSymbolHistory:
    def test_factor_carries_across_a_rename(self, env):
        sqlite_path, parquet_root = env
        conn = connect(sqlite_path)
        try:
            conn.execute(
                "INSERT INTO securities (isin, canonical_symbol, company_name, "
                "primary_exchange, status, first_seen_on, last_seen_on, updated_at) "
                "VALUES ('INE000A01001','NEWNAME','Example','NSE','ACTIVE',"
                "'2020-01-01','2026-09-17','2026-09-17T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO listings (security_id, exchange, symbol, series, status, "
                "source, updated_at) VALUES (1,'NSE','NEWNAME','EQ','ACTIVE','test',"
                "'2026-09-17T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO symbol_history (security_id, exchange, symbol, valid_from, "
                "valid_to) VALUES (1,'NSE','OLDNAME','2020-01-01','2026-01-01')"
            )
        finally:
            conn.close()

        # Bars exist under the OLD name, the action is announced under the NEW one.
        _write_bars(parquet_root, "OLDNAME", [BEFORE])
        _insert_action(sqlite_path, symbol="NEWNAME", security_id=1)

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        rows = _adjusted(parquet_root)
        assert rows[("OLDNAME", BEFORE)]["close"] == 50.0

    def test_an_action_stored_under_the_old_name_joins_the_same_timeline(self, env):
        """corporate_actions.security_id is resolved at ingest from CURRENT listings, so an action
        announced before a rename is stored NULL under the old symbol. Once symbol_history knows
        that symbol, both actions must compose into ONE timeline: two timelines for one symbol
        made an old bar take whichever row was nearest, dropping the later action."""
        sqlite_path, parquet_root = env
        conn = connect(sqlite_path)
        try:
            conn.execute(
                "INSERT INTO securities (isin, canonical_symbol, company_name, "
                "primary_exchange, status, first_seen_on, last_seen_on, updated_at) "
                "VALUES ('INE000A01001','NEWNAME','Example','NSE','ACTIVE',"
                "'2020-01-01','2026-09-17','2026-09-17T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO listings (security_id, exchange, symbol, series, status, "
                "source, updated_at) VALUES (1,'NSE','NEWNAME','EQ','ACTIVE','test',"
                "'2026-09-17T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO symbol_history (security_id, exchange, symbol, valid_from, "
                "valid_to) VALUES (1,'NSE','OLDNAME','1900-01-01','2026-04-01')"
            )
        finally:
            conn.close()
        early = date(2026, 3, 2)
        _write_bars(parquet_root, "OLDNAME", [date(2026, 3, 1)])
        _insert_action(sqlite_path, symbol="OLDNAME", ex_date=early, security_id=None)
        _insert_action(sqlite_path, symbol="NEWNAME", security_id=1)

        result = rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        assert _adjusted(parquet_root)[("OLDNAME", date(2026, 3, 1))]["close"] == 25.0
        assert result.unresolved_actions == 0


class TestDegradation:
    def test_ambiguous_action_is_excluded_and_marks_the_job_degraded(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(
            sqlite_path, parse_status="ambiguous", price_factor=None, volume_factor=None,
            action_type="RIGHTS",
        )

        result = rebuild_adjusted_bars_job(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        assert result.excluded_actions == 1
        assert result.degraded

        conn = connect(sqlite_path)
        try:
            status = conn.execute(
                "SELECT status FROM job_runs WHERE job_name='rebuild_adjustments_nse'"
            ).fetchone()["status"]
        finally:
            conn.close()
        assert status == "degraded"

    def test_a_dividend_is_excluded_without_counting_as_degradation(self, env):
        """Dividends legitimately carry no price factor under this
        project's convention -- excluding them is correct, not a gap."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(
            sqlite_path, action_type="DIVIDEND", price_factor=None, volume_factor=None
        )

        result = rebuild_adjusted_bars_job(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        assert result.excluded_actions == 0
        assert not result.degraded

    @pytest.mark.parametrize("action_type", ["DISTRIBUTION", "BUYBACK", "AGM"])
    def test_events_that_do_not_move_the_price_series_never_degrade_the_run(
        self, env, action_type
    ):
        """Real data: 35 buybacks, 1 AGM and 202 InvIT/bond distributions in ~15 months. None of
        them changes the price series, so flagging the run 'degraded' for them would be a
        permanent false alarm -- and a flag that is always on is a flag nobody reads."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path, action_type=action_type, price_factor=None,
                       volume_factor=None)
        result = rebuild_adjusted_bars_job(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root)
        assert result.excluded_actions == 0 and not result.degraded

    @pytest.mark.parametrize("action_type", ["RIGHTS", "DEMERGER", "CONSOLIDATION", "SPLIT",
                                             "BONUS"])
    def test_price_affecting_events_with_no_factor_still_degrade_the_run(self, env, action_type):
        """The other side of the line: these DO move prices, so lacking a factor is a real hole."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path, parse_status="ambiguous", action_type=action_type,
                       price_factor=None, volume_factor=None)
        result = rebuild_adjusted_bars_job(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root)
        assert result.excluded_actions == 1 and result.degraded

    def test_unresolved_security_still_adjusts_but_degrades(self, env):
        """With no securities master, the factor still applies to the
        announced symbol -- but a rename could be missed, so say so."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path, security_id=None)

        result = rebuild_adjusted_bars_job(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        assert result.unresolved_actions == 1
        assert result.degraded
        assert _adjusted(parquet_root)[("AAA", BEFORE)]["close"] == 50.0
