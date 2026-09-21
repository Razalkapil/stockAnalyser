"""Classify traded symbols as company shares or funds (ETFs / mutual-fund units).

WHY THIS EXISTS. NSE's bhavcopy puts ETFs in the ordinary EQ series, indistinguishable from
stocks, and the security master does not list them. Found live: the first real scan recommended
GOLDETF, GOLDBEES and NEXT50IETF, and 348 of the 3,660 instruments in one day's file are funds.
A stock picker must not rank them, and a momentum backtest must not trade them.

THE SIGNAL is the ISIN prefix: ``INE`` = a company's securities, ``INF`` = funds (checked live:
all 348 INF rows in a UDiFF file were EQ-series ETFs / fund units, GOLDBEES and NIFTYBEES among
them). Only UDiFF carries ISINs (from 2024-07), so this reads that file; a symbol is classified
once and the row is kept even after the symbol stops trading.

KNOWN LIMIT: an ETF that delisted before the first UDiFF file ingested is not classified, so
history before then can still contain a few defunct funds. Re-run with an older ``--date`` to
widen it.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from stk.core.errors import DataNotPublished
from stk.ingest.jobs import JobSkipped, job_run
from stk.ingest.raw_store import persist_artifact
from stk.providers.base import SymbolChange
from stk.store.db.engine import connect, transaction

FUND_PREFIX = "INF"
EQUITY_PREFIX = "INE"


def classify_isin(isin: str | None) -> str | None:
    """'fund' / 'equity' / 'other', or None when there is no ISIN to judge by."""
    if not isin:
        return None
    if isin.startswith(FUND_PREFIX):
        return "fund"
    if isin.startswith(EQUITY_PREFIX):
        return "equity"
    return "other"


def ingest_instrument_classes(
    business_date: date, *, sqlite_path: Path, raw_root: Path, exchange: str = "NSE"
) -> int:
    """Classify every instrument in one day's UDiFF file. Returns rows written. Idempotent."""
    from stk.providers.registry import get_price_provider  # noqa: PLC0415

    conn = connect(sqlite_path)
    try:
        with job_run(conn, "ingest_instruments", business_date=business_date) as handle:
            provider = get_price_provider("nse_udiff")
            try:
                artifact = provider.fetch_eod(business_date, exchange)
            except DataNotPublished as exc:
                raise JobSkipped(str(exc)) from exc
            persist_artifact(raw_root, conn, artifact)

            now = datetime.now(UTC).isoformat()
            rows = []
            for bar in provider.parse_eod(artifact):
                cls = classify_isin(bar.isin)
                if cls is not None:
                    rows.append((exchange, bar.symbol, bar.isin, cls, business_date.isoformat(),
                                 now))
            with transaction(conn):
                conn.executemany(
                    """INSERT INTO instrument_class
                           (exchange, symbol, isin, class, source_date, updated_at)
                       VALUES (?,?,?,?,?,?)
                       ON CONFLICT(exchange, symbol) DO UPDATE SET
                           isin=excluded.isin, class=excluded.class,
                           source_date=excluded.source_date, updated_at=excluded.updated_at""",
                    rows)
            handle.rows_in = handle.rows_written = len(rows)
            handle.metrics = {"funds": sum(1 for r in rows if r[3] == "fund")}
            return len(rows)
    finally:
        conn.close()
    return 0  # unreachable: job_run either returns above or re-raises; JobSkipped is swallowed


def fund_symbols(conn: sqlite3.Connection, exchange: str) -> set[str]:
    return {r["symbol"] for r in conn.execute(
        "SELECT symbol FROM instrument_class WHERE exchange=? AND class='fund'", (exchange,))}


def classes_known(conn: sqlite3.Connection, exchange: str) -> bool:
    return conn.execute("SELECT 1 FROM instrument_class WHERE exchange=? LIMIT 1",
                        (exchange,)).fetchone() is not None


def require_instrument_classes(conn: sqlite3.Connection, exchange: str) -> None:
    """Refuse to run a scan/backtest whose universe would silently contain ETFs."""
    if not classes_known(conn, exchange):
        raise ValueError(
            f"no instrument classes for {exchange}: ETFs and other funds would be treated as "
            "stocks. Run `stk ingest instruments` first.")


def inherit_classes_from_renames(
    conn: sqlite3.Connection, changes: list[SymbolChange], *, now: str
) -> int:
    """Give an old symbol the class of the symbol it became. Returns rows added.

    Classes come from UDiFF, which exists only from 2024-07 and lists only what trades that day:
    an ETF renamed before then (ICICI500 -> BSE500IETF, NETFAUTO -> AUTOBEES) had no class, so
    its old-symbol bars sat in the STOCK universe of every backtest -- and its 10:1 unit splits
    read as 90% crashes. A symbol that already has a class (including one since reused by a
    different instrument) is never overwritten.
    """
    became = {(c.exchange, c.old_symbol): c.new_symbol for c in changes}
    known = {(str(r["exchange"]), str(r["symbol"])): r for r in conn.execute(
        "SELECT exchange, symbol, isin, class FROM instrument_class")}
    added = 0
    for (exchange, old), new in became.items():
        if (exchange, old) in known:
            continue
        current, hops = new, 0
        while (exchange, current) in became and hops < len(became):  # follow a chain to today
            current, hops = became[(exchange, current)], hops + 1
        source = known.get((exchange, current))
        if source is None:
            continue
        conn.execute(
            "INSERT INTO instrument_class (exchange, symbol, isin, class, source_date, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (exchange, old, source["isin"], source["class"], f"renamed-to:{current}", now),
        )
        added += 1
    return added
