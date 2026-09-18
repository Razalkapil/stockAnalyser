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

# Back-adjusted bars: bars_daily with every price multiplied by the
# cumulative price factor of all corporate actions AFTER that bar, and
# every quantity by the cumulative volume factor. DERIVED and fully
# rebuildable -- bars_daily is never rewritten.
#
# THE RULE (build plan, restated because it is easy to get backwards):
# any number shown to a user for "what did I pay" comes from
# bars_daily; any number fed to a signal, a backtest or a chart comes
# from bars_daily_adjusted.
#
# The two factor columns ride along on every row so an adjusted bar is
# self-describing: the unadjusted price is always recoverable by
# dividing, and which corporate actions were applied is auditable
# without re-deriving the timeline. Two float64s per row is a cheap
# price for that.
BARS_DAILY_ADJUSTED_SCHEMA = pa.schema(
    [
        *BARS_DAILY_SCHEMA,
        pa.field("cumulative_price_factor", pa.float64(), nullable=False),
        pa.field("cumulative_volume_factor", pa.float64(), nullable=False),
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


# Index OHLC, one row per (index_name, date). Year-partitioned only --
# there is no exchange dimension: this comes from NSE's index archive,
# and BSE index data is a documented gap (docs/data-sources.md).
#
# `index_name` is what the file literally said; `index_code` is the
# canonical identity. Those differ for a reason that matters: NSE has
# renamed the benchmark twice inside the covered range ("S&P CNX
# Nifty" -> "CNX Nifty" -> "Nifty 50"), so a benchmark series keyed on
# the printed name silently breaks into three disconnected fragments.
#
# `turnover` is RUPEES, converted from the file's "Rs. Cr." at the
# parser boundary -- the same discipline as the lakhs rule for
# sec_bhavdata. The word "crore" never survives into the canonical layer.
INDICES_DAILY_SCHEMA = pa.schema(
    [
        pa.field("date", pa.date32(), nullable=False),
        pa.field("index_name", pa.string(), nullable=False),
        pa.field("index_code", pa.dictionary(pa.int8(), pa.string()), nullable=True),
        pa.field("open", pa.float64(), nullable=True),
        pa.field("high", pa.float64(), nullable=True),
        pa.field("low", pa.float64(), nullable=True),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("points_change", pa.float64(), nullable=True),
        pa.field("pct_change", pa.float64(), nullable=True),
        pa.field("volume", pa.int64(), nullable=True),
        pa.field("turnover", pa.float64(), nullable=True),  # rupees, always
        pa.field("pe", pa.float64(), nullable=True),
        pa.field("pb", pa.float64(), nullable=True),
        pa.field("div_yield", pa.float64(), nullable=True),
        pa.field("source", pa.dictionary(pa.int8(), pa.string()), nullable=False),
        pa.field("ingested_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)
