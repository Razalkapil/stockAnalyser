"""Integrated-filing rows -> snapshots -> the SAME XBRL parser -> point-in-time metrics.

Uses the REAL listing rows and the REAL Reliance March-2026 and June-2026 documents (fetched
2026-09-19). The point: the newer filing system needed no new parser -- same element names, same
OneD / FourD / OneI contexts -- and its March filing carries the full year plus a balance sheet.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from stk.ingest.fundamentals import upsert_snapshot
from stk.ingest.fundamentals_metrics import load_filing_facts
from stk.ingest.fundamentals_sweep import sweep_liquid_universe
from stk.ingest.fundamentals_xbrl import ingest_xbrl_documents
from stk.providers.base import SecurityRef
from stk.providers.nse.fundamentals import NseFundamentalsProvider
from stk.store.db.engine import connect, migrate

FIX = Path(__file__).parent.parent / "fixtures" / "nse"
TAGS = yaml.safe_load((Path(__file__).parents[2] / "config" / "xbrl_tags.yaml").read_text())
LISTING = json.loads((FIX / "integrated_filing_listing_trimmed.json").read_text())
MAR = (FIX / "xbrl" / "integrated_reliance_mar2026_consolidated.xml").read_bytes()
JUN = (FIX / "xbrl" / "integrated_reliance_jun2026_consolidated.xml").read_bytes()
LIST_URL = "https://www.nseindia.com/api/integrated-filing-results"
MAR_URL = ("https://nsearchives.nseindia.com/corporate/xbrl/"
           "INTEGRATED_FILING_INDAS_1658776_24042026105714_WEB.xml")
JUN_URL = ("https://nsearchives.nseindia.com/corporate/xbrl/"
           "INTEGRATED_FILING_INDAS_1695741_17072026075004_WEB.xml")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "app.db"
    migrate(path)
    c = connect(path)
    c.execute(
        """INSERT INTO securities (security_id, isin, canonical_symbol, company_name,
               primary_exchange, status, first_seen_on, last_seen_on, updated_at)
           VALUES (1, 'INE002A01018', 'RELIANCE', 'Reliance', 'NSE', 'ACTIVE',
                   '2020-01-01', '2026-01-01', '2026-01-01')""")
    c.close()
    return path


def only_reliance_consolidated(payload: dict) -> dict:
    rows = [r for r in payload["data"] if r["symbol"] == "RELIANCE"
            and r["consolidated"] == "Consolidated"]
    return {**payload, "data": rows, "totalCount": len(rows)}


@respx.mock
def test_the_real_documents_parse_and_yield_a_full_year_and_point_in_time_availability(db):
    respx.get(LIST_URL).mock(return_value=httpx.Response(
        200, json=only_reliance_consolidated(LISTING)))
    respx.get(MAR_URL).mock(return_value=httpx.Response(
        200, content=MAR, headers={"content-type": "application/xml"}))
    respx.get(JUN_URL).mock(return_value=httpx.Response(
        200, content=JUN, headers={"content-type": "application/xml"}))

    conn = connect(db)
    snaps = NseFundamentalsProvider().fetch_integrated_statements(
        SecurityRef(isin="INE002A01018", symbol="RELIANCE", exchange="NSE"))
    assert sum(upsert_snapshot(conn, s) for s in snaps) == 2
    assert sum(upsert_snapshot(conn, s) for s in snaps) == 0  # re-running is a no-op
    conn.close()

    res = ingest_xbrl_documents(sqlite_path=db, raw_root=db.parent / "raw", tag_map=TAGS,
                                throttle_s=0)
    assert (res.parsed, res.partial, res.unsupported, res.malformed) == (2, 0, 0, 0)

    conn = connect(db)
    facts = {f.period_end.isoformat(): f for f in load_filing_facts(conn, lag_days=60)}
    mar, jun = facts["2026-03-31"], facts["2026-06-30"]
    assert mar.is_annual and not jun.is_annual
    assert mar.ytd["revenue"] == pytest.approx(10_756_750_000_000)  # the full year, not Q4
    assert mar.quarter["revenue"] == pytest.approx(2_986_210_000_000)
    assert mar.instant["equity"] == pytest.approx(10_858_660_000_000)  # the March balance sheet
    assert jun.instant == {}  # quarterly filings carry none
    # known the day after each broadcast -- never earlier
    assert mar.available_on.isoformat() == "2026-04-25"
    assert jun.available_on.isoformat() == "2026-07-18"


def make_liquid(db) -> None:
    c = connect(db)
    c.execute("INSERT INTO universe_current (security_id, as_of_date, is_liquid, reason) "
              "VALUES (1, '2026-09-18', 1, 'ok')")
    c.close()


@respx.mock
def test_the_sweep_stores_integrated_filings_alongside_the_legacy_feed(db):
    make_liquid(db)
    respx.get("https://www.nseindia.com/api/corporates-financial-results").mock(
        return_value=httpx.Response(200, json=[]))
    respx.get(LIST_URL).mock(return_value=httpx.Response(
        200, json=only_reliance_consolidated(LISTING)))
    res = sweep_liquid_universe(sqlite_path=db, throttle_s=0)
    assert res.securities == 1 and res.filings_upserted == 2 and res.failures == 0


@respx.mock
def test_an_integrated_endpoint_failure_degrades_the_sweep_but_keeps_the_legacy_data(db):
    make_liquid(db)
    respx.get("https://www.nseindia.com/api/corporates-financial-results").mock(
        return_value=httpx.Response(200, json=[]))
    respx.get(LIST_URL).mock(return_value=httpx.Response(503))
    res = sweep_liquid_universe(sqlite_path=db, throttle_s=0)
    assert res.failures == 1
    conn = connect(db)
    row = conn.execute("SELECT status FROM job_runs WHERE job_name='ingest_fundamentals_sweep'"
                       ).fetchone()
    assert row["status"] == "degraded"


# --- which filings are worth downloading -------------------------------------------------------

from stk.ingest.fundamentals_xbrl import _pending  # noqa: E402


def snap(conn, i, *, consolidated, period_end, security_id=1, url="https://x/y.xml"):
    conn.execute(
        """INSERT INTO fundamentals_snapshots
               (snapshot_id, security_id, provider, statement_type, period_type, period_end,
                consolidated, broadcast_at, captured_at, data_json, source_url, source_hash,
                parser_version)
           VALUES (?, ?, 'nse_filings', 'meta', 'Q', ?, ?, '2026-01-01T00:00:00', 'c', '{}', ?,
                   ?, 1)""",
        (i, security_id, period_end, int(consolidated), url, f"h{i}"))


class TestPending:
    def test_standalone_is_skipped_when_the_company_files_consolidated_results(self, db):
        c = connect(db)
        snap(c, 1, consolidated=True, period_end="2026-03-31")
        snap(c, 2, consolidated=False, period_end="2026-03-31")  # never read by the metrics
        assert [r["snapshot_id"] for r in _pending(c, None, None)] == [1]

    def test_a_standalone_only_company_still_gets_its_standalone_filings(self, db):
        c = connect(db)
        c.execute("""INSERT INTO securities (security_id, isin, canonical_symbol, company_name,
                         primary_exchange, status, first_seen_on, last_seen_on, updated_at)
                     VALUES (2,'INE999A01010','SOLO','n','NSE','ACTIVE','a','a','a')""")
        snap(c, 1, consolidated=False, period_end="2026-03-31", security_id=2)
        assert [r["snapshot_id"] for r in _pending(c, None, None)] == [1]

    def test_periods_older_than_any_metric_needs_are_not_downloaded(self, db):
        c = connect(db)
        snap(c, 1, consolidated=True, period_end="2019-03-31")
        snap(c, 2, consolidated=True, period_end="2023-03-31")
        assert [r["snapshot_id"] for r in _pending(c, None, None)] == [2]
        assert len(_pending(c, None, None, min_period_end="2010-01-01")) == 2

    def test_the_skip_rule_matches_what_the_metrics_loader_actually_reads(self, db):
        """The two must agree, or the skip would silently starve a metric."""
        from stk.ingest.fundamentals_metrics import load_metric_frame  # noqa: PLC0415

        c = connect(db)
        snap(c, 1, consolidated=True, period_end="2026-03-31")
        snap(c, 2, consolidated=False, period_end="2026-03-31")
        c.executemany("INSERT INTO fundamentals_parse_status (snapshot_id, status, detail_json, "
                      "parser_version, parsed_at) VALUES (?, 'parsed', '{}', 1, 'x')",
                      [(1,), (2,)])
        c.execute("UPDATE fundamentals_snapshots SET data_json='{\"symbol\":\"RELIANCE\"}'")
        for sid, rev in ((1, 100.0), (2, 999.0)):
            c.execute("INSERT INTO fundamentals_line_items (snapshot_id, security_id, period_kind, "
                      "item, value, unit, source_tag, parser_version) "
                      "VALUES (?,1,'quarter','revenue',?,'INR','t',1)", (sid, rev))
        facts = load_metric_frame(c, 60)  # one row: the CONSOLIDATED filing only
        assert len(facts) == 1
