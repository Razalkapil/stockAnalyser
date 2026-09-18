#!/usr/bin/env python3
"""Phase-0 history spike: how far back does sec_bhavdata_full actually go?

Per docs/adr/0003-historical-price-source.md. Probes ten dates spanning
2010-2024 against nsearchives.nseindia.com/products/content/sec_bhavdata_full_*.csv
and reports status/content-type/row-count for each, so the ADR can be
updated with a real answer instead of a provisional guess.

Run: uv run python scripts/spikes/history_probe.py
"""

from __future__ import annotations

import sys
from datetime import date

import httpx

PROBE_DATES = [
    date(2010, 1, 4),
    date(2012, 6, 15),
    date(2014, 11, 20),
    date(2016, 3, 10),
    date(2018, 8, 22),
    date(2020, 3, 23),  # covid circuit-breaker day
    date(2021, 7, 1),
    date(2023, 2, 15),
    date(2024, 6, 14),
    date(2024, 7, 10),
]

URL_TEMPLATE = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
UA = "stk/0.1 (+personal research tool)"


def probe(d: date) -> dict:
    url = URL_TEMPLATE.format(d=d.strftime("%d%m%Y"))
    try:
        resp = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
    except httpx.HTTPError as exc:
        return {"date": d, "url": url, "error": str(exc)}

    body = resp.content
    first_line = body.decode("utf-8", errors="replace").splitlines()[0] if body else ""
    row_count = max(0, body.decode("utf-8", errors="replace").count("\n") - 1) if body else 0
    looks_valid = "SYMBOL" in first_line

    return {
        "date": d,
        "url": url,
        "status": resp.status_code,
        "content_type": resp.headers.get("content-type"),
        "bytes": len(body),
        "row_count": row_count,
        "looks_valid": looks_valid,
        "first_line": first_line[:80],
    }


def main() -> int:
    results = [probe(d) for d in PROBE_DATES]

    print(f"{'date':<12} {'status':<7} {'bytes':<8} {'rows':<7} {'valid':<6} content-type")
    print("-" * 80)
    valid_count = 0
    for r in results:
        if "error" in r:
            print(f"{r['date']} ERROR: {r['error']}")
            continue
        valid = "YES" if r["looks_valid"] else "no"
        if r["looks_valid"]:
            valid_count += 1
        print(
            f"{r['date']!s:<12} {r['status']:<7} {r['bytes']:<8} {r['row_count']:<7} "
            f"{valid:<6} {r['content_type']}"
        )

    print()
    print(f"{valid_count}/{len(PROBE_DATES)} probe dates returned a valid-looking CSV.")

    earliest_valid = min(
        (r["date"] for r in results if r.get("looks_valid")), default=None
    )
    latest_invalid = max(
        (r["date"] for r in results if not r.get("looks_valid") and "error" not in r), default=None
    )
    print(f"Earliest valid date in probe set: {earliest_valid}")
    print(f"Latest invalid date in probe set: {latest_invalid}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
