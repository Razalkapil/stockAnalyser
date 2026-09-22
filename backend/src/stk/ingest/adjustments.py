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

from stk.ingest.corpactions import terp_price_factor
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
#: -- and AGMs, which are purely informational). BONUS_NON_EQUITY is the same shape as a
#: dividend: recognised, understood, and by design has no equity price/volume factor (a bonus of
#: preference shares does not dilute equity -- see ingest.corpactions). Anything else without a
#: factor (rights, demergers, an unparsed split...) is a known hole in the adjusted series and
#: counts as degradation. Real counts over ~15 months: 202 distributions, 35 buybacks, 1 AGM,
#: 1 non-equity bonus -- flagging those would raise a permanent false alarm.
NON_PRICE_EVENT_TYPES = frozenset({"DIVIDEND", "DISTRIBUTION", "BUYBACK", "AGM",
                                   "BONUS_NON_EQUITY"})

#: Price events this module can structurally never compute a factor for, given the data sources
#: it has -- not "not implemented yet". A DEMERGER needs the spun-off entity's own traded value,
#: which no free NSE feed gives; a CAPITAL_REDUCTION's subject never carries a ratio at all (see
#: ingest.corpactions.ActionType). Counted and named (so nothing goes invisible) but excluded
#: from `degraded`, whose job is to flag a hole THIS RUN could plausibly close -- a permanent gap
#: that alerts every run forever is a flag nobody reads, exactly the trap BONUS_NON_EQUITY above
#: fell into before it got its own type. RIGHTS stays OUTSIDE this set on purpose: most rights DO
#: get a computed factor (see rights_factors), and one that does not (no cum-rights price in the
#: lake, or no premium stated) is a real, closeable hole, not a permanent one.
PERMANENTLY_UNADJUSTABLE_TYPES = frozenset({"DEMERGER", "CAPITAL_REDUCTION"})

#: Price columns scaled by the cumulative price factor.
PRICE_COLUMNS = ("open", "high", "low", "close", "prev_close", "last", "vwap", "settle_price")

#: Quantity columns scaled by the cumulative volume factor. `turnover`
#: is deliberately absent: rupees traded on the day is a historical
#: fact, and since price_factor * volume_factor == 1 it is conserved
#: anyway -- scaling it would actively corrupt it.
VOLUME_COLUMNS = ("volume", "delivery_qty")


#: Series a cum-rights close may be read from, best first. A symbol can publish several series
#: on one day (an EQ line and a T0 stub); the equity line is the one whose price the rights are
#: priced against.
_CUM_PRICE_SERIES = ("EQ", "BE", "BZ")


class RightsFactor(BaseModel):
    """A rights issue whose factor was computed from the lake, and how."""

    ca_id: int
    symbol: str
    ex_date: date
    cum_price: Decimal
    issue_price: Decimal
    face_value: Decimal
    price_factor: Decimal


def _face_value_asof(
    conn: sqlite3.Connection, *, exchange: str, symbol: str, ex_date: date
) -> Decimal | None:
    """The face value this symbol's shares carried on ``ex_date``.

    A rights premium is quoted over the face value AT THE TIME. Reading today's face value
    would be wrong for any company that later split -- 15 of the stored rights issues are
    followed by one. A face-value change records what it changed FROM, so the earliest such
    change after the ex-date states the value in force before it.
    """
    row = conn.execute(
        """SELECT face_value_from FROM corporate_actions
           WHERE symbol = ? AND exchange = ? AND ex_date > ? AND face_value_from IS NOT NULL
             AND parse_status = 'parsed'
           ORDER BY ex_date LIMIT 1""",
        (symbol, exchange, ex_date.isoformat()),
    ).fetchone()
    if row and row["face_value_from"]:
        return Decimal(str(row["face_value_from"]))
    current = conn.execute(
        """SELECT s.face_value FROM securities s
           JOIN listings l ON l.security_id = s.security_id
           WHERE l.exchange = ? AND l.symbol = ? AND s.face_value IS NOT NULL
           LIMIT 1""",
        (exchange, symbol),
    ).fetchone()
    return Decimal(str(current["face_value"])) if current else None


def _cum_prices(
    parquet_root: Path, exchange: str, wanted: list[tuple[str, date]]
) -> dict[tuple[str, date], Decimal]:
    """Last close strictly BEFORE each ex-date, from the raw (unadjusted) lake.

    Raw on purpose: every factor in the timeline is expressed against the price as the exchange
    reported it that day, and they compose multiplicatively afterwards. One query for all the
    symbols, then the pick happens in Python -- a query per action would rescan the lake ~215
    times for no benefit.
    """
    if not wanted:
        return {}
    symbols = sorted({sym for sym, _ in wanted})
    # The LATEST ex-date bounds the fetch: every action needs the close just before its OWN
    # ex-date, so bounding by the earliest would starve all the others. (It did: 24 liquid
    # symbols silently got no factor until this read `max`.)
    latest = max(d for _, d in wanted)
    with duck.connect(parquet_root) as session:
        rows = session.con.execute(
            """SELECT symbol, date, series, close FROM bars_daily
               WHERE exchange = ? AND symbol IN ? AND date < ? AND close > 0
                 AND series IN ?
               ORDER BY symbol, date""",
            [exchange, symbols, latest.isoformat(), list(_CUM_PRICE_SERIES)],
        ).fetchall()
    # symbol -> ordered list of (date, series_rank, close)
    history: dict[str, list[tuple[date, int, Decimal]]] = {}
    for symbol, day, series, close in rows:
        history.setdefault(symbol, []).append(
            (day, _CUM_PRICE_SERIES.index(series), Decimal(str(close)))
        )
    out: dict[tuple[str, date], Decimal] = {}
    for symbol, ex_date in wanted:
        before = [h for h in history.get(symbol, []) if h[0] < ex_date]
        if not before:
            continue
        last_day = max(h[0] for h in before)
        same_day = sorted(h for h in before if h[0] == last_day)  # series rank breaks the tie
        out[(symbol, ex_date)] = same_day[0][2]
    return out


def rights_factors(
    conn: sqlite3.Connection, *, exchange: str, parquet_root: Path
) -> dict[int, RightsFactor]:
    """Theoretical ex-rights factors for every rights action the parser left computable.

    This is the half of a rights issue the parser cannot do: it needs the face value as of the
    ex-date and the cum-rights close. An action whose price is missing, or whose numbers give an
    implausible factor, is simply absent from the result -- and therefore still counted as an
    excluded action, which is the honest outcome.
    """
    rows = conn.execute(
        """SELECT ca_id, symbol, ex_date, ratio_numerator, ratio_denominator, issue_premium
           FROM corporate_actions
           WHERE exchange = ? AND action_type = 'RIGHTS' AND parse_status = 'parsed'
             AND price_factor IS NULL AND issue_premium IS NOT NULL
             AND ratio_numerator IS NOT NULL AND ratio_denominator IS NOT NULL
             AND ex_date IS NOT NULL""",
        (exchange,),
    ).fetchall()
    if not rows:
        return {}
    wanted = [(str(r["symbol"]), date.fromisoformat(str(r["ex_date"]))) for r in rows]
    prices = _cum_prices(parquet_root, exchange, wanted)

    out: dict[int, RightsFactor] = {}
    for row in rows:
        symbol, ex_date = str(row["symbol"]), date.fromisoformat(str(row["ex_date"]))
        cum = prices.get((symbol, ex_date))
        if cum is None:
            continue
        face_value = _face_value_asof(conn, exchange=exchange, symbol=symbol, ex_date=ex_date)
        if face_value is None:
            continue
        issue_price = face_value + Decimal(str(row["issue_premium"]))
        factor = terp_price_factor(
            new_shares=int(row["ratio_numerator"]),
            held_shares=int(row["ratio_denominator"]),
            issue_price=issue_price,
            cum_price=cum,
        )
        if factor is None:
            continue
        out[int(row["ca_id"])] = RightsFactor(
            ca_id=int(row["ca_id"]), symbol=symbol, ex_date=ex_date, cum_price=cum,
            issue_price=issue_price, face_value=face_value, price_factor=factor,
        )
    return out


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
        rights_applied: int = 0,
        excluded_permanent: int = 0,
        unresolved_symbols: tuple[str, ...] = (),
    ) -> None:
        self.exchange = exchange
        self.actions_applied = actions_applied
        self.factor_rows = factor_rows
        self.bars_written = bars_written
        #: Actionable holes -- a price-affecting action this module structurally COULD compute a
        #: factor for (given more data, a fixed parser, a re-ingested security master...) but
        #: currently has not. This is what `degraded` is about.
        self.excluded_actions = excluded_actions
        self.unresolved_actions = unresolved_actions
        #: Rights issues whose theoretical ex-rights factor was derived from the lake. Reported
        #: because it is the one number here that says a KNOWN hole got smaller.
        self.rights_applied = rights_applied
        #: Demergers/capital reductions: this module can never compute a factor for these given
        #: its data sources (see PERMANENTLY_UNADJUSTABLE_TYPES). Reported so nothing is hidden,
        #: but does NOT feed `degraded` -- a gap that can never close must not alert forever.
        self.excluded_permanent = excluded_permanent
        self.unresolved_symbols = unresolved_symbols

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

    Actions sharing an ex-date (a split AND a bonus, as BAJAJFINSV did on
    2022-09-13) are merged into ONE row carrying their product. Emitting a
    row each gave two rows with the same effective_date but different
    running products, and the lookup applied only one of them.
    """
    by_security: dict[tuple[str, str], list[ActionFactor]] = {}
    for action in actions:
        by_security.setdefault((action.exchange, action.security_key), []).append(action)

    rows: list[FactorRow] = []
    for (exchange, _key), group in by_security.items():
        by_date: dict[date, list[ActionFactor]] = {}
        for action in group:
            by_date.setdefault(action.ex_date, []).append(action)

        # Newest first: the running product for an older bar includes
        # every action that happened after it.
        cumulative_price = Decimal(1)
        cumulative_volume = Decimal(1)
        for ex_date in sorted(by_date, reverse=True):
            same_day = by_date[ex_date]
            price_factor = Decimal(1)
            volume_factor = Decimal(1)
            symbols: set[str] = set()
            for action in same_day:
                price_factor *= action.price_factor
                volume_factor *= action.volume_factor
                symbols.update(action.symbols)
            cumulative_price *= price_factor
            cumulative_volume *= volume_factor
            for symbol in sorted(symbols):
                rows.append(
                    FactorRow(
                        exchange=exchange,
                        symbol=symbol,
                        effective_date=ex_date,
                        price_factor=price_factor,
                        volume_factor=volume_factor,
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

    Raises on two rows with one effective_date: which one "wins" would be
    arbitrary, and picking one silently drops the other action.
    """
    if len({r.effective_date for r in rows}) != len(rows):
        raise ValueError(
            f"duplicate effective_date in factor timeline for {rows[0].symbol}; "
            "same-day actions must be merged by build_factor_rows"
        )
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
    #: A price-affecting action we could not turn into a factor, and structurally MIGHT be able
    #: to (an unparsed subject, a rights issue missing price history or a premium) -- this is
    #: what `degraded` counts.
    excluded: int
    #: The same shape of gap, but for an action type this module can never compute a factor for
    #: given its data sources (see PERMANENTLY_UNADJUSTABLE_TYPES). Reported, never hidden, but
    #: does not itself degrade the run.
    excluded_permanent: int
    unresolved: int
    #: Symbols behind `unresolved` (capped for the metrics line -- see the sweep's failed_symbols
    #: for the same convention), so a person does not have to query the DB to find who.
    unresolved_symbols: list[str] = []


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


def _symbol_owners(conn: sqlite3.Connection, *, exchange: str) -> dict[str, set[int]]:
    """Every security that has ever used each symbol on this exchange."""
    owners: dict[str, set[int]] = {}
    for r in conn.execute(
        "SELECT symbol, security_id FROM listings WHERE exchange=? "
        "UNION SELECT symbol, security_id FROM symbol_history WHERE exchange=?",
        (exchange, exchange),
    ):
        owners.setdefault(str(r["symbol"]), set()).add(int(r["security_id"]))
    return owners


def load_actions(
    conn: sqlite3.Connection,
    *,
    exchange: str,
    rights: dict[int, RightsFactor] | None = None,
) -> _LoadedActions:
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
    owners = _symbol_owners(conn, exchange=exchange)

    def security_of(row: sqlite3.Row) -> int | None:
        # corporate_actions.security_id is resolved at INGEST time from current listings, so an
        # action announced under a since-renamed symbol is stored NULL. Resolve it again here
        # (symbol_history now knows old symbols) -- else the same company gets two timelines.
        if row["security_id"] is not None:
            return int(row["security_id"])
        candidates = owners.get(str(row["symbol"]), set())
        return next(iter(candidates)) if len(candidates) == 1 else None

    deduped: dict[tuple, tuple[sqlite3.Row, int | None, float, float | None]] = {}
    excluded = 0
    excluded_permanent = 0
    unresolved = 0
    unresolved_symbols: list[str] = []

    rights = rights or {}
    for row in rows:
        price_factor = row["price_factor"]
        volume_factor = row["volume_factor"]
        if price_factor is None and row["parse_status"] == "parsed":
            # A rights issue is stored parsed but factorless on purpose: its factor needs the
            # cum-rights close, which the parser cannot see. If the caller worked it out, it is
            # as good as any other factor; if not, it stays a counted hole below.
            computed = rights.get(int(row["ca_id"]))
            if computed is not None:
                price_factor = float(computed.price_factor)
                volume_factor = float(1 / computed.price_factor)
        if row["parse_status"] != "parsed" or price_factor is None:
            # A dividend legitimately has no price factor under this
            # project's convention and is not a degradation; anything
            # else we could not parse IS one -- unless it is a type this
            # module can never compute a factor for regardless (counted
            # separately so it does not masquerade as a closeable gap).
            if row["action_type"] in PERMANENTLY_UNADJUSTABLE_TYPES:
                excluded_permanent += 1
            elif row["action_type"] not in NON_PRICE_EVENT_TYPES:
                excluded += 1
            continue

        security_id = security_of(row)
        identity = (
            security_id if security_id is not None else f"sym:{row['symbol']}",
            row["ex_date"],
            row["action_type"],
            row["ratio_numerator"],
            row["ratio_denominator"],
            round(float(price_factor), 12),
        )
        incumbent = deduped.get(identity)
        if incumbent is None or str(row["captured_at"]) > str(incumbent[0]["captured_at"]):
            deduped[identity] = (row, security_id, price_factor, volume_factor)

    actions: list[ActionFactor] = []
    for row, resolved, price_factor, volume_factor in deduped.values():
        symbol = str(row["symbol"])
        if resolved is not None:
            security_id = resolved
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
            unresolved_symbols.append(symbol)
            key = f"sym:{exchange}:{symbol}"
            symbols = (symbol,)

        actions.append(
            ActionFactor(
                exchange=exchange,
                security_key=key,
                symbols=symbols,
                ex_date=date.fromisoformat(str(row["ex_date"])),
                price_factor=Decimal(str(price_factor)),
                volume_factor=Decimal(str(volume_factor or 1)),
            )
        )

    return _LoadedActions(actions=actions, excluded=excluded,
                          excluded_permanent=excluded_permanent, unresolved=unresolved,
                          unresolved_symbols=unresolved_symbols)


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
        # Rights first: their factors are the one kind this module has to DERIVE (from the
        # cum-rights close) rather than read, so they must exist before the timeline is built.
        rights = rights_factors(conn, exchange=exchange, parquet_root=parquet_root)
        loaded = load_actions(conn, exchange=exchange, rights=rights)
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
        rights_applied=len(rights),
        excluded_permanent=loaded.excluded_permanent,
        unresolved_symbols=tuple(loaded.unresolved_symbols),
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
                    "rights_applied": result.rights_applied,
                    "excluded_actions": result.excluded_actions,
                    "unresolved_actions": result.unresolved_actions,
                    "excluded_permanent": result.excluded_permanent,
                }
            )
            if result.unresolved_symbols:
                shown = result.unresolved_symbols[:10]
                more = len(result.unresolved_symbols) - len(shown)
                handle.metrics["unresolved_symbols"] = (
                    ", ".join(shown) + (f" (+{more} more)" if more else "")
                )
            # Wrote data, and knows that data is incomplete. Not a
            # failure (the rest of the series is correct and useful),
            # not a success (some symbol's history is unadjusted).
            handle.degraded = result.degraded
        return result
    finally:
        conn.close()
