"""Parse an NSE Ind-AS XBRL filing into normalised line items.

WHAT THE REAL FILINGS LOOK LIKE (verified 2026-09-19 against Reliance Q3 FY25
and FY24 annual, consolidated; fixtures in tests/fixtures/nse/xbrl/):

  The template defines a handful of context IDs with NO dimensional scenario:
    OneD   the current period -- the DISCRETE QUARTER
    FourD  the cumulative period -- year-to-date (the FULL YEAR in an annual filing)
    OneI   the instant at period end -- the balance sheet
  Every other context carries a <scenario> (segments, notes) and is ignored.

  THE PRINTED DATES ON FourD CANNOT BE TRUSTED. In both filings FourD declares
  exactly the same start/end dates as OneD, yet its values are the cumulative
  ones (Reliance Q3 FY25: OneD revenue 1.28 trn vs FourD 3.97 trn; annual FY24:
  OneD 2.41 trn = Q4, FourD 9.14 trn = the year). So meaning is taken from the
  context ID and the dates are only used to sanity-check OneD against the
  filing's own period (toDate).

  Consequences worth knowing:
    * each filing's OneD is already a discrete quarter -- trailing-twelve-month
      sums need no "FY minus nine months" derivation;
    * quarterly filings carry NO balance sheet; half-year and annual ones do;
    * `DebtEquityRatio` reads 0.00 for a heavily indebted company, so it is
      never used (config/xbrl_tags.yaml says so).

FAILING LOUDLY. A filing whose expected contexts are absent is
``unsupported_format`` (banks use a different taxonomy; older filings a
different template) -- recorded as such, with NO line items, never guessed at.
A sanity-check miss (EPS x shares vs PAT) makes the result ``partial`` and is
recorded in the detail; it does not silently pass. Missing required items are
never stored as zero.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

PARSER_VERSION = 1
MAX_BYTES = 8 * 1024 * 1024
NS_XBRLI = "http://www.xbrl.org/2003/instance"

CTX_QUARTER = "OneD"
CTX_YTD = "FourD"
CTX_INSTANT = "OneI"
PERIOD_KINDS = {CTX_QUARTER: "quarter", CTX_YTD: "ytd", CTX_INSTANT: "instant"}

# Items a filing must yield for its result to count as fully parsed.
REQUIRED_FLOW = ("revenue", "pbt", "pat")


class XbrlError(ValueError):
    """The document is not parseable XBRL at all (malformed, hostile or oversized)."""


@dataclass
class XbrlFacts:
    status: str  # parsed | partial | unsupported_format
    #: (period_kind, item) -> (value, source element local name, unit)
    facts: dict[tuple[str, str], tuple[float, str, str]] = field(default_factory=dict)
    quarter_start: date | None = None
    quarter_end: date | None = None
    detail: dict[str, object] = field(default_factory=dict)

    def get(self, kind: str, item: str) -> float | None:
        hit = self.facts.get((kind, item))
        return hit[0] if hit else None

    def kind_values(self, kind: str) -> dict[str, float]:
        return {item: v[0] for (k, item), v in self.facts.items() if k == kind}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_date(text: str | None) -> date | None:
    try:
        return date.fromisoformat((text or "").strip()[:10])
    except ValueError:
        return None


def _plain_contexts(root: ET.Element) -> dict[str, tuple[date | None, date | None]]:
    """context id -> (start, end) for contexts with no scenario/segment dimension."""
    plain: dict[str, tuple[date | None, date | None]] = {}
    for ctx in root.findall(f"{{{NS_XBRLI}}}context"):
        entity_or_scenario = ctx.find(f"{{{NS_XBRLI}}}scenario")
        segment = ctx.find(f"{{{NS_XBRLI}}}entity/{{{NS_XBRLI}}}segment")
        if entity_or_scenario is not None or segment is not None:
            continue
        period = ctx.find(f"{{{NS_XBRLI}}}period")
        if period is None:
            continue
        start = _parse_date(getattr(period.find(f"{{{NS_XBRLI}}}startDate"), "text", None))
        end = _parse_date(getattr(period.find(f"{{{NS_XBRLI}}}endDate"), "text", None)
                          or getattr(period.find(f"{{{NS_XBRLI}}}instant"), "text", None))
        plain[ctx.get("id", "")] = (start, end)
    return plain


def _to_float(text: str | None) -> float | None:
    if text is None or not text.strip():
        return None
    try:
        return float(Decimal(text.strip()))
    except InvalidOperation:
        return None


def _index_facts(root: ET.Element, wanted_contexts: set[str]) -> dict[tuple[str, str], ET.Element]:
    """(context id, element local name) -> element, for plain-context numeric facts."""
    found: dict[tuple[str, str], ET.Element] = {}
    for el in root:
        if el.tag.startswith(f"{{{NS_XBRLI}}}"):
            continue
        ctx = el.get("contextRef")
        if ctx in wanted_contexts and el.get("unitRef") is not None:
            found.setdefault((ctx, _local(el.tag)), el)
    return found


#: EPS x shares vs PAT is a SCALE detector (rupees vs thousands vs crore, or a stray multiplier),
#: not an accounting identity. Real filings legitimately miss it by tens of percent -- paid-up
#: capital is not the weighted-average share count, PAT includes minority interest and preference
#: dividends -- so a tight band (the first version used 0.75-1.25) rejected ~8% of real filings.
#: Seen live: honest filings at 1.3-1.5x (and 5.7x); true slips at 1e5x and 1e7x.
SCALE_SLIP_FACTOR = 10.0


def _sanity(facts: XbrlFacts) -> list[str]:
    """EPS x share count should be the same ORDER OF MAGNITUDE as PAT; a miss of more than
    ``SCALE_SLIP_FACTOR`` either way means a unit/scale slip. A sign disagreement is not a scale
    problem (discontinued operations, a loss attributed against a profit) and passes."""
    problems: list[str] = []
    eps = facts.get("quarter", "eps")
    paid, face = facts.get("quarter", "paid_up_capital"), facts.get("quarter", "face_value")
    pat = facts.get("quarter", "pat_owners") or facts.get("quarter", "pat")
    if eps is not None and paid and face and pat:
        implied = eps * (paid / face)
        ratio = implied / pat if pat != 0 else 1.0
        if implied != 0 and ratio > 0 and not 1 / SCALE_SLIP_FACTOR <= ratio <= SCALE_SLIP_FACTOR:
            problems.append(
                f"eps x shares = {implied:,.0f} vs pat = {pat:,.0f} (ratio {implied / pat:.2f})"
            )
    return problems


def parse_xbrl(
    content: bytes,
    tag_map: dict[str, dict[str, list[str]]],
    *,
    expected_period_end: date | None = None,
) -> XbrlFacts:
    """Parse one filing. ``tag_map`` is config/xbrl_tags.yaml (``flow``/``instant``)."""
    if len(content) > MAX_BYTES:
        raise XbrlError(f"document is {len(content):,} bytes, over the {MAX_BYTES:,} limit")
    if b"<!ENTITY" in content:
        # Entity declarations are how XML bombs are built; a filing never needs one.
        raise XbrlError("document declares XML entities; refusing to parse")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise XbrlError(f"not well-formed XML: {exc}") from exc
    if _local(root.tag) != "xbrl":
        raise XbrlError(f"root element is {_local(root.tag)!r}, not xbrl")

    contexts = _plain_contexts(root)
    present = {c for c in (CTX_QUARTER, CTX_YTD, CTX_INSTANT) if c in contexts}
    out = XbrlFacts(status="unsupported_format")
    if CTX_QUARTER not in present and CTX_INSTANT not in present:
        out.detail["reason"] = (
            f"expected plain contexts {CTX_QUARTER}/{CTX_INSTANT}, found {sorted(contexts)[:6]}"
        )
        return out

    out.quarter_start, out.quarter_end = contexts.get(CTX_QUARTER, (None, None))
    indexed = _index_facts(root, present)

    def take(ctx: str, item: str, candidates: list[str]) -> None:
        for name in candidates:
            el = indexed.get((ctx, name))
            value = _to_float(el.text) if el is not None else None
            if el is not None and value is not None:
                out.facts[(PERIOD_KINDS[ctx], item)] = (value, name, el.get("unitRef", ""))
                return

    for item, candidates in tag_map.get("flow", {}).items():
        take(CTX_QUARTER, item, candidates)
        take(CTX_YTD, item, candidates)
    for item, candidates in tag_map.get("instant", {}).items():
        take(CTX_INSTANT, item, candidates)

    problems: list[str] = []
    missing = [i for i in REQUIRED_FLOW if ("quarter", i) not in out.facts]
    if missing:
        problems.append(f"missing required items: {missing}")
    if (
        expected_period_end is not None
        and out.quarter_end is not None
        and out.quarter_end != expected_period_end
    ):
        problems.append(
            f"OneD ends {out.quarter_end}, filing says {expected_period_end}"
        )
    problems += _sanity(out)

    if len(missing) == len(REQUIRED_FLOW):
        # Not one of revenue / pbt / pat exists: this is not a damaged Ind-AS filing but a
        # different profit-and-loss template (banks and insurers report InterestEarned, premiums,
        # ...). Say so, and store nothing -- never guess a mapping for them.
        out.status = "unsupported_format"
        out.facts.clear()
        out.detail["reason"] = "no revenue, pbt or pat: a different P&L template (bank / insurer)"
        return out
    out.status = "partial" if problems else "parsed"
    out.detail["problems"] = problems
    out.detail["contexts_present"] = sorted(present)
    return out
