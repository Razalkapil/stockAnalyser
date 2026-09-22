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
import zlib
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

    def test_a_non_equity_bonus_does_not_degrade_the_run(self, env):
        """A bonus of preference shares ("Bonus Ncrps 1:116") is recognised, understood, and by
        design has no equity factor -- unlike a real BONUS lacking a factor (below), this is not
        a gap. Real data: this was the ONE false alarm making `rebuild_adjustments_nse` cry wolf
        in the category (BONUS) that must never be ignored."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path, action_type="BONUS_NON_EQUITY", price_factor=None,
                       volume_factor=None)
        result = rebuild_adjusted_bars_job(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root)
        assert result.excluded_actions == 0 and not result.degraded

    @pytest.mark.parametrize("action_type", ["RIGHTS", "CONSOLIDATION", "SPLIT", "BONUS"])
    def test_price_affecting_events_with_no_factor_still_degrade_the_run(self, env, action_type):
        """The other side of the line: these DO move prices AND this module could in principle
        still compute a factor for them (a parser fix, more price history...), so lacking one is
        an actionable hole, not a permanent one."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path, parse_status="ambiguous", action_type=action_type,
                       price_factor=None, volume_factor=None)
        result = rebuild_adjusted_bars_job(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root)
        assert result.excluded_actions == 1 and result.excluded_permanent == 0
        assert result.degraded

    @pytest.mark.parametrize("action_type", ["DEMERGER", "CAPITAL_REDUCTION"])
    def test_permanently_unadjustable_events_are_counted_but_never_degrade_the_run(
        self, env, action_type
    ):
        """A demerger needs the spun-off entity's own traded value (no free NSE feed gives it);
        a capital reduction's subject never carries a ratio at all. Neither can EVER get a
        factor from this module's data sources -- reported so nothing is invisible, but a gap
        that can never close must not keep the banner red forever (that is what happened to the
        one BONUS_NON_EQUITY false alarm before it got its own type)."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, AFTER])
        _insert_action(sqlite_path, parse_status="ambiguous", action_type=action_type,
                       price_factor=None, volume_factor=None)
        result = rebuild_adjusted_bars_job(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root)
        assert result.excluded_actions == 0 and result.excluded_permanent == 1
        assert not result.degraded

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
        assert result.unresolved_symbols == ("AAA",)  # which symbol, not just how many
        assert result.degraded
        assert _adjusted(parquet_root)[("AAA", BEFORE)]["close"] == 50.0


def _insert_rights(
    sqlite_path: Path,
    *,
    symbol: str = "AAA",
    ex_date: date = EX_DATE,
    num: int = 1,
    den: int = 1,
    premium: float | None = 0.0,
    face_value: float | None = 10.0,
    parse_status: str = "parsed",
) -> None:
    """A rights row as the v4 parser writes one: ratio and premium, NO price factor."""
    conn = connect(sqlite_path)
    try:
        if face_value is not None:
            # One security PER SYMBOL: sharing a security_id would make these the same company
            # under two names, and a factor would correctly apply to both series.
            sid = 1 + zlib.crc32(symbol.encode()) % 10_000  # stable across processes
            conn.execute(
                """INSERT INTO securities (security_id, isin, canonical_symbol, company_name,
                       primary_exchange, face_value, status, first_seen_on, last_seen_on,
                       updated_at)
                   VALUES (?,?,?,'A Ltd','NSE',?,'ACTIVE','2020-01-01','2026-01-01','2026-01-01')
                   ON CONFLICT(security_id) DO NOTHING""",
                (sid, f"INE{sid:06d}1", symbol, face_value),
            )
            conn.execute(
                """INSERT INTO listings (security_id, exchange, symbol, series, source, updated_at)
                   VALUES (?,'NSE',?, 'EQ','t','2026-01-01')""", (sid, symbol))
        conn.execute(
            """INSERT INTO corporate_actions
                   (symbol, exchange, ex_date, subject_raw, action_type, ratio_numerator,
                    ratio_denominator, issue_premium, price_factor, volume_factor, parse_status,
                    parser_version, source, source_hash, captured_at)
               VALUES (?,'NSE',?,?, 'RIGHTS', ?,?,?, NULL, NULL, ?, 4, 'nse_corp_actions', ?,
                       '2026-06-01T00:00:00+00:00')""",
            (
                symbol, ex_date.isoformat(), f"Rights {num}:{den} @ Premium Rs {premium}/-",
                num, den, premium, parse_status,
                hashlib.sha256(f"rights{symbol}{ex_date}{num}{den}".encode()).hexdigest(),
            ),
        )
    finally:
        conn.close()


class TestRightsIssues:
    """A rights factor is DERIVED here, not read: the parser knows the ratio and the premium,
    and only this step can see the cum-rights close it has to be measured against."""

    def test_a_rights_issue_at_par_adjusts_history_and_stops_degrading_the_run(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER], close=100.0)
        # 1 new share per 1 held at face value 10, cum price 100:
        # TERP = (1*100 + 1*10)/2 = 55  ->  factor 0.55
        _insert_rights(sqlite_path, num=1, den=1, premium=0.0, face_value=10.0)

        result = rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        rows = _adjusted(parquet_root)
        assert rows[("AAA", BEFORE)]["close"] == pytest.approx(55.0)
        assert rows[("AAA", EX_DATE)]["close"] == 100.0   # the ex-date bar is never adjusted
        assert rows[("AAA", AFTER)]["close"] == 100.0
        assert result.rights_applied == 1
        assert result.excluded_actions == 0 and not result.degraded

    def test_the_premium_is_added_to_the_face_value(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER], close=100.0)
        # issue price = 10 + 40 = 50; TERP = (1*100 + 1*50)/2 = 75
        _insert_rights(sqlite_path, num=1, den=1, premium=40.0, face_value=10.0)

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )
        assert _adjusted(parquet_root)[("AAA", BEFORE)]["close"] == pytest.approx(75.0)

    def test_a_face_value_change_after_the_rights_wins_over_todays_value(self, env):
        """The premium was quoted against the face value OF THE DAY. 15 real rights issues are
        followed by a split, and using today's value would misprice every one of them."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER], close=100.0)
        _insert_rights(sqlite_path, num=1, den=1, premium=40.0, face_value=1.0)  # TODAY it is 1
        _insert_action(sqlite_path, symbol="AAA", ex_date=date(2026, 8, 1),
                       action_type="SPLIT", price_factor=0.1, volume_factor=10.0,
                       source_hash="split-after-rights")
        conn = connect(sqlite_path)
        try:  # ... because it split 10 -> 1 AFTER the rights issue
            conn.execute("UPDATE corporate_actions SET face_value_from=10, face_value_to=1 "
                         "WHERE action_type='SPLIT'")
        finally:
            conn.close()

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )
        # Face value at the rights date was 10, so issue price 50 and TERP 75 -- then the later
        # split scales everything before 2026-08-01 by a further 0.1.
        assert _adjusted(parquet_root)[("AAA", BEFORE)]["close"] == pytest.approx(7.5)

    def test_rights_priced_above_the_market_leave_history_alone(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER], close=100.0)
        _insert_rights(sqlite_path, num=1, den=4, premium=500.0, face_value=10.0)

        result = rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )
        assert _adjusted(parquet_root)[("AAA", BEFORE)]["close"] == 100.0
        assert result.rights_applied == 1 and not result.degraded

    def test_a_rights_issue_with_no_price_history_stays_a_counted_hole(self, env):
        """No cum-rights close, no factor -- and it must still be VISIBLE as missing."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [AFTER], close=100.0)  # nothing before the ex-date
        _insert_rights(sqlite_path, num=1, den=1, premium=0.0, face_value=10.0)

        result = rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )
        assert result.rights_applied == 0
        assert result.excluded_actions == 1 and result.degraded

    def test_an_ambiguous_rights_row_is_never_guessed_at(self, env):
        """No premium in the subject means no issue price. Assuming par would invent a discount
        and mark down history that never fell."""
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER], close=100.0)
        _insert_rights(sqlite_path, premium=None, parse_status="ambiguous")

        result = rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )
        assert _adjusted(parquet_root)[("AAA", BEFORE)]["close"] == 100.0
        assert result.rights_applied == 0 and result.excluded_actions == 1

    def test_a_rights_issue_with_no_face_value_is_not_guessed_either(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER], close=100.0)
        _insert_rights(sqlite_path, premium=40.0, face_value=None)

        result = rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )
        assert result.rights_applied == 0 and result.excluded_actions == 1

    def test_a_rights_issue_composes_with_a_later_bonus(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER], close=100.0)
        _insert_rights(sqlite_path, num=1, den=1, premium=0.0, face_value=10.0)  # 0.55
        _insert_action(sqlite_path, symbol="AAA", ex_date=date(2026, 7, 1),
                       source_hash="bonus-after-rights")                          # 0.5

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )
        rows = _adjusted(parquet_root)
        assert rows[("AAA", BEFORE)]["close"] == pytest.approx(27.5)   # 100 * 0.55 * 0.5
        assert rows[("AAA", AFTER)]["close"] == pytest.approx(50.0)    # only the bonus applies

    def test_turnover_is_never_scaled(self, env):
        sqlite_path, parquet_root = env
        _write_bars(parquet_root, "AAA", [BEFORE, EX_DATE, AFTER], close=100.0)
        _insert_rights(sqlite_path, num=1, den=1, premium=0.0, face_value=10.0)

        rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )
        assert _adjusted(parquet_root)[("AAA", BEFORE)]["turnover"] == pytest.approx(100_000.0)


class TestSeveralRightsIssues:
    def test_each_rights_issue_is_priced_against_its_OWN_cum_close(self, env):
        """Regression: the price fetch was bounded by the EARLIEST ex-date, so every later
        rights issue saw no history and silently got no factor -- 24 liquid symbols' worth.
        A single-ex-date test cannot catch it, because then earliest == latest."""
        sqlite_path, parquet_root = env
        early_ex, late_ex = date(2026, 3, 10), date(2026, 9, 10)
        _write_bars(parquet_root, "AAA", [date(2026, 3, 9), early_ex], close=100.0)
        _write_bars(parquet_root, "BBB", [date(2026, 9, 9), late_ex], close=100.0)
        _insert_rights(sqlite_path, symbol="AAA", ex_date=early_ex, num=1, den=1, premium=0.0)
        _insert_rights(sqlite_path, symbol="BBB", ex_date=late_ex, num=1, den=1, premium=0.0)

        result = rebuild_adjusted_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        assert result.rights_applied == 2, "the later rights issue was not priced"
        rows = _adjusted(parquet_root)
        assert rows[("AAA", date(2026, 3, 9))]["close"] == pytest.approx(55.0)
        assert rows[("BBB", date(2026, 9, 9))]["close"] == pytest.approx(55.0)
