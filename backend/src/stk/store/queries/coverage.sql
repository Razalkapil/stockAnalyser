-- Coverage and integrity queries. These feed `stk doctor`: each one
-- answers "what does the lake actually contain", so a gap shows up as
-- a reportable fact rather than as a surprise in a backtest months later.

-- name: dates_present
-- Every business date with at least one bar, for one exchange.
SELECT DISTINCT date
FROM bars_daily
WHERE exchange = ?
ORDER BY date

-- name: latest_date
-- The newest date with at least one bar, for one exchange -- the starting point for a
-- catch-up run to compute what has been missed since.
SELECT max(date) FROM bars_daily WHERE exchange = ?

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

-- name: adjusted_jumps
-- Next-session moves in the ADJUSTED equity series outside [low, high] -- almost always an
-- unadjusted corporate action, not a real move (NSE bands cap most stocks at 20%). "Next
-- session" means consecutive dates of the dataset itself, so a symbol returning after a gap
-- (suspension, missing file) is not mistaken for a jump. Params: exchange, exchange, low, high.
WITH days AS (
    SELECT date, row_number() OVER (ORDER BY date) AS n
    FROM (SELECT DISTINCT date FROM bars_daily_adjusted WHERE exchange = ?)
),
eq AS (
    SELECT a.symbol, a.date, a.close, d.n,
           lag(a.close) OVER w AS prior_close,
           lag(d.n) OVER w AS prior_n
    FROM bars_daily_adjusted a JOIN days d ON d.date = a.date
    WHERE a.exchange = ? AND a.series = 'EQ'
    WINDOW w AS (PARTITION BY a.symbol ORDER BY a.date)
)
SELECT symbol, date, prior_close, close, close / prior_close AS ratio
FROM eq
WHERE n = prior_n + 1 AND prior_close > 0
  AND (close / prior_close < ? OR close / prior_close > ?)
ORDER BY date, symbol

-- name: dates_without_benchmark
-- Trading days with prices but no close for the benchmark index, from the first day the
-- benchmark exists (earlier history is a known limit of the free archive, not a gap).
-- Params: exchange, index_code, index_code.
SELECT DISTINCT b.date
FROM bars_daily b
WHERE b.exchange = ?
  AND b.date >= (SELECT min(date) FROM indices_daily WHERE index_code = ?)
  AND b.date NOT IN (SELECT date FROM indices_daily WHERE index_code = ?)
ORDER BY b.date
