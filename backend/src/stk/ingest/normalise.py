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
