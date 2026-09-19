"""XBRL parsing against REAL NSE filings, plus the hostile inputs a parser must refuse."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from stk.ingest.xbrl import MAX_BYTES, XbrlError, parse_xbrl

FIXTURES = Path(__file__).parent.parent / "fixtures" / "nse" / "xbrl"
REPO = Path(__file__).parent.parent.parent
TAGS = yaml.safe_load((REPO / "config" / "xbrl_tags.yaml").read_text())
Q3 = (FIXTURES / "INDAS_reliance_q3fy25_consolidated.xml").read_bytes()
ANNUAL = (FIXTURES / "INDAS_reliance_fy24_annual_consolidated.xml").read_bytes()


class TestRealQuarterlyFiling:
    """Reliance Q3 FY25 (Oct-Dec 2024), consolidated."""

    def test_parses_cleanly(self):
        r = parse_xbrl(Q3, TAGS, expected_period_end=date(2024, 12, 31))
        assert r.status == "parsed", r.detail

    def test_oneD_is_the_discrete_quarter(self):
        r = parse_xbrl(Q3, TAGS)
        assert r.get("quarter", "revenue") == 1_282_600_000_000.0
        assert r.get("quarter", "pbt") == 115_970_000_000.0
        assert r.get("quarter", "pat") == 87_210_000_000.0
        assert r.get("quarter", "eps") == 6.44

    def test_fourD_is_year_to_date_even_though_it_PRINTS_the_quarters_dates(self):
        """The trap: FourD declares identical start/end dates to OneD but its values are
        cumulative. Taking meaning from the dates would store nine months as a quarter."""
        r = parse_xbrl(Q3, TAGS)
        assert r.get("ytd", "revenue") == 3_966_450_000_000.0
        assert r.get("ytd", "revenue") > 3 * r.get("quarter", "revenue")

    def test_a_quarterly_filing_has_no_balance_sheet_and_says_so(self):
        r = parse_xbrl(Q3, TAGS)
        assert r.kind_values("instant") == {}  # absent, NOT zero
        assert r.get("instant", "equity") is None

    def test_quarter_dates_are_read_from_the_context(self):
        r = parse_xbrl(Q3, TAGS)
        assert (r.quarter_start, r.quarter_end) == (date(2024, 10, 1), date(2024, 12, 31))

    def test_the_unreliable_debt_equity_field_is_never_used(self):
        r = parse_xbrl(Q3, TAGS)
        assert not any("debt" in item for (_, item) in r.facts)


class TestRealAnnualFiling:
    """Reliance FY24 (Apr 2023 - Mar 2024), consolidated."""

    def test_parses_cleanly(self):
        assert parse_xbrl(ANNUAL, TAGS, expected_period_end=date(2024, 3, 31)).status == "parsed"

    def test_carries_q4_as_the_quarter_and_the_year_as_ytd(self):
        r = parse_xbrl(ANNUAL, TAGS)
        assert r.get("quarter", "revenue") == 2_407_150_000_000.0  # Q4 FY24
        assert r.get("ytd", "revenue") == 9_144_720_000_000.0  # full FY24
        assert r.get("ytd", "pat") == 790_200_000_000.0

    def test_balance_sheet_items(self):
        r = parse_xbrl(ANNUAL, TAGS)
        assert r.get("instant", "equity") == 9_257_880_000_000.0
        assert r.get("instant", "borrowings_noncurrent") == 2_227_120_000_000.0
        assert r.get("instant", "borrowings_current") == 1_019_100_000_000.0
        assert r.get("instant", "total_assets") == 17_559_860_000_000.0

    def test_every_value_records_its_source_element_and_unit(self):
        r = parse_xbrl(ANNUAL, TAGS)
        _value, tag, unit = r.facts[("instant", "equity")]
        assert (tag, unit) == ("Equity", "INR")


class TestFailingLoudly:
    def test_wrong_expected_period_end_makes_it_partial_not_parsed(self):
        r = parse_xbrl(Q3, TAGS, expected_period_end=date(2024, 9, 30))
        assert r.status == "partial"
        assert any("OneD ends" in p for p in r.detail["problems"])

    def test_a_scale_slip_is_caught_by_the_eps_times_shares_check(self):
        broken = Q3.replace(b">6.44<", b">6440.00<")  # EPS x1000, every EPS element
        r = parse_xbrl(broken, TAGS)
        assert r.status == "partial"
        assert any("eps x shares" in p for p in r.detail["problems"])

    def test_missing_required_items_are_reported_never_zero_filled(self):
        r = parse_xbrl(Q3.replace(b"RevenueFromOperations", b"SomethingElseEntirely"), TAGS)
        assert r.status == "partial"
        assert r.get("quarter", "revenue") is None
        assert any("missing required items" in p and "revenue" in p for p in r.detail["problems"])

    def test_an_unrecognised_template_is_unsupported_with_no_facts(self):
        """A bank's filing (different taxonomy) or an older template has none of the
        expected plain contexts. Record that -- do not guess."""
        doc = (b'<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
               b'<xbrli:context id="Weird"><xbrli:entity/><xbrli:period>'
               b'<xbrli:instant>2024-03-31</xbrli:instant></xbrli:period></xbrli:context>'
               b"</xbrli:xbrl>")
        r = parse_xbrl(doc, TAGS)
        assert r.status == "unsupported_format"
        assert r.facts == {}

    @pytest.mark.parametrize(
        "payload", [b"", b"<not-closed", b"plain text", b"<html><body/></html>"]
    )
    def test_garbage_is_an_error(self, payload):
        with pytest.raises(XbrlError):
            parse_xbrl(payload, TAGS)

    def test_entity_declarations_are_refused(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
        with pytest.raises(XbrlError, match="entities"):
            parse_xbrl(bomb, TAGS)

    def test_oversized_documents_are_refused(self):
        with pytest.raises(XbrlError, match="over the"):
            parse_xbrl(b"<x>" + b"a" * MAX_BYTES + b"</x>", TAGS)


class TestScaleSanityCheck:
    """EPS x shares vs PAT catches unit slips, not honest accounting differences."""

    def _with_eps(self, factor: float) -> bytes:
        text = Q3.decode()
        m = re.search(r'(<in-bse-fin:BasicEarningsLossPerShareFromContinuingAndDiscontinued'
                      r'Operations[^>]*contextRef="OneD"[^>]*>)([^<]+)(<)', text)
        assert m, "fixture has no OneD EPS"
        return text.replace(m.group(0), f"{m.group(1)}{float(m.group(2)) * factor}{m.group(3)}"
                            ).encode()

    def test_the_real_filing_is_clean(self):
        assert parse_xbrl(Q3, TAGS).status == "parsed"

    @pytest.mark.parametrize("factor", [1.4, 0.6, 3.0, 8.0, 0.15])
    def test_honest_differences_within_an_order_of_magnitude_pass(self, factor):
        assert parse_xbrl(self._with_eps(factor), TAGS).status == "parsed"

    @pytest.mark.parametrize("factor", [100.0, 1e5, 1e7, 0.001])
    def test_a_unit_slip_is_partial_and_says_so(self, factor):
        r = parse_xbrl(self._with_eps(factor), TAGS)
        assert r.status == "partial" and "eps x shares" in str(r.detail["problems"])

    def test_a_sign_disagreement_is_not_a_scale_problem(self):
        assert parse_xbrl(self._with_eps(-1.0), TAGS).status == "parsed"


class TestOtherPnlTemplates:
    def test_a_filing_with_none_of_revenue_pbt_pat_is_unsupported_not_partial(self):
        text = Q3.decode()
        for tag in ("RevenueFromOperations", "ProfitBeforeTax", "ProfitLossForPeriod",
                    "Revenue", "ProfitLossFromOrdinaryActivitiesBeforeTax"):
            # both the opening and the closing tag, or the document is no longer well-formed
            text = re.sub(rf"in-bse-fin:{tag}(?=[ >])", f"in-bse-fin:Renamed{tag}", text)
        r = parse_xbrl(text.encode(), TAGS)
        assert r.status == "unsupported_format" and r.facts == {}
        assert "different P&L template" in str(r.detail["reason"])

    def test_one_missing_item_is_still_a_damaged_filing_not_a_different_template(self):
        r = parse_xbrl(Q3.replace(b"RevenueFromOperations", b"SomethingElseEntirely"), TAGS)
        assert r.status == "partial"
