"""XBRL ingest end to end: real filings served through a mocked network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx
import yaml

from stk.ingest.fundamentals_metrics import load_metric_frame
from stk.ingest.fundamentals_xbrl import ingest_xbrl_documents
from stk.store.db.engine import connect, migrate

FIXTURES = Path(__file__).parent.parent / "fixtures" / "nse"
REPO = Path(__file__).parent.parent.parent
TAGS = yaml.safe_load((REPO / "config" / "xbrl_tags.yaml").read_text())
Q3_URL = "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_q3.xml"
ANNUAL_URL = "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_annual.xml"
Q3 = (FIXTURES / "xbrl" / "INDAS_reliance_q3fy25_consolidated.xml").read_bytes()
ANNUAL = (FIXTURES / "xbrl" / "INDAS_reliance_fy24_annual_consolidated.xml").read_bytes()


def meta_row(url: str, *, period: str, to_date: str, broadcast: str, bank: str = "N") -> dict:
    return {"symbol": "RELIANCE", "isin": "INE002A01018", "bank": bank, "period": period,
            "toDate": to_date, "broadCastDate": broadcast, "consolidated": "Consolidated",
            "xbrl": url}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "app.db"
    migrate(path)
    conn = connect(path)
    conn.execute(
        """INSERT INTO securities (security_id, isin, canonical_symbol, company_name,
               primary_exchange, status, first_seen_on, last_seen_on, updated_at)
           VALUES (1, 'INE002A01018', 'RELIANCE', 'Reliance', 'NSE', 'ACTIVE',
                   '2020-01-01', '2026-01-01', '2026-01-01')"""
    )
    conn.close()
    return path


def add_snapshot(path: Path, meta: dict, *, period_type: str, period_end: str,
                 broadcast_at: str | None, snap_id: int) -> None:
    conn = connect(path)
    conn.execute(
        """INSERT INTO fundamentals_snapshots
               (snapshot_id, security_id, provider, statement_type, period_type, period_end,
                consolidated, broadcast_at, captured_at, data_json, source_url, source_hash,
                parser_version)
           VALUES (?, 1, 'nse_filings', 'meta', ?, ?, 1, ?, ?, ?, ?, ?, 1)""",
        (snap_id, period_type, period_end, broadcast_at, datetime.now(UTC).isoformat(),
         json.dumps(meta), meta.get("xbrl"), f"h{snap_id}"),
    )
    conn.close()


def run(path: Path, tmp_path: Path, **kw):
    return ingest_xbrl_documents(sqlite_path=path, raw_root=tmp_path / "raw", tag_map=TAGS,
                                 throttle_s=0.0, **kw)


def rows(path: Path, sql: str):
    conn = connect(path)
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


class TestIngest:
    @respx.mock
    def test_parses_stores_line_items_and_records_status(self, db, tmp_path):
        add_snapshot(db, meta_row(Q3_URL, period="Quarterly", to_date="31-Dec-2024",
                                  broadcast="16-Jan-2025 20:20:21"),
                     period_type="Q", period_end="2024-12-31",
                     broadcast_at="2025-01-16T20:20:21", snap_id=1)
        respx.get(Q3_URL).mock(return_value=httpx.Response(200, content=Q3))

        result = run(db, tmp_path)

        assert (result.attempted, result.parsed, result.transient_failures) == (1, 1, 0)
        items = {(r["period_kind"], r["item"]): r["value"] for r in rows(
            db, "SELECT period_kind, item, value FROM fundamentals_line_items")}
        assert items[("quarter", "revenue")] == 1_282_600_000_000.0
        assert items[("ytd", "revenue")] == 3_966_450_000_000.0
        status = rows(db, "SELECT status, raw_sha256 FROM fundamentals_parse_status")[0]
        assert status["status"] == "parsed" and len(status["raw_sha256"]) == 64

    @respx.mock
    def test_raw_bytes_are_on_disk_content_addressed_before_parsing(self, db, tmp_path):
        add_snapshot(db, meta_row(Q3_URL, period="Quarterly", to_date="31-Dec-2024",
                                  broadcast="16-Jan-2025 20:20:21"),
                     period_type="Q", period_end="2024-12-31",
                     broadcast_at="2025-01-16T20:20:21", snap_id=1)
        respx.get(Q3_URL).mock(return_value=httpx.Response(200, content=Q3))
        run(db, tmp_path)
        stored = list((tmp_path / "raw" / "nse_xbrl" / "by-sha").rglob("*.xml"))
        assert len(stored) == 1 and stored[0].read_bytes() == Q3
        assert rows(db, "SELECT COUNT(*) AS n FROM raw_artifacts")[0]["n"] == 1

    @respx.mock
    def test_rerun_fetches_nothing_new(self, db, tmp_path):
        add_snapshot(db, meta_row(Q3_URL, period="Quarterly", to_date="31-Dec-2024",
                                  broadcast="16-Jan-2025 20:20:21"),
                     period_type="Q", period_end="2024-12-31",
                     broadcast_at="2025-01-16T20:20:21", snap_id=1)
        route = respx.get(Q3_URL).mock(return_value=httpx.Response(200, content=Q3))
        run(db, tmp_path)
        second = run(db, tmp_path)
        assert route.call_count == 1  # the ledger, not a lock: nothing pending, nothing fetched
        assert second.attempted == 0

    @respx.mock
    def test_banks_are_recorded_unsupported_without_a_fetch(self, db, tmp_path):
        add_snapshot(db, meta_row("https://nsearchives.nseindia.com/x.xml", period="Quarterly",
                                  to_date="31-Dec-2024", broadcast="16-Jan-2025 20:20:21",
                                  bank="Y"),
                     period_type="Q", period_end="2024-12-31",
                     broadcast_at="2025-01-16T20:20:21", snap_id=1)
        route = respx.get("https://nsearchives.nseindia.com/x.xml")
        result = run(db, tmp_path)
        assert route.call_count == 0
        assert result.unsupported == 1
        st = rows(db, "SELECT status, detail_json FROM fundamentals_parse_status")[0]
        assert st["status"] == "unsupported_format" and "bank" in st["detail_json"]
        assert rows(db, "SELECT COUNT(*) AS n FROM fundamentals_line_items")[0]["n"] == 0

    @respx.mock
    def test_a_transient_failure_is_retried_next_run_and_marks_the_job_degraded(
        self, db, tmp_path
    ):
        add_snapshot(db, meta_row(Q3_URL, period="Quarterly", to_date="31-Dec-2024",
                                  broadcast="16-Jan-2025 20:20:21"),
                     period_type="Q", period_end="2024-12-31",
                     broadcast_at="2025-01-16T20:20:21", snap_id=1)
        respx.get(Q3_URL).mock(side_effect=httpx.ConnectError("boom"))
        first = run(db, tmp_path)
        assert first.transient_failures == 1
        assert rows(db, "SELECT COUNT(*) AS n FROM fundamentals_parse_status")[0]["n"] == 0
        assert rows(db, "SELECT status FROM job_runs WHERE job_name='ingest_xbrl'")[0][
            "status"] == "degraded"

        respx.get(Q3_URL).mock(return_value=httpx.Response(200, content=Q3))
        second = run(db, tmp_path)
        assert second.parsed == 1  # picked up on the retry

    @respx.mock
    def test_an_html_page_served_as_200_is_not_treated_as_a_filing(self, db, tmp_path):
        add_snapshot(db, meta_row(Q3_URL, period="Quarterly", to_date="31-Dec-2024",
                                  broadcast="16-Jan-2025 20:20:21"),
                     period_type="Q", period_end="2024-12-31",
                     broadcast_at="2025-01-16T20:20:21", snap_id=1)
        respx.get(Q3_URL).mock(return_value=httpx.Response(200, content=b"<html><body>Blocked"))
        result = run(db, tmp_path)
        # a fetch failure: nothing stored, nothing parsed, retried next run, job degraded --
        # and the batch carries on rather than dying on one bad response
        assert result.transient_failures == 1 and result.parsed == 0
        assert rows(db, "SELECT COUNT(*) AS n FROM raw_artifacts")[0]["n"] == 0
        assert rows(db, "SELECT COUNT(*) AS n FROM fundamentals_parse_status")[0]["n"] == 0
        assert rows(db, "SELECT status FROM job_runs WHERE job_name='ingest_xbrl'")[0][
            "status"] == "degraded"

    @respx.mock
    def test_a_mislabelled_period_is_recorded_partial_and_stays_out_of_metrics(
        self, db, tmp_path
    ):
        # the filing says it ends 2024-09-30 but the document's OneD ends 2024-12-31
        add_snapshot(db, meta_row(Q3_URL, period="Quarterly", to_date="30-Sep-2024",
                                  broadcast="14-Oct-2024 19:32:45"),
                     period_type="Q", period_end="2024-09-30",
                     broadcast_at="2024-10-14T19:32:45", snap_id=1)
        respx.get(Q3_URL).mock(return_value=httpx.Response(200, content=Q3))
        result = run(db, tmp_path)
        assert result.partial == 1
        assert load_metric_frame(connect(db), lag_days=60).empty


class TestMetricsEndToEnd:
    @respx.mock
    def test_line_items_become_point_in_time_metric_rows(self, db, tmp_path):
        add_snapshot(db, meta_row(ANNUAL_URL, period="Annual", to_date="31-Mar-2024",
                                  broadcast="22-Apr-2024 19:47:12"),
                     period_type="FY", period_end="2024-03-31",
                     broadcast_at="2024-04-22T19:47:12", snap_id=1)
        respx.get(ANNUAL_URL).mock(return_value=httpx.Response(200, content=ANNUAL))
        run(db, tmp_path)

        frame = load_metric_frame(connect(db), lag_days=60)
        assert len(frame) == 1
        row = frame.iloc[0]
        assert row["symbol"] == "RELIANCE"
        # usable the day AFTER the (evening) broadcast, never on the period end
        assert row["available_on"].date().isoformat() == "2024-04-23"
        # D/E = (2,227,120 + 1,019,100) / 9,257,880 (Rs crore-scale figures from the real filing)
        assert row["de_ratio"] == pytest.approx(3_246_220_000_000 / 9_257_880_000_000)
        # one filing = one quarter known: no TTM, so ROCE and EPS TTM are None (not zero)
        assert pd.isna(row["roce"]) and pd.isna(row["eps_ttm"])
