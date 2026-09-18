"""Turn stored XBRL line items into point-in-time fundamental metric rows.

Reads ``fundamentals_line_items`` (via the parse-status ledger), assembles
one ``FilingFacts`` per filing, and hands each company's history to the pure
``stk.domain.fundamentals.derive_metric_rows``.

ONLY ``parsed`` filings feed metrics. A ``partial`` one failed a sanity check
(a suspected scale slip, a period mismatch, a missing required item); using
numbers we already suspect is worse than a gap, so they are excluded here and
stay visible in ``fundamentals_parse_status`` for ``stk doctor`` to count.

BASIS. A company that files consolidated results is measured on those; only a
company with no consolidated filings falls back to standalone. Mixing the two
inside one series would make a CAGR compare unlike things.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime

import pandas as pd

from stk.domain.fundamentals import FilingFacts, available_on, derive_metric_rows

_QUERY = """
SELECT s.snapshot_id, s.security_id, s.period_type, s.period_end, s.consolidated,
       s.broadcast_at, s.data_json, li.period_kind, li.item, li.value
FROM fundamentals_snapshots s
JOIN fundamentals_parse_status p ON p.snapshot_id = s.snapshot_id AND p.status = 'parsed'
JOIN fundamentals_line_items li ON li.snapshot_id = s.snapshot_id
"""

METRIC_COLUMNS = ["symbol", "available_on", "period_end", "roce", "de_ratio",
                  "sales_cagr3", "profit_cagr3", "eps_ttm"]


def load_filing_facts(conn: sqlite3.Connection, lag_days: int) -> list[FilingFacts]:
    grouped: dict[int, dict] = {}
    for row in conn.execute(_QUERY):
        entry = grouped.setdefault(row["snapshot_id"], {"row": row, "items": defaultdict(dict)})
        entry["items"][row["period_kind"]][row["item"]] = row["value"]

    filings: list[FilingFacts] = []
    for entry in grouped.values():
        row = entry["row"]
        meta = json.loads(row["data_json"])
        symbol = (meta.get("symbol") or "").strip()
        if not symbol:
            continue
        broadcast = (
            datetime.fromisoformat(row["broadcast_at"]).date() if row["broadcast_at"] else None
        )
        period_end = datetime.fromisoformat(row["period_end"]).date()
        avail, _approx = available_on(broadcast, period_end, lag_days)
        filings.append(
            FilingFacts(
                symbol=symbol,
                basis="consolidated" if row["consolidated"] else "standalone",
                period_end=period_end,
                is_annual=row["period_type"] == "FY",
                available_on=avail,
                quarter=dict(entry["items"].get("quarter", {})),
                ytd=dict(entry["items"].get("ytd", {})),
                instant=dict(entry["items"].get("instant", {})),
            )
        )
    return filings


def load_metric_frame(conn: sqlite3.Connection, lag_days: int) -> pd.DataFrame:
    """One row per (symbol, filing), point-in-time, on each company's preferred basis."""
    by_symbol: dict[str, dict[str, list[FilingFacts]]] = defaultdict(lambda: defaultdict(list))
    for f in load_filing_facts(conn, lag_days):
        by_symbol[f.symbol][f.basis].append(f)

    rows: list[dict[str, object]] = []
    for bases in by_symbol.values():
        chosen = bases.get("consolidated") or bases.get("standalone") or []
        rows.extend(derive_metric_rows(chosen))
    if not rows:
        return pd.DataFrame(columns=METRIC_COLUMNS)
    return pd.DataFrame(rows)[METRIC_COLUMNS]
