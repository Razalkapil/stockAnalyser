"""NSE security-master and price-band provider.

Two separate nsearchives static CSVs, both fetched the same way as the
legacy price archive (fetch_csv_file -- no cookie handshake needed):

  - EQUITY_L.csv: the active-listing snapshot (symbol/ISIN/name/lot size).
  - sec_list.csv: the daily price-band list, used for circuit-lock
    detection (not master data per se, but served from the same host
    in the same shape, so it lives on the same provider per
    SecurityMasterProvider.fetch_price_bands's optional-capability design).
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from stk.core.time import parse_ddmmmyyyy
from stk.providers.base import MasterRecord, PriceBand, SecurityMasterProvider
from stk.providers.nse.archives import fetch_csv_file

_EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
_SEC_LIST_URL = "https://nsearchives.nseindia.com/content/equities/sec_list.csv"
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
