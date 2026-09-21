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

SUSPENSION / DELISTING (added after the first version deferred it): every SUCCESSFUL snapshot
of an exchange increments ``listings.missed_snapshots`` for each active listing of that exchange
that is absent, and resets it for those present. A security's status follows the smallest miss
count across its active listings (present on either exchange = not gone):
``domain.universe.lifecycle_status`` -> ACTIVE / SUSPENDED / DELISTED, thresholds in
config/universe.yaml. Two safeguards, both because absence is only a heuristic: an exchange whose
fetch FAILED is not counted at all (an outage is not a delisting), and a snapshot missing more than
``max_absent_fraction`` of that exchange's listings is treated as broken -- nothing is counted and
the run is marked degraded. Reappearing resets everything (the upsert reactivates the security).
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel

from stk.config.universe import LifecycleConfig, load_universe_config
from stk.core.errors import ProviderError
from stk.core.time import today_ist
from stk.domain.universe import lifecycle_status
from stk.ingest.instruments import inherit_classes_from_renames
from stk.ingest.jobs import job_run
from stk.ingest.raw_store import persist_artifact
from stk.providers.base import MasterRecord, SymbolChange
from stk.providers.registry import get_security_master_provider
from stk.store.db.engine import connect, transaction


class MasterIngestResult:
    def __init__(self, securities_upserted: int, listings_upserted: int, renames: int, *,
                 suspended: int = 0, delisted: int = 0, degraded: bool = False) -> None:
        self.securities_upserted = securities_upserted
        self.listings_upserted = listings_upserted
        self.renames = renames
        self.suspended = suspended  # securities that ENTERED suspended this run
        self.delisted = delisted  # securities that ENTERED delisted this run
        self.degraded = degraded  # a snapshot looked broken and absences were not counted


def _update_lifecycle(
    conn: sqlite3.Connection, records: list[MasterRecord], fetched: set[str],
    *, cfg: LifecycleConfig, now: str, today: date,
) -> tuple[int, int, list[str]]:
    """Count absences for successfully fetched exchanges and move securities between statuses.

    Returns (newly_suspended, newly_delisted, exchanges_skipped_as_broken)."""
    broken: list[str] = []
    for exchange in sorted(fetched):
        present = {(r.symbol, r.series) for r in records if r.exchange == exchange}
        active = conn.execute(
            "SELECT listing_id, symbol, series, missed_snapshots, missed_counted_on FROM listings "
            "WHERE exchange=? AND status='ACTIVE'", (exchange,)).fetchall()
        if not active:
            continue
        absent = [r["listing_id"] for r in active if (r["symbol"], r["series"]) not in present]
        if len(absent) / len(active) > cfg.max_absent_fraction:
            broken.append(f"{exchange}: {len(absent)}/{len(active)} listings absent")
            continue  # a broken snapshot is not evidence of anything
        back = [(r["listing_id"],) for r in active
                if (r["symbol"], r["series"]) in present and r["missed_snapshots"]]
        conn.executemany("UPDATE listings SET missed_snapshots=0 WHERE listing_id=?", back)
        # At most one increment per listing per calendar day: re-running the ingest (always safe)
        # must not count one absence twice.
        stamp = today.isoformat()
        fresh = [(stamp, r["listing_id"]) for r in active
                 if r["listing_id"] in set(absent) and r["missed_counted_on"] != stamp]
        conn.executemany(
            "UPDATE listings SET missed_snapshots = missed_snapshots + 1, missed_counted_on=? "
            "WHERE listing_id=?", fresh)

    suspended = delisted = 0
    for row in conn.execute(
        """SELECT s.security_id, s.status, MIN(l.missed_snapshots) AS missed
           FROM securities s JOIN listings l ON l.security_id = s.security_id
           WHERE l.status='ACTIVE' GROUP BY s.security_id"""
    ).fetchall():
        new = lifecycle_status(row["missed"], suspend_after=cfg.suspend_after_missed,
                               delist_after=cfg.delist_after_missed)
        if new == row["status"]:
            continue
        conn.execute("UPDATE securities SET status=?, updated_at=? WHERE security_id=?",
                     (new, now, row["security_id"]))
        suspended += new == "SUSPENDED"
        delisted += new == "DELISTED"
    return suspended, delisted, broken


def _fetch_all_records(exchanges: list[str]) -> tuple[list[MasterRecord], set[str]]:
    """Fetch every exchange's master snapshot, tolerating one exchange's
    fetch failing without losing the other -- mirrors ingest.daily's
    per-exchange isolation, since a BSE API outage must not block an
    NSE-only refresh."""
    provider_by_exchange = {"NSE": "nse_equity_l", "BSE": "bse_scrip_api"}
    records: list[MasterRecord] = []
    fetched: set[str] = set()
    errors: list[str] = []
    for exchange in exchanges:
        provider_name = provider_by_exchange.get(exchange)
        if provider_name is None:
            continue
        try:
            provider = get_security_master_provider(provider_name)
            records.extend(provider.fetch_master())
            fetched.add(exchange)
        except ProviderError as exc:
            errors.append(f"{exchange} ({provider_name}): {exc}")
    if errors and not records:
        raise ProviderError(f"all security-master fetches failed: {'; '.join(errors)}")
    return records, fetched


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
    *, sqlite_path: Path, exchanges: list[str] | None = None,
    lifecycle: LifecycleConfig | None = None, today: date | None = None,
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
            records, fetched = _fetch_all_records(exchanges)
            lifecycle_cfg = lifecycle or load_universe_config().lifecycle

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
                suspended, delisted, broken = _update_lifecycle(
                    conn, records, fetched, cfg=lifecycle_cfg, now=now, today=today or today_ist())

            if broken:
                handle.degraded = True  # absences were NOT counted for these; see doctor/logs
                handle.metrics["snapshot_looked_broken"] = broken
            handle.metrics["newly_suspended"] = suspended
            handle.metrics["newly_delisted"] = delisted
            handle.rows_in = len(records)
            handle.rows_written = securities_upserted
            handle.metrics["listings_upserted"] = listings_upserted
            handle.metrics["renames"] = renames

        return MasterIngestResult(securities_upserted, listings_upserted, renames,
                                  suspended=suspended, delisted=delisted, degraded=bool(broken))
    finally:
        conn.close()


# --- Historical symbol changes ---------------------------------------------

#: valid_from for a symbol whose start we do not know (it was used since listing, before any
#: change the exchange records). Sorts before every real date, as symbol_history compares text.
UNKNOWN_START = "1900-01-01"


class SymbolChangeResult(BaseModel):
    changes: int
    inserted: int
    already_known: int
    #: New symbol not in our master at all -- a company no longer listed. Normal, not an error.
    unresolved: int
    #: Old symbol also used by ANOTHER security (reused). Skipped: linking it would apply one
    #: company's corporate actions to another's bars. Those bars stay unadjusted, as before.
    conflicts: list[str]
    #: Old symbols given the instrument class (fund/equity) of the symbol they became.
    classes_inherited: int = 0


def apply_symbol_changes(
    conn: sqlite3.Connection, changes: list[SymbolChange]
) -> SymbolChangeResult:
    """Record each old symbol in symbol_history against the security that holds the new one.

    Newest change first, so a chain resolves in one pass: TATAMOTORS -> TMPV (2025) links
    TATAMOTORS to TMPV's security, then TELCO -> TATAMOTORS (2003) finds TATAMOTORS in
    symbol_history. valid_to is the change date (bars before it carry the old symbol); valid_from
    is the change INTO the old symbol when the file has one, else UNKNOWN_START.
    """
    entered: dict[tuple[str, str], date] = {}
    for ch in changes:
        key = (ch.exchange, ch.new_symbol)
        entered[key] = max(entered.get(key, ch.effective_date), ch.effective_date)

    def owners(exchange: str, symbol: str) -> set[int]:
        return {
            int(r["security_id"]) for r in conn.execute(
                "SELECT security_id FROM listings WHERE exchange=? AND symbol=? "
                "UNION SELECT security_id FROM symbol_history WHERE exchange=? AND symbol=?",
                (exchange, symbol, exchange, symbol),
            )
        }

    inserted = already = unresolved = 0
    conflicts: list[str] = []
    for ch in sorted(changes, key=lambda c: c.effective_date, reverse=True):
        new_owner = owners(ch.exchange, ch.new_symbol)
        if len(new_owner) != 1:
            unresolved += 1
            continue
        (security_id,) = new_owner
        old_owner = owners(ch.exchange, ch.old_symbol)
        if old_owner - {security_id}:
            conflicts.append(ch.old_symbol)
            continue
        if old_owner:
            already += 1
            continue
        start = entered.get((ch.exchange, ch.old_symbol))
        valid_from = start.isoformat() if start and start < ch.effective_date else UNKNOWN_START
        conn.execute(
            "INSERT INTO symbol_history (security_id, exchange, symbol, valid_from, valid_to) "
            "VALUES (?, ?, ?, ?, ?)",
            (security_id, ch.exchange, ch.old_symbol, valid_from, ch.effective_date.isoformat()),
        )
        inserted += 1
    return SymbolChangeResult(changes=len(changes), inserted=inserted, already_known=already,
                              unresolved=unresolved, conflicts=conflicts)


def ingest_symbol_changes(
    *, sqlite_path: Path, raw_root: Path, provider_name: str = "nse_equity_l"
) -> SymbolChangeResult:
    """Fetch the exchange's symbol-change history and backfill symbol_history from it.

    EQUITY_L only ever shows today's symbol, so symbol_history built from master snapshots starts
    at our first snapshot: MINDAIND -> UNOMINDA (2022) was invisible, and UNOMINDA's bonus never
    reached the MINDAIND bars. Run `stk ingest master` first -- a change resolves only when its
    new symbol is in listings. Idempotent: a symbol already tracked is left alone.
    """
    conn = connect(sqlite_path)
    try:
        with job_run(conn, "ingest_symbol_changes") as handle:
            provider = get_security_master_provider(provider_name)
            artifact = provider.fetch_symbol_changes_artifact()
            persist_artifact(raw_root, conn, artifact)
            changes = provider.parse_symbol_changes(artifact)
            with transaction(conn):
                result = apply_symbol_changes(conn, changes)
                result.classes_inherited = inherit_classes_from_renames(
                    conn, changes, now=datetime.now(UTC).isoformat())
            handle.rows_in = result.changes
            handle.rows_written = result.inserted
            handle.metrics.update(
                inserted=result.inserted, already_known=result.already_known,
                unresolved=result.unresolved, conflicts=len(result.conflicts),
                classes_inherited=result.classes_inherited,
            )
        return result
    finally:
        conn.close()
