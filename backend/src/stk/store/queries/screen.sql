-- Universe / screening queries.

-- name: liquidity_metrics
-- Trailing-window liquidity metrics per symbol, computed straight from
-- bars_daily. Lifted verbatim out of ingest.liquidity's inline DuckDB
-- call so the SQL is reviewable next to the other named queries.
--
-- `listed_days` deliberately counts the symbol's FULL history, not just
-- the trailing window: it exists to reject freshly-listed names, which
-- is a question about the whole series. is_liquid itself is NOT decided
-- here -- that rule is the pure domain.universe.is_liquid function.
--
-- Params: as_of_date, lookback_days
WITH scanned AS (
    SELECT * FROM bars_daily
    WHERE exchange = ? AND date <= ?
),
ranked AS (
    SELECT *, row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
    FROM scanned
),
windowed AS (
    SELECT * FROM ranked WHERE rn <= ?
),
listed AS (
    SELECT symbol, COUNT(DISTINCT date) AS listed_days
    FROM scanned
    GROUP BY symbol
)
SELECT
    w.symbol AS symbol,
    median(w.turnover) AS median_turnover_20d,
    median(w.volume) AS median_volume_20d,
    median(w.trades) AS median_trades_20d,
    median(w.delivery_pct) AS median_delivery_pct_20d,
    avg(w.close) AS avg_price_20d,
    l.listed_days AS listed_days
FROM windowed w
JOIN listed l USING (symbol)
GROUP BY w.symbol, l.listed_days
ORDER BY w.symbol

-- name: liquid_universe_as_of
-- The tradeable universe for a date, resolved to real securities.
-- A company listed on both exchanges appears once, on its
-- primary_exchange -- the build plan's "one-series-per-company
-- resolution happens at QUERY time, not at ingest".
SELECT
    s.security_id,
    s.isin,
    s.canonical_symbol,
    s.company_name,
    s.primary_exchange,
    f.exchange,
    f.symbol,
    f.date AS as_of_date,
    f.median_turnover_20d,
    f.median_volume_20d,
    f.listed_days
FROM liquidity_daily f
JOIN dim_listings l
  ON l.exchange = f.exchange AND l.symbol = f.symbol
JOIN dim_securities s
  ON s.security_id = l.security_id
WHERE f.date = ?
  AND f.is_liquid
  AND s.primary_exchange = f.exchange
ORDER BY s.canonical_symbol
