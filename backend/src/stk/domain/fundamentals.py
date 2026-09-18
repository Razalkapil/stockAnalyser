"""Fundamentals: derived metrics from parsed filings, and the point-in-time join.

PURE. Filings arrive as ``FilingFacts`` (already parsed and unit-normalised
by ``stk.ingest.xbrl``); this module turns a company's history of them into
ROCE / D-E / CAGR / EPS-TTM rows, each stamped with the date it became
knowable, and joins those rows onto a daily panel WITHOUT look-ahead.

POINT-IN-TIME RULE. A filing is usable from ``available_on`` (its broadcast
date + 1 day -- filings often land after market close, so the next session
is the first that could act on it), never from its period end. The join is
``merge_asof(direction="backward")``: each bar sees the latest row whose
``available_on`` <= the bar's date, so a restated or later filing can only
ever affect later dates.

WHAT EACH METRIC NEEDS (and says when it cannot be computed -- None, never 0):
  eps_ttm / revenue_ttm / pat_ttm   4 consecutive discrete quarters
  roce = EBIT_ttm / (equity + borrowings)
                                    EBIT = PBT + finance costs; balance sheet
                                    from the latest filing that carried one
                                    (half-year and annual filings do)
  de_ratio = borrowings / equity
  sales_cagr3 / profit_cagr3        annual figures of FY t and FY t-3

Banks and non-Ind-AS filers are unsupported upstream, so they simply have
no rows -- their fundamentals conditions evaluate False, never spuriously true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise

import numpy as np
import pandas as pd

FUNDAMENTAL_COLUMNS = ("roce", "de_ratio", "sales_cagr3", "profit_cagr3", "eps_ttm")


@dataclass(frozen=True)
class FilingFacts:
    """The subset of one parsed filing the metrics need. ``None`` = not reported."""

    symbol: str
    basis: str  # "consolidated" | "standalone"
    period_end: date  # the discrete quarter's end (== filing toDate)
    is_annual: bool
    available_on: date
    quarter: dict[str, float] = field(default_factory=dict)  # revenue, pbt, finance_costs, pat, eps
    ytd: dict[str, float] = field(default_factory=dict)  # year-to-date / full-year (annual filing)
    instant: dict[str, float] = field(default_factory=dict)  # equity, borrowings_*


def _cagr(end: float | None, start: float | None, years: int) -> float | None:
    if end is None or start is None or start <= 0 or end <= 0:
        return None  # a CAGR off a non-positive base is meaningless, not zero
    return float((end / start) ** (1.0 / years) - 1.0)


def _borrowings(inst: dict[str, float]) -> float | None:
    parts = [inst.get("borrowings_noncurrent"), inst.get("borrowings_current")]
    known = [p for p in parts if p is not None]
    return float(sum(known)) if known else None


def _ttm(quarters: list[FilingFacts], item: str) -> float | None:
    """Sum of ``item`` over the 4 most recent quarters, if they are truly consecutive."""
    if len(quarters) < 4:
        return None
    last4 = quarters[-4:]
    for a, b in pairwise(last4):
        gap = (b.period_end - a.period_end).days
        if not 70 <= gap <= 110:  # ~one quarter apart; a hole means the TTM would be wrong
            return None
    values = [q.quarter.get(item) for q in last4]
    return None if any(v is None for v in values) else float(sum(values))  # type: ignore[arg-type]


def derive_metric_rows(filings: list[FilingFacts]) -> list[dict[str, object]]:
    """One row per filing, as known on its ``available_on``.

    ``filings`` must all be one company on ONE basis (the caller picks
    consolidated, else standalone). Each row only uses filings available on
    or before its own date, so the series is point-in-time.
    """
    ordered = sorted(filings, key=lambda f: (f.available_on, f.period_end))
    rows: list[dict[str, object]] = []
    for i, current in enumerate(ordered):
        known = ordered[: i + 1]
        quarters = sorted({f.period_end: f for f in known}.values(), key=lambda f: f.period_end)
        annual = sorted((f for f in known if f.is_annual), key=lambda f: f.period_end)
        balance = next((f for f in reversed(known) if f.instant.get("equity") is not None), None)

        pbt, fin = _ttm(quarters, "pbt"), _ttm(quarters, "finance_costs")
        borrowings = _borrowings(balance.instant) if balance else None
        equity = balance.instant.get("equity") if balance else None

        roce = None
        if pbt is not None and fin is not None and equity is not None and borrowings is not None:
            capital = equity + borrowings
            roce = (pbt + fin) / capital if capital > 0 else None
        de = borrowings / equity if borrowings is not None and equity and equity > 0 else None

        sales_cagr = profit_cagr = None
        if annual:
            latest = annual[-1]
            base = next((a for a in annual if abs((latest.period_end - a.period_end).days
                                                  - 3 * 365) <= 20), None)
            if base is not None:
                sales_cagr = _cagr(latest.ytd.get("revenue"), base.ytd.get("revenue"), 3)
                profit_cagr = _cagr(latest.ytd.get("pat"), base.ytd.get("pat"), 3)

        rows.append({
            "symbol": current.symbol,
            "available_on": pd.Timestamp(current.available_on),
            "period_end": pd.Timestamp(current.period_end),
            "roce": roce,
            "de_ratio": de,
            "sales_cagr3": sales_cagr,
            "profit_cagr3": profit_cagr,
            "eps_ttm": _ttm(quarters, "eps"),
        })
    return rows


def attach_fundamentals(frame: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """Join metric rows onto a daily panel as-of each bar's date. NO look-ahead.

    Adds ``roce, de_ratio, sales_cagr3, profit_cagr3, eps_ttm`` plus the
    derived ``pe_ttm`` (close_raw / eps_ttm, only where EPS > 0) and
    ``fund_age_days`` (days since the row in use became available).
    Bars before a symbol's first available filing get NaN, never a fill.
    """
    out = frame.copy()
    for col in (*FUNDAMENTAL_COLUMNS, "fund_age_days", "pe_ttm"):
        out[col] = np.nan
    if metrics.empty:
        return out

    # merge_asof refuses keys of different datetime RESOLUTIONS (parquet-loaded bars are
    # us/ms, freshly built metric rows are s/ns), so both are normalised to ns first.
    m = metrics.copy()
    m["available_on"] = pd.to_datetime(m["available_on"]).astype("datetime64[ns]")
    m = m.sort_values("available_on")
    left = out.drop(columns=[c for c in (*FUNDAMENTAL_COLUMNS, "fund_age_days", "pe_ttm")
                             if c in out.columns])
    left["date"] = pd.to_datetime(left["date"]).astype("datetime64[ns]")
    left = left.sort_values("date")
    joined = pd.merge_asof(
        left,
        m[["symbol", "available_on", *FUNDAMENTAL_COLUMNS]],
        left_on="date",
        right_on="available_on",
        by="symbol",
        direction="backward",
    )
    joined["fund_age_days"] = (joined["date"] - joined["available_on"]).dt.days.astype(float)
    eps = joined["eps_ttm"]
    joined["pe_ttm"] = (joined["close_raw"] / eps).where(eps > 0)
    return joined.drop(columns=["available_on"]).sort_values(["symbol", "date"]).reset_index(
        drop=True
    )


def available_on(broadcast: date | None, period_end: date, lag_days: int) -> tuple[date, bool]:
    """When a filing became usable, and whether that date is an ESTIMATE.

    A real broadcast date -> the next day (filings land after market close).
    No broadcast date -> ``period_end + lag_days`` and ``approximate=True``.
    """
    if broadcast is not None:
        return broadcast + timedelta(days=1), False
    return period_end + timedelta(days=lag_days), True
