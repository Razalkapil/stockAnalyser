"""NSE security-master and price-band provider.

Two separate nsearchives static CSVs, both fetched the same way as the
legacy price archive (fetch_csv_file -- no cookie handshake needed):

  - EQUITY_L.csv: the active-listing snapshot (symbol/ISIN/name/lot size).
  - sec_list.csv: the daily price-band list, used for circuit-lock
    detection (not master data per se, but served from the same host
    in the same shape, so it lives on the same provider per
    SecurityMasterProvider.fetch_price_bands's optional-capability design).
  - symbolchange.csv: every symbol change since ~2000 (company, old, new, date). EQUITY_L only
    knows today's symbols, so without this a rename older than our first master snapshot is
    invisible (MINDAIND -> UNOMINDA, 2022). It has NO header row, so its shape is checked
    row by row in parse_symbol_changes rather than by a header token.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from stk.core.errors import ParseError
from stk.core.time import parse_ddmmmyyyy, today_ist
from stk.providers.base import (
    MasterRecord,
    PriceBand,
    RawArtifact,
    SecurityMasterProvider,
    SymbolChange,
)
from stk.providers.nse.archives import fetch_csv_file

_EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
_SEC_LIST_URL = "https://nsearchives.nseindia.com/content/equities/sec_list.csv"
_SYMBOL_CHANGE_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
SOURCE = "nse_equity_l"


class NseSecurityMasterProvider(SecurityMasterProvider):
    """SecurityMasterProvider backed by NSE's EQUITY_L.csv / sec_list.csv."""

    def fetch_master(self) -> list[MasterRecord]:
        artifact = fetch_csv_file(
            _EQUITY_L_URL, source=SOURCE, business_date=None, expected_header_token="SYMBOL"
        )
        text = artifact.content.decode("utf-8", errors="strict")
        reader = csv.DictReader(io.StringIO(text), skipinitialspace=True)

        records = []
        for raw_row in reader:
            row = {k.strip(): v.strip() for k, v in raw_row.items() if k}
            paid_up_value = row.get("PAID UP VALUE", "").strip()
            market_lot = row.get("MARKET LOT", "").strip()
            records.append(
                MasterRecord(
                    isin=row["ISIN NUMBER"],
                    symbol=row["SYMBOL"],
                    company_name=row["NAME OF COMPANY"],
                    exchange="NSE",
                    series=row.get("SERIES") or None,
                    face_value=Decimal(paid_up_value) if paid_up_value else None,
                    lot_size=int(market_lot) if market_lot else None,
                    listing_date=parse_ddmmmyyyy(row["DATE OF LISTING"])
                    if row.get("DATE OF LISTING")
                    else None,
                )
            )
        return records

    def fetch_price_bands(self) -> list[PriceBand]:
        artifact = fetch_csv_file(
            _SEC_LIST_URL, source="nse_sec_list", business_date=None, expected_header_token="Symbol"
        )
        text = artifact.content.decode("utf-8", errors="strict")
        reader = csv.DictReader(io.StringIO(text), skipinitialspace=True)

        bands = []
        for raw_row in reader:
            row = {k.strip(): v.strip() for k, v in raw_row.items() if k}
            band_raw = row.get("Band", "").strip()
            band_pct = int(band_raw) if band_raw.isdigit() else None
            bands.append(
                PriceBand(symbol=row["Symbol"], series=row.get("Series") or None, band_pct=band_pct)
            )
        return bands

    def fetch_symbol_changes_artifact(self) -> RawArtifact:
        # No header row, so the only first-line token to demand is the delimiter (an HTML shell
        # has none); the real shape check is per row, in parse_symbol_changes. Dated today: the
        # file is appended to, so each day's copy is its own raw artifact.
        return fetch_csv_file(
            _SYMBOL_CHANGE_URL, source="nse_symbolchange", business_date=today_ist(),
            expected_header_token=",",
        )

    def parse_symbol_changes(self, artifact: RawArtifact) -> list[SymbolChange]:
        text = artifact.content.decode("utf-8-sig", errors="strict")
        changes = []
        for line_no, row in enumerate(csv.reader(io.StringIO(text)), start=1):
            if not any(cell.strip() for cell in row):
                continue
            if len(row) != 4:
                raise ParseError(f"symbolchange.csv line {line_no}: expected 4 fields, got {row!r}")
            name, old, new, when = (cell.strip() for cell in row)
            if not old or not new:
                raise ParseError(f"symbolchange.csv line {line_no}: blank symbol in {row!r}")
            try:
                effective = parse_ddmmmyyyy(when)
            except ValueError as exc:
                raise ParseError(f"symbolchange.csv line {line_no}: bad date {when!r}") from exc
            changes.append(SymbolChange(
                exchange="NSE", old_symbol=old, new_symbol=new, effective_date=effective,
                company_name=name or None,
            ))
        if not changes:
            raise ParseError("symbolchange.csv parsed to zero rows")
        return changes
