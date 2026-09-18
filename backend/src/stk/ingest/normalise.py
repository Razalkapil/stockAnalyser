"""Normalisation of raw provider text into CanonicalBar rows.

Every source format (NSE sec_bhavdata_full, NSE/BSE UDiFF) goes through
its own parser function here into the identical CanonicalBar shape, so
downstream code never has to know which file a bar came from.

Rules enforced here (see providers.base.CanonicalBar's docstring and
the module-level notes below for why each matters):
  - '-' parses to None, never 0, for delivery fields.
  - TURNOVER_LACS is multiplied by 100_000 at this boundary; the word
    "lacs" never survives past this module.
  - Dates use explicit format strings, never dateutil inference.
  - skipinitialspace is applied to every NSE plain CSV (its headers and
    values both carry a leading space after the first column).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from stk.core.errors import ParseError
from stk.core.time import parse_ddmmmyyyy
from stk.providers.base import CanonicalBar

_LAKH = Decimal(100_000)


def _decimal_or_none(raw: str) -> Decimal | None:
    """Parse a numeric field, treating '-' (NSE's null marker) as None,
    never as 0 -- unreported delivery and zero delivery are different facts."""
    value = raw.strip()
    if value in ("-", ""):
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ParseError(f"could not parse numeric field {raw!r}") from exc


def _int_or_none(raw: str) -> int | None:
    dec = _decimal_or_none(raw)
    return int(dec) if dec is not None else None


def parse_sec_bhavdata_full(
    text: str, *, source: str = "nse_sec_bhavdata"
) -> Iterator[CanonicalBar]:
    """Parse NSE's sec_bhavdata_full_{DDMMYYYY}.csv into canonical bars.

    This file predates the UDiFF format and is the primary historical
    price source (see docs/adr/0003 once the phase-0 history spike
    lands). It carries OHLCV + delivery in one file but no ISIN --
    security_id resolution against the security master happens later
    in the ingest pipeline (see ingest.merge), not in this parser.
    """
    reader = csv.DictReader(io.StringIO(text), skipinitialspace=True)
    datetime.now(UTC)

    for raw_row in reader:
        row = {k.strip(): v.strip() for k, v in raw_row.items() if k}

        trade_date = parse_ddmmmyyyy(row["DATE1"])
        turnover_lacs = _decimal_or_none(row["TURNOVER_LACS"]) or Decimal(0)

        yield CanonicalBar(
            date=trade_date,
            exchange="NSE",
            symbol=row["SYMBOL"],
            series=row["SERIES"],
            instrument_type="EQ",
            open=_decimal_or_none(row["OPEN_PRICE"]) or Decimal(0),
            high=_decimal_or_none(row["HIGH_PRICE"]) or Decimal(0),
            low=_decimal_or_none(row["LOW_PRICE"]) or Decimal(0),
            close=_decimal_or_none(row["CLOSE_PRICE"]) or Decimal(0),
            prev_close=_decimal_or_none(row["PREV_CLOSE"]),
            last=_decimal_or_none(row["LAST_PRICE"]),
            vwap=_decimal_or_none(row["AVG_PRICE"]),
            volume=_int_or_none(row["TTL_TRD_QNTY"]) or 0,
            turnover=turnover_lacs * _LAKH,  # "lacs" never survives past this line
            trades=_int_or_none(row["NO_OF_TRADES"]),
            delivery_qty=_int_or_none(row["DELIV_QTY"]),
            delivery_pct=_decimal_or_none(row["DELIV_PER"]),
            source=source,
        )


def parse_legacy_bhavcopy(
    text: str, *, source: str = "nse_legacy_bhavcopy"
) -> Iterator[CanonicalBar]:
    """Parse NSE's legacy cm{DDMONYYYY}bhav.csv format (2010 through
    ~2019-10-01, confirmed by the phase-0 history spike -- see
    docs/adr/0003-historical-price-source.md).

    This is the ONLY source with confirmed coverage back to 2010, but
    it carries no delivery data and no ISIN -- both `delivery_qty` and
    `isin` are left None on every row from this parser. Once
    sec_bhavdata_full's coverage begins (2019-09-30, confirmed
    overlapping with this format's tail end), that source is preferred
    for its delivery data; this parser is only used before that date.

    Columns: SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,
    TOTTRDQTY,TOTTRDVAL,TIMESTAMP, (trailing empty column from a
    trailing comma in NSE's own header row -- csv.DictReader assigns it
    key None, which the row dict comprehension below drops via `if k`).
    TIMESTAMP is 'D-MON-YYYY' (day not zero-padded) -- %d in
    strptime accepts both, so no special-casing is needed.
    """
    reader = csv.DictReader(io.StringIO(text))

    for raw_row in reader:
        row = {k.strip(): v.strip() for k, v in raw_row.items() if k}

        trade_date = datetime.strptime(row["TIMESTAMP"], "%d-%b-%Y").date()

        yield CanonicalBar(
            date=trade_date,
            exchange="NSE",
            symbol=row["SYMBOL"],
            series=row["SERIES"],
            instrument_type="EQ",
            open=_decimal_or_none(row["OPEN"]) or Decimal(0),
            high=_decimal_or_none(row["HIGH"]) or Decimal(0),
            low=_decimal_or_none(row["LOW"]) or Decimal(0),
            close=_decimal_or_none(row["CLOSE"]) or Decimal(0),
            prev_close=_decimal_or_none(row["PREVCLOSE"]),
            last=_decimal_or_none(row["LAST"]),
            volume=_int_or_none(row["TOTTRDQTY"]) or 0,
            turnover=_decimal_or_none(row["TOTTRDVAL"]) or Decimal(0),
            source=source,
        )


def parse_bse_legacy_bhavcopy(
    text: str, *, business_date: date, source: str = "bse_legacy_bhavcopy"
) -> Iterator[CanonicalBar]:
    """Parse BSE's legacy EQ{DDMMYY}_CSV.ZIP bhavcopy (2010 through
    2024-07-05, confirmed by direct probe -- see
    docs/adr/0003-historical-price-source.md's BSE addendum).

    Columns: SC_CODE,SC_NAME,SC_GROUP,SC_TYPE,OPEN,HIGH,LOW,CLOSE,LAST,
    PREVCLOSE,NO_TRADES,NO_OF_SHRS,NET_TURNOV,TDCLOINDI. BSE identifies
    securities by a numeric scrip code, not a symbol -- there is no
    ISIN and no symbol in this file at all. ``symbol`` is set to the
    scrip code (as a string); resolving it to a real symbol/ISIN is a
    security-master join done later in the pipeline (ingest.merge), not
    this parser's job -- same division of responsibility as the other
    bhavcopy parsers in this module. This file has no delivery data,
    same as NSE's legacy format.

    The date itself is not a column in this file -- every row is for
    the one date the whole file covers, which the caller already knows
    (it's what was requested in the URL), so ``business_date`` is
    passed in rather than parsed from a row.
    """
    reader = csv.DictReader(io.StringIO(text))
    for raw_row in reader:
        row = {k.strip(): v.strip() for k, v in raw_row.items() if k}

        yield CanonicalBar(
            date=business_date,
            exchange="BSE",
            symbol=row["SC_CODE"],
            series=row.get("SC_GROUP") or None,
            instrument_type="EQ",
            open=_decimal_or_none(row["OPEN"]) or Decimal(0),
            high=_decimal_or_none(row["HIGH"]) or Decimal(0),
            low=_decimal_or_none(row["LOW"]) or Decimal(0),
            close=_decimal_or_none(row["CLOSE"]) or Decimal(0),
            prev_close=_decimal_or_none(row["PREVCLOSE"]),
            last=_decimal_or_none(row["LAST"]),
            volume=_int_or_none(row["NO_OF_SHRS"]) or 0,
            turnover=_decimal_or_none(row["NET_TURNOV"]) or Decimal(0),
            trades=_int_or_none(row["NO_TRADES"]),
            source=source,
        )


def parse_udiff(text: str, *, exchange: str, source: str) -> Iterator[CanonicalBar]:
    """Parse an NSE or BSE UDiFF bhavcopy CSV into canonical bars.

    UDiFF carries ISIN and uses ISO dates, unlike sec_bhavdata_full.
    Only EQ-instrument-type equity rows are yielded -- UDiFF also
    contains F&O rows in the combined file layout for some sources,
    filtered out here rather than downstream.
    """
    reader = csv.DictReader(io.StringIO(text))

    for raw_row in reader:
        row = {k.strip(): v.strip() for k, v in raw_row.items() if k}

        if row.get("FinInstrmTp") not in (None, "", "STK"):
            continue  # skip derivatives rows if present in a combined file

        trade_date = _parse_iso_date(row["TradDt"])
        turnover = _decimal_or_none(row.get("TtlTrfVal", "")) or Decimal(0)

        yield CanonicalBar(
            date=trade_date,
            exchange=exchange,
            symbol=row["TckrSymb"],
            isin=row.get("ISIN") or None,
            series=row.get("SctySrs") or None,
            instrument_type="EQ",
            open=_decimal_or_none(row["OpnPric"]) or Decimal(0),
            high=_decimal_or_none(row["HghPric"]) or Decimal(0),
            low=_decimal_or_none(row["LwPric"]) or Decimal(0),
            close=_decimal_or_none(row["ClsPric"]) or Decimal(0),
            prev_close=_decimal_or_none(row.get("PrvsClsgPric", "")),
            last=_decimal_or_none(row.get("LastPric", "")),
            volume=_int_or_none(row["TtlTradgVol"]) or 0,
            turnover=turnover,
            trades=_int_or_none(row.get("TtlNbOfTxsExctd", "")),
            source=source,
        )


def _parse_iso_date(s: str) -> date:
    """UDiFF dates are ISO 'YYYY-MM-DD' -- explicit format, never inferred."""
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


_CRORE = Decimal(10_000_000)

#: NSE has renamed its benchmark twice inside the covered range. Keying
#: a benchmark series on the printed name would silently split it into
#: three disconnected fragments at 2013 and 2016 -- which, in a
#: 15-year backtest, looks like the index simply ceasing to exist.
#: Verified by direct probe 2026-09-19:
#:   "S&P CNX Nifty"  .. through early 2013
#:   "CNX Nifty"      .. mid-2013 through 2015
#:   "Nifty 50"       .. 2016 onward
INDEX_CODE_BY_NAME = {
    "s&p cnx nifty": "NIFTY_50",
    "cnx nifty": "NIFTY_50",
    "nifty 50": "NIFTY_50",
    "s&p cnx nifty junior": "NIFTY_NEXT_50",
    "cnx nifty junior": "NIFTY_NEXT_50",
    "nifty next 50": "NIFTY_NEXT_50",
    "cnx bank": "NIFTY_BANK",
    "bank nifty": "NIFTY_BANK",
    "nifty bank": "NIFTY_BANK",
    "cnx 500": "NIFTY_500",
    "nifty 500": "NIFTY_500",
    "cnx it": "NIFTY_IT",
    "nifty it": "NIFTY_IT",
}


def canonical_index_code(index_name: str) -> str | None:
    """Stable identity for an index whose printed name changes over time.

    Returns None for indices we have no canonical code for -- that is
    fine and expected (the file carries ~100 indices and only a handful
    matter as benchmarks). None means "no canonical identity claimed",
    never a guess.
    """
    return INDEX_CODE_BY_NAME.get(index_name.strip().lower())


class IndexBar(BaseModel):
    """One index's OHLC for one date, canonicalised."""

    date: date
    index_name: str
    index_code: str | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    points_change: Decimal | None
    pct_change: Decimal | None
    volume: int | None
    turnover: Decimal | None  # rupees
    pe: Decimal | None
    pb: Decimal | None
    div_yield: Decimal | None
    source: str


def parse_ind_close_all(text: str, *, source: str = "nse_indices") -> list[IndexBar]:
    """Parse NSE's ind_close_all_DDMMYYYY.csv into canonical index bars.

    Two conversions happen here and nowhere else:
      - "Turnover (Rs. Cr.)" is multiplied by 10,000,000 so the
        canonical layer only ever holds rupees.
      - The printed index name is mapped to a stable index_code where
        one is known (see canonical_index_code).

    Rows whose Closing Index Value is '-' are SKIPPED, not stored with a
    null close: the file carries derived series (e.g. "Nifty50 Dividend
    Points") that legitimately have no OHLC, and a row with no close is
    not a price bar at all.
    """
    reader = csv.DictReader(io.StringIO(text), skipinitialspace=True)
    if reader.fieldnames is None:
        raise ParseError("ind_close_all CSV has no header row")
    reader.fieldnames = [name.strip() for name in reader.fieldnames]
    if "Index Name" not in reader.fieldnames:
        raise ParseError(
            f"ind_close_all CSV missing 'Index Name' column; got {reader.fieldnames}"
        )

    bars: list[IndexBar] = []
    for row in reader:
        name = (row.get("Index Name") or "").strip()
        if not name:
            continue
        close = _decimal_or_none(row.get("Closing Index Value") or "")
        if close is None:
            continue

        raw_date = (row.get("Index Date") or "").strip()
        try:
            # Explicit format string, never dateutil inference.
            bar_date = datetime.strptime(raw_date, "%d-%m-%Y").date()
        except ValueError as exc:
            raise ParseError(f"could not parse index date {raw_date!r}: {exc}") from exc

        turnover_crore = _decimal_or_none(row.get("Turnover (Rs. Cr.)") or "")
        bars.append(
            IndexBar(
                date=bar_date,
                index_name=name,
                index_code=canonical_index_code(name),
                open=_decimal_or_none(row.get("Open Index Value") or ""),
                high=_decimal_or_none(row.get("High Index Value") or ""),
                low=_decimal_or_none(row.get("Low Index Value") or ""),
                close=close,
                points_change=_decimal_or_none(row.get("Points Change") or ""),
                pct_change=_decimal_or_none(row.get("Change(%)") or ""),
                volume=_int_or_none(row.get("Volume") or ""),
                # "crore" never survives past this line.
                turnover=turnover_crore * _CRORE if turnover_crore is not None else None,
                pe=_decimal_or_none(row.get("P/E") or ""),
                pb=_decimal_or_none(row.get("P/B") or ""),
                div_yield=_decimal_or_none(row.get("Div Yield") or ""),
                source=source,
            )
        )
    return bars
