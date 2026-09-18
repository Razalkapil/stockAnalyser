"""Security-master ingest: ISIN-keyed merge of NSE + BSE listings into
`securities`/`listings`/`symbol_history`.

ISIN is the only reliable cross-exchange identity (symbols and company
names both differ across exchanges) -- see the build plan's "ISIN
dedup / NSE-preferred merge" section. Algorithm, run inside one
job_run() scope:

  1. Fetch both exchanges' master snapshots (skip an exchange whose
     fetch fails loudly rather than aborting the whole run -- see
     ingest_security_master's docstring).
  2. Group MasterRecords by ISIN. A blank ISIN is real (BSE has some)
     and is skipped by the provider adapters themselves, not here.
  3. For each ISIN: upsert ONE `securities` row (insert if new; if
     existing, refresh company_name/last_seen_on/updated_at and
     reactivate status=ACTIVE -- a security that stopped appearing and
     has now reappeared is not something this pass needs to treat
     specially). `primary_exchange` prefers NSE when an NSE listing
     exists for this ISIN, else BSE.
  4. For each (exchange, symbol, series) MasterRecord under that ISIN,
     upsert one `listings` row. If an existing ACTIVE listing for the
     same (security_id, exchange) has a DIFFERENT symbol than this
     one, that is a rename: the old listing is marked INACTIVE and
     `symbol_history` records the transition (closing the old row's
     valid_to, opening a new row for the new symbol) -- so historical
     bars keyed by the old symbol still resolve.

KNOWN, DEFERRED LIMITATION: suspension/delisting detection ("absent
from N consecutive snapshots -> SUSPENDED after 1, DELISTED after 20",
per the build plan) is NOT implemented here -- it requires tracking
absence across many runs over time, which this single-pass merge
cannot safely infer from one snapshot alone without additional
tracking infrastructure this phase does not yet have. A security
missing from today's snapshot is simply left at its previous status,
never silently flipped. This is a documented gap, not an oversight.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from stk.core.errors import ProviderError
from stk.ingest.jobs import job_run
from stk.providers.base import MasterRecord
from stk.providers.registry import get_security_master_provider
from stk.store.db.engine import connect, transaction


class MasterIngestResult:
    def __init__(self, securities_upserted: int, listings_upserted: int, renames: int) -> None:
        self.securities_upserted = securities_upserted
        self.listings_upserted = listings_upserted
        self.renames = renames


def _fetch_all_records(exchanges: list[str]) -> list[MasterRecord]:
    """Fetch every exchange's master snapshot, tolerating one exchange's
    fetch failing without losing the other -- mirrors ingest.daily's
    per-exchange isolation, since a BSE API outage must not block an
    NSE-only refresh."""
    provider_by_exchange = {"NSE": "nse_equity_l", "BSE": "bse_scrip_api"}
    records: list[MasterRecord] = []
    errors: list[str] = []
    for exchange in exchanges:
        provider_name = provider_by_exchange.get(exchange)
        if provider_name is None:
            continue
        try:
            provider = get_security_master_provider(provider_name)
            records.extend(provider.fetch_master())
        except ProviderError as exc:
            errors.append(f"{exchange} ({provider_name}): {exc}")
    if errors and not records:
        raise ProviderError(f"all security-master fetches failed: {'; '.join(errors)}")
    return records


def _upsert_security(
    conn: sqlite3.Connection, isin: str, by_isin: list[MasterRecord], now: str
) -> int:
    nse_record = next((r for r in by_isin if r.exchange == "NSE"), None)
    preferred = nse_record or by_isin[0]

    existing = conn.execute(
        "SELECT security_id FROM securities WHERE isin=?", (isin,)
    ).fetchone()
    if existing is None:
        cursor = conn.execute(
            """INSERT INTO securities
               (isin, canonical_symbol, company_name, primary_exchange, face_value,
                status, first_seen_on, last_seen_on, updated_at)
               VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)""",
            (
                isin, preferred.symbol, preferred.company_name, preferred.exchange,
                float(preferred.face_value) if preferred.face_value is not None else None,
                now, now, now,
            ),
        )
        return int(cursor.lastrowid)  # type: ignore[arg-type]

    security_id = existing["security_id"]
    conn.execute(
        """UPDATE securities
           SET company_name=?, status='ACTIVE', last_seen_on=?, updated_at=?
           WHERE security_id=?""",
        (preferred.company_name, now, now, security_id),
    )
    return int(security_id)


def _upsert_listing_and_detect_rename(
    conn: sqlite3.Connection, security_id: int, record: MasterRecord, now: str
) -> bool:
    """Returns True if this upsert closed out a rename (a different
    symbol was previously active for this security on this exchange)."""
    prior_active = conn.execute(
        """SELECT listing_id, symbol FROM listings
           WHERE security_id=? AND exchange=? AND status='ACTIVE' AND symbol != ?""",
        (security_id, record.exchange, record.symbol),
    ).fetchone()

    renamed = prior_active is not None
    if prior_active is not None:
        conn.execute(
            "UPDATE listings SET status='INACTIVE', updated_at=? WHERE listing_id=?",
            (now, prior_active["listing_id"]),
        )
        conn.execute(
            """UPDATE symbol_history SET valid_to=?
               WHERE exchange=? AND symbol=? AND valid_to IS NULL""",
            (now, record.exchange, prior_active["symbol"]),
        )

    conn.execute(
        """INSERT INTO listings
               (security_id, exchange, symbol, exchange_token, series, listing_date,
                lot_size, status, source, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
           ON CONFLICT (exchange, symbol, series) DO UPDATE SET
               exchange_token=excluded.exchange_token,
               listing_date=excluded.listing_date,
               lot_size=excluded.lot_size,
               status='ACTIVE',
               updated_at=excluded.updated_at""",
        (
            security_id, record.exchange, record.symbol, record.exchange_token,
            record.series, record.listing_date.isoformat() if record.listing_date else None,
            record.lot_size, f"master:{record.exchange.lower()}", now,
        ),
    )

    already_tracked = conn.execute(
        "SELECT 1 FROM symbol_history WHERE exchange=? AND symbol=?",
        (record.exchange, record.symbol),
    ).fetchone()
    if already_tracked is None:
        # First time this (exchange, symbol) has ever been seen -- open
        # its symbol_history row now. On a plain re-run with no rename,
        # this row already exists and nothing is inserted, keeping
        # repeated runs idempotent (no accumulating duplicate rows).
        conn.execute(
            """INSERT INTO symbol_history (security_id, exchange, symbol, valid_from)
               VALUES (?, ?, ?, ?)""",
            (security_id, record.exchange, record.symbol, now),
        )

    return renamed


def ingest_security_master(
    *, sqlite_path: Path, exchanges: list[str] | None = None
) -> MasterIngestResult:
    """Fetch and merge the NSE + BSE security masters into securities/
    listings/symbol_history, keyed on ISIN. Safe to re-run -- every
    write here is an upsert keyed on a stable natural key (isin, or
    (exchange, symbol, series)), never a blind insert.
    """
    exchanges = exchanges or ["NSE", "BSE"]
    conn = connect(sqlite_path)
    try:
        with job_run(conn, "ingest_security_master") as handle:
            records = _fetch_all_records(exchanges)

            by_isin: dict[str, list[MasterRecord]] = defaultdict(list)
            for record in records:
                by_isin[record.isin].append(record)

            now = datetime.now(UTC).isoformat()
            securities_upserted = 0
            listings_upserted = 0
            renames = 0

            with transaction(conn):
                for isin, group in by_isin.items():
                    security_id = _upsert_security(conn, isin, group, now)
                    securities_upserted += 1
                    for record in group:
                        if _upsert_listing_and_detect_rename(conn, security_id, record, now):
                            renames += 1
                        listings_upserted += 1

            handle.rows_in = len(records)
            handle.rows_written = securities_upserted
            handle.metrics["listings_upserted"] = listings_upserted
            handle.metrics["renames"] = renames

        return MasterIngestResult(securities_upserted, listings_upserted, renames)
    finally:
        conn.close()
