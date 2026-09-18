"""Corporate-action back-adjustment: factor timelines and the derived
bars_daily_adjusted dataset.

WHAT "ADJUSTED" MEANS HERE, PRECISELY. This is standard BACK-adjustment:
the most recent bars are left exactly as the exchange reported them,
and older bars are scaled so the series is continuous across splits and
bonuses. A chart, an indicator and a backtest all want this. "What did
I actually pay on 12-Mar-2019" does not -- that number lives in
bars_daily and is never rewritten.

    cumulative_price_factor(bar)  = product of price_factor(a)
                                    for every action a with ex_date > bar.date
    cumulative_volume_factor(bar) = the same product over volume_factor

A bar on or after the newest ex-date therefore has both factors exactly
1.0. A bar ON an ex-date is NOT adjusted by that action: the ex-date is
the first day the price already reflects the corporate action, so
applying the factor to it would double-count. That off-by-one is the
classic bug in this code and has its own test.

THE FACTORS THEMSELVES come from ingest.corpactions, which stores, per
action, the multiplier to apply to bars strictly BEFORE its ex-date --
for a 1:1 bonus, price_factor=0.5 and volume_factor=2.0, conserving
value (price_factor * volume_factor == 1). This module only composes
them; it never re-derives a ratio from free text.

WHAT IS DELIBERATELY EXCLUDED. Only rows with parse_status='parsed' AND
a non-null price_factor feed the timeline. Rows that are 'ambiguous' or
'unparsed' are excluded AND COUNTED, and a non-zero count inside the
rebuilt range marks the job degraded -- a corporate action we could not
compute is a known hole in the adjusted series, and the whole point of
this codebase's loud-failure rule is that such a hole is visible rather
than silently smoothed over. Dividends are a separate case: they
legitimately carry price_factor IS NULL by this project's convention
(cash events, not price events), so they are excluded WITHOUT counting
as degradation.

DUPLICATES. corporate_actions is keyed on (source, source_hash), so
when NSE republishes an action with a corrected field, BOTH rows
survive by design. Composing both would apply a 1:1 bonus twice and
quarter the pre-ex prices. The timeline therefore dedupes on the
action's economic identity, keeping the most recently captured row.

RENAMES. Bars are keyed by the symbol as of the bar's date; a corporate
action carries the symbol as of its announcement. Both sides resolve to
security_id (via symbol_history/listings) so a factor announced under
NEWNAME still applies to bars written under OLDNAME. The emitted
adjustment_factors rows are then written for EVERY symbol that security
has used on that exchange, so the table remains usable on its own.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
from pydantic import BaseModel

from stk.store import duck
from stk.store.db.engine import connect
from stk.store.parquet.layout import (
    adjustment_factors_path,
    bars_daily_adjusted_partition,
)
from stk.store.parquet.schema import (
    ADJUSTMENT_FACTORS_SCHEMA,
    BARS_DAILY_ADJUSTED_SCHEMA,
)
from stk.store.parquet.writer import upsert_partition

#: Action types that do NOT move a price series and so legitimately carry no price factor:
#: cash to the holder (dividends, InvIT/REIT distributions, bond interest), and events with no
#: price effect at all (buybacks -- shares are extinguished, the exchange applies no adjustment
#: -- and AGMs, which are purely informational). Anything else without a factor (rights,
#: demergers, an unparsed split...) is a known hole in the adjusted series and counts as
#: degradation. Real counts over ~15 months: 202 distributions, 35 buybacks, 1 AGM -- flagging
#: those would raise a permanent false alarm.
NON_PRICE_EVENT_TYPES = frozenset({"DIVIDEND", "DISTRIBUTION", "BUYBACK", "AGM"})

#: Price columns scaled by the cumulative price factor.
PRICE_COLUMNS = ("open", "high", "low", "close", "prev_close", "last", "vwap", "settle_price")

#: Quantity columns scaled by the cumulative volume factor. `turnover`
#: is deliberately absent: rupees traded on the day is a historical
#: fact, and since price_factor * volume_factor == 1 it is conserved
#: anyway -- scaling it would actively corrupt it.
VOLUME_COLUMNS = ("volume", "delivery_qty")


class ActionFactor(BaseModel):
    """One price/volume-affecting action, already deduped and resolved."""

    exchange: str
    security_key: str  # "sid:123" or "sym:NSE:RELIANCE" when unresolved
    symbols: tuple[str, ...]
    ex_date: date
    price_factor: Decimal
    volume_factor: Decimal


class FactorRow(BaseModel):
    """One emitted adjustment_factors row."""

    exchange: str
    symbol: str
    effective_date: date
    price_factor: Decimal
    volume_factor: Decimal
    cumulative_price_factor: Decimal
    cumulative_volume_factor: Decimal


class AdjustmentResult:
    def __init__(
        self,
        exchange: str,
        *,
        actions_applied: int,
        factor_rows: int,
        bars_written: int,
        excluded_actions: int,
        unresolved_actions: int,
    ) -> None:
        self.exchange = exchange
        self.actions_applied = actions_applied
        self.factor_rows = factor_rows
        self.bars_written = bars_written
        self.excluded_actions = excluded_actions
        self.unresolved_actions = unresolved_actions

    @property
    def degraded(self) -> bool:
        return bool(self.excluded_actions or self.unresolved_actions)


def build_factor_rows(actions: Iterable[ActionFactor]) -> list[FactorRow]:
    """Compose per-action factors into a cumulative back-adjustment timeline.

    For each (exchange, security), actions are walked from NEWEST to
    OLDEST accumulating a running product. The row emitted for
    ``effective_date = E`` carries the multiplier that applies to any
    bar with ``date < E`` and ``date >= the previous (older) effective
    date`` -- i.e. the running product INCLUDING this row's own factor.
    Read that sentence twice; it is the single most misread number in
    this file.

    Arithmetic is Decimal throughout. Float would make
    price_factor * volume_factor == 1 fail by ~1e-17 per action, which
    compounds into a visible drift over a 15-year series.
    """
    by_security: dict[tuple[str, str], list[ActionFactor]] = {}
    for action in actions:
        by_security.setdefault((action.exchange, action.security_key), []).append(action)

    rows: list[FactorRow] = []
    for (exchange, _key), group in by_security.items():
        # Newest first: the running product for an older bar includes
        # every action that happened after it.
        ordered = sorted(group, key=lambda a: a.ex_date, reverse=True)
        cumulative_price = Decimal(1)
        cumulative_volume = Decimal(1)
        for action in ordered:
            cumulative_price *= action.price_factor
            cumulative_volume *= action.volume_factor
            for symbol in action.symbols:
                rows.append(
                    FactorRow(
                        exchange=exchange,
                        symbol=symbol,
                        effective_date=action.ex_date,
                        price_factor=action.price_factor,
                        volume_factor=action.volume_factor,
                        cumulative_price_factor=cumulative_price,
                        cumulative_volume_factor=cumulative_volume,
                    )
                )
    return sorted(rows, key=lambda r: (r.exchange, r.symbol, r.effective_date))


def factors_for_bar(rows: list[FactorRow], bar_date: date) -> tuple[Decimal, Decimal]:
    """The cumulative factors applying to one bar, given that symbol's
    timeline (any order).

    A bar ON an ex-date is NOT adjusted by that action -- the ex-date is
    the first session whose price already reflects it. Hence the strict
    ``effective_date > bar_date``.
    """
    applicable = [r for r in rows if r.effective_date > bar_date]
    if not applicable:
        return Decimal(1), Decimal(1)
    # The rows already carry running products, so the correct answer is
    # the one whose effective_date is the OLDEST among those still in
    # the future relative to this bar.
    nearest = min(applicable, key=lambda r: r.effective_date)
    return nearest.cumulative_price_factor, nearest.cumulative_volume_factor


# --- Reading actions out of SQLite -----------------------------------------


class _LoadedActions(BaseModel):
    actions: list[ActionFactor]
    excluded: int
    unresolved: int


def _symbols_for_security(
    conn: sqlite3.Connection, *, exchange: str, security_id: int, fallback: str
) -> tuple[str, ...]:
    """Every symbol this security has used on this exchange.

    Includes historical names so a factor announced under the current
    symbol still lands on bars written under an older one.
    """
    rows = conn.execute(
        "SELECT symbol FROM symbol_history WHERE exchange=? AND security_id=? "
        "UNION SELECT symbol FROM listings WHERE exchange=? AND security_id=?",
        (exchange, security_id, exchange, security_id),
    ).fetchall()
    symbols = {str(r["symbol"]) for r in rows}
    symbols.add(fallback)
    return tuple(sorted(symbols))


def load_actions(conn: sqlite3.Connection, *, exchange: str) -> _LoadedActions:
    """Load price-affecting corporate actions for one exchange, deduped.

    Returns the usable actions plus counts of what was left out, so the
    caller can mark the run degraded rather than quietly producing an
    adjusted series with a hole in it.
    """
    rows = conn.execute(
        """SELECT ca_id, security_id, symbol, ex_date, action_type, parse_status,
                  price_factor, volume_factor, ratio_numerator, ratio_denominator,
                  captured_at
           FROM corporate_actions
           WHERE exchange = ? AND ex_date IS NOT NULL
           ORDER BY ex_date, ca_id""",
        (exchange,),
    ).fetchall()

    # Economic identity, NOT source_hash: NSE republishing a corrected
    # row creates a second row by design, and applying both would
    # compound the same bonus twice.
    deduped: dict[tuple, sqlite3.Row] = {}
    excluded = 0
    unresolved = 0

    for row in rows:
        if row["parse_status"] != "parsed" or row["price_factor"] is None:
            # A dividend legitimately has no price factor under this
            # project's convention and is not a degradation; anything
            # else we could not parse IS one.
            if row["action_type"] not in NON_PRICE_EVENT_TYPES:
                excluded += 1
            continue

        identity = (
            row["security_id"] if row["security_id"] is not None else f"sym:{row['symbol']}",
            row["ex_date"],
            row["action_type"],
            row["ratio_numerator"],
            row["ratio_denominator"],
            round(float(row["price_factor"]), 12),
        )
        incumbent = deduped.get(identity)
        if incumbent is None or str(row["captured_at"]) > str(incumbent["captured_at"]):
            deduped[identity] = row

    actions: list[ActionFactor] = []
    for row in deduped.values():
        symbol = str(row["symbol"])
        if row["security_id"] is not None:
            security_id = int(row["security_id"])
            key = f"sid:{security_id}"
            symbols = _symbols_for_security(
                conn, exchange=exchange, security_id=security_id, fallback=symbol
            )
        else:
            # The security master has not been ingested (or this symbol
            # is not in it). Fall back to symbol-keying, count it, and
            # let the caller degrade the run -- a factor applied to only
            # one of a renamed security's symbols is a real, if partial,
            # gap.
            unresolved += 1
            key = f"sym:{exchange}:{symbol}"
            symbols = (symbol,)

        actions.append(
            ActionFactor(
                exchange=exchange,
                security_key=key,
                symbols=symbols,
                ex_date=date.fromisoformat(str(row["ex_date"])),
                price_factor=Decimal(str(row["price_factor"])),
                volume_factor=Decimal(str(row["volume_factor"] or 1)),
            )
        )

    return _LoadedActions(actions=actions, excluded=excluded, unresolved=unresolved)


# --- Materialisation -------------------------------------------------------


def _factor_table(rows: list[FactorRow]) -> pa.Table:
    if not rows:
        return ADJUSTMENT_FACTORS_SCHEMA.empty_table()
    return pa.Table.from_pylist(
        [
            {
                "exchange": r.exchange,
                "symbol": r.symbol,
                "effective_date": r.effective_date,
                "price_factor": float(r.price_factor),
                "volume_factor": float(r.volume_factor),
                "cumulative_price_factor": float(r.cumulative_price_factor),
                "cumulative_volume_factor": float(r.cumulative_volume_factor),
            }
            for r in rows
        ],
        schema=ADJUSTMENT_FACTORS_SCHEMA,
    )


def _adjust_bar(bar: dict, price_factor: Decimal, volume_factor: Decimal) -> dict:
    out = dict(bar)
    pf, vf = float(price_factor), float(volume_factor)
    for column in PRICE_COLUMNS:
        if out.get(column) is not None:
            out[column] = out[column] * pf
    for column in VOLUME_COLUMNS:
        if out.get(column) is not None:
            # Volumes stay integral: a split turning 1,000 shares into
            # 5,000 is exact, and a fractional share count in an int64
            # column would fail the Arrow cast anyway.
            out[column] = round(out[column] * vf)
    out["cumulative_price_factor"] = pf
    out["cumulative_volume_factor"] = vf
    return out


def rebuild_adjusted_bars(
    *,
    exchange: str,
    sqlite_path: Path,
    parquet_root: Path,
) -> AdjustmentResult:
    """Rebuild adjustment_factors and bars_daily_adjusted for one exchange.

    Network-free and fully rebuildable: reads bars_daily through the
    store.duck view layer, reads corporate_actions from SQLite, and
    writes two derived datasets. bars_daily itself is never opened for
    writing -- it is the source of truth and a derived step has no
    business touching it.

    A new ex-date invalidates every EARLIER bar of that symbol, so the
    rebuild is whole-exchange, all years. The build plan sized this at
    ~16 files and seconds, which is why there is no incremental path to
    get subtly wrong.
    """
    conn = connect(sqlite_path)
    try:
        loaded = load_actions(conn, exchange=exchange)
    finally:
        conn.close()

    factor_rows = build_factor_rows(loaded.actions)
    by_symbol: dict[str, list[FactorRow]] = {}
    for row in factor_rows:
        by_symbol.setdefault(row.symbol, []).append(row)

    factors_path = adjustment_factors_path(parquet_root, exchange)
    factors_path.parent.mkdir(parents=True, exist_ok=True)
    upsert_partition(
        factors_path,
        _factor_table(factor_rows),
        schema=ADJUSTMENT_FACTORS_SCHEMA,
        replace_dates={r.effective_date for r in factor_rows},
        date_column="effective_date",
        sort_keys=[("symbol", "ascending"), ("effective_date", "ascending")],
    )

    bars_written = 0
    with duck.connect(parquet_root) as session:
        years = [
            int(r[0])
            for r in session.con.execute(
                "SELECT DISTINCT year FROM bars_daily WHERE exchange = ? ORDER BY year",
                [exchange],
            ).fetchall()
        ]

        for year in years:
            result = session.con.execute(
                "SELECT * EXCLUDE (year) FROM bars_daily WHERE exchange = ? AND year = ?",
                [exchange, year],
            )
            columns = [d[0] for d in result.description]
            bars = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
            if not bars:
                continue

            adjusted = []
            for bar in bars:
                price_factor, volume_factor = factors_for_bar(
                    by_symbol.get(bar["symbol"], []), bar["date"]
                )
                adjusted.append(_adjust_bar(bar, price_factor, volume_factor))

            table = pa.Table.from_pylist(adjusted, schema=BARS_DAILY_ADJUSTED_SCHEMA)
            upsert_partition(
                bars_daily_adjusted_partition(parquet_root, exchange, year),
                table,
                schema=BARS_DAILY_ADJUSTED_SCHEMA,
                replace_dates={b["date"] for b in adjusted},
                manifest_root=parquet_root,
                dataset="bars_daily_adjusted",
                exchange=exchange,
                year=year,
            )
            bars_written += len(adjusted)

    return AdjustmentResult(
        exchange,
        actions_applied=len(loaded.actions),
        factor_rows=len(factor_rows),
        bars_written=bars_written,
        excluded_actions=loaded.excluded,
        unresolved_actions=loaded.unresolved,
    )


def rebuild_adjusted_bars_job(
    *, exchange: str, sqlite_path: Path, parquet_root: Path
) -> AdjustmentResult:
    """rebuild_adjusted_bars wrapped in a job_run scope.

    Kept separate so the rebuild itself stays a plain, testable
    function -- and so ingest.daily can call it as one step among
    several without nesting job scopes.
    """
    from stk.ingest.jobs import job_run  # noqa: PLC0415

    conn = connect(sqlite_path)
    try:
        with job_run(conn, f"rebuild_adjustments_{exchange.lower()}") as handle:
            result = rebuild_adjusted_bars(
                exchange=exchange, sqlite_path=sqlite_path, parquet_root=parquet_root
            )
            handle.rows_in = result.actions_applied
            handle.rows_written = result.bars_written
            handle.metrics.update(
                {
                    "factor_rows": result.factor_rows,
                    "excluded_actions": result.excluded_actions,
                    "unresolved_actions": result.unresolved_actions,
                }
            )
            # Wrote data, and knows that data is incomplete. Not a
            # failure (the rest of the series is correct and useful),
            # not a success (some symbol's history is unadjusted).
            handle.degraded = result.degraded
        return result
    finally:
        conn.close()
