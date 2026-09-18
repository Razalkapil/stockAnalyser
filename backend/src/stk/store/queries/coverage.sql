-- Coverage and integrity queries. These feed `stk doctor`: each one
-- answers "what does the lake actually contain", so a gap shows up as
-- a reportable fact rather than as a surprise in a backtest months later.

-- name: dates_present
-- Every business date with at least one bar, for one exchange.
SELECT DISTINCT date
FROM bars_daily
WHERE exchange = ?
ORDER BY date

-- name: dates_present_in_range
SELECT DISTINCT date
FROM bars_daily
WHERE exchange = ? AND date BETWEEN ? AND ?
ORDER BY date

-- name: partition_row_counts
-- Row count per (exchange, year) partition, for comparison against the
-- _manifests sidecars. A mismatch means the file changed out-of-band.
SELECT exchange, year, count(*) AS row_count
FROM bars_daily
GROUP BY exchange, year
ORDER BY exchange, year

-- name: stale_symbols
-- Symbols whose most recent bar is older than a cutoff date -- a
-- delisting, a suspension, or an ingest that has been quietly failing
-- for one name while succeeding overall.
SELECT symbol, max(date) AS last_date
FROM bars_daily
WHERE exchange = ?
GROUP BY symbol
HAVING max(date) < ?
ORDER BY last_date, symbol

-- name: adjusted_coverage
-- Newest date present in the derived adjusted dataset, per exchange.
-- Compared against the newest corporate-action ex_date to detect an
-- adjusted series that has gone stale relative to known CAs.
SELECT exchange, max(date) AS last_date, count(*) AS row_count
FROM bars_daily_adjusted
GROUP BY exchange
ORDER BY exchange
