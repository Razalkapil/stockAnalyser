"""Canonical Arrow schema for daily bars.

NSE UDiFF, BSE UDiFF and sec_bhavdata_full all normalise into exactly
this schema (see ``stk.ingest.normalise``) before being written to
parquet. Field-for-field, this mirrors ``stk.providers.base.CanonicalBar``.

Design notes (see docs/adr and the build plan for full justification):
- Partitioned by exchange then year, sorted by (symbol, date) within
  each partition file -- NOT by month. A 15-year dataset is ~150-200MB
  total; year partitioning keeps both the "last 60 days, all symbols"
  screen query and the "all history, one symbol" stock-view query fast
  via Parquet row-group statistics.
- Unadjusted prices are the only thing ever written here. Corporate
  actions never rewrite bars_daily -- see adjustment_factors and
  bars_daily_adjusted instead.
- delivery_qty/delivery_pct are nullable and MUST be null (not 0) when
  the source reports "-": zero delivery and unreported delivery are
  different facts.
"""

from __future__ import annotations

import pyarrow as pa

ROW_GROUP_SIZE = 100_000

BARS_DAILY_SCHEMA = pa.schema(
    [
        pa.field("date", pa.date32(), nullable=False),
        pa.field("exchange", pa.dictionary(pa.int8(), pa.string()), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("security_id", pa.int32(), nullable=True),
        pa.field("isin", pa.string(), nullable=True),
        pa.field("series", pa.dictionary(pa.int8(), pa.string()), nullable=True),
        pa.field("instrument_type", pa.dictionary(pa.int8(), pa.string()), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("prev_close", pa.float64(), nullable=True),
        pa.field("last", pa.float64(), nullable=True),
        pa.field("vwap", pa.float64(), nullable=True),
        pa.field("volume", pa.int64(), nullable=False),
        pa.field("turnover", pa.float64(), nullable=False),  # rupees, always
        pa.field("trades", pa.int64(), nullable=True),
        pa.field("delivery_qty", pa.int64(), nullable=True),  # null (not 0) if unreported
        pa.field("delivery_pct", pa.float64(), nullable=True),
        pa.field("settle_price", pa.float64(), nullable=True),
        pa.field("source", pa.dictionary(pa.int8(), pa.string()), nullable=False),
        pa.field("ingested_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

# Adjustment factors: (exchange, symbol, effective_date) -> cumulative
# price/volume multipliers, derived from corporate_actions. Small table
# (thousands, not millions, of rows) -- not year-partitioned.
ADJUSTMENT_FACTORS_SCHEMA = pa.schema(
    [
        pa.field("exchange", pa.dictionary(pa.int8(), pa.string()), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("effective_date", pa.date32(), nullable=False),
        pa.field("price_factor", pa.float64(), nullable=False),
        pa.field("volume_factor", pa.float64(), nullable=False),
        pa.field("cumulative_price_factor", pa.float64(), nullable=False),
        pa.field("cumulative_volume_factor", pa.float64(), nullable=False),
    ]
)

# Liquidity universe features, one row per (exchange, symbol, date).
LIQUIDITY_DAILY_SCHEMA = pa.schema(
    [
        pa.field("date", pa.date32(), nullable=False),
        pa.field("exchange", pa.dictionary(pa.int8(), pa.string()), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("security_id", pa.int32(), nullable=True),
        pa.field("median_turnover_20d", pa.float64(), nullable=True),
        pa.field("median_volume_20d", pa.float64(), nullable=True),
        pa.field("median_trades_20d", pa.float64(), nullable=True),
        pa.field("median_delivery_pct_20d", pa.float64(), nullable=True),
        pa.field("avg_price_20d", pa.float64(), nullable=True),
        pa.field("listed_days", pa.int32(), nullable=False),
        pa.field("is_liquid", pa.bool_(), nullable=False),
    ]
)
