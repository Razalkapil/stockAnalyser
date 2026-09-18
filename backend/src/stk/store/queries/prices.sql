-- Price reads. Every consumer of prices goes through here rather than
-- opening a parquet path directly (see stk.store.duck's docstring).
--
-- The adjusted_* queries read bars_daily_adjusted (signals, charts,
-- backtests); the unadjusted_* queries read bars_daily ("what did I
-- actually pay"). Picking the wrong one is the single most consequential
-- mistake available here, so the names say which is which.

-- name: adjusted_bars_for_symbol
SELECT *
FROM bars_daily_adjusted
WHERE exchange = ?
  AND symbol = ?
  AND date BETWEEN ? AND ?
ORDER BY date

-- name: unadjusted_bars_for_symbol
SELECT *
FROM bars_daily
WHERE exchange = ?
  AND symbol = ?
  AND date BETWEEN ? AND ?
ORDER BY date

-- name: latest_bar_per_symbol
SELECT symbol, max(date) AS last_date
FROM bars_daily
WHERE exchange = ?
GROUP BY symbol
ORDER BY symbol

-- name: bars_with_resolved_identity
-- bars_daily enriched with the securities master. `security_id`/`isin`
-- on the bar itself are whatever the SOURCE reported (null for every
-- NSE sec_bhavdata row, which carries no ISIN); the resolved_* columns
-- come from the dimension join and are keyed by the symbol AS OF the
-- bar's own date via symbol_history, so a bar written under a since-
-- renamed symbol still resolves. COALESCE prefers the source value
-- when it exists -- the exchange's own identification of its own row
-- outranks our reconstruction of it.
SELECT
    b.*,
    COALESCE(b.security_id, h.security_id, l.security_id) AS resolved_security_id,
    COALESCE(b.isin, s.isin)                              AS resolved_isin
FROM bars_daily b
LEFT JOIN dim_symbol_history h
       ON h.exchange = b.exchange
      AND h.symbol = b.symbol
      AND h.valid_from <= CAST(b.date AS VARCHAR)
      AND (h.valid_to IS NULL OR CAST(b.date AS VARCHAR) < h.valid_to)
LEFT JOIN dim_listings l
       ON l.exchange = b.exchange
      AND l.symbol = b.symbol
LEFT JOIN dim_securities s
       ON s.security_id = COALESCE(b.security_id, h.security_id, l.security_id)
WHERE b.exchange = ?
  AND b.date BETWEEN ? AND ?


-- name: benchmark_series
-- A continuous benchmark series keyed on the CANONICAL index code, not
-- the printed name: NSE renamed the Nifty twice inside the covered
-- range ("S&P CNX Nifty" -> "CNX Nifty" -> "Nifty 50"), so filtering
-- on index_name silently returns a fragment instead of a series.
SELECT date, index_code, index_name, open, high, low, close, pct_change
FROM indices_daily
WHERE index_code = ?
  AND date BETWEEN ? AND ?
ORDER BY date

-- name: backtest_panel
-- Adjusted daily bars for one exchange over a date range: the raw material of a
-- backtest. Params: tradeable_series (a list, in PRECEDENCE order), exchange,
-- start, end.
--
-- ONE ROW PER (symbol, date), by construction. bars_daily_adjusted is keyed by
-- (exchange, symbol, SERIES, date), and NSE really does publish several series for
-- one symbol on one day (WIPRO: EQ plus T0; also P1, N3, ...), so reading the table
-- raw would hand the engine two bars for one stock -- one of them a 3-share stub.
-- Only the tradeable series are kept, and where a symbol has several the earliest in
-- the precedence list wins (EQ over BE over BZ).
--
-- cumulative_price_factor rides along so the unadjusted close (close_raw, used for
-- absolute-rupee filters) can be recovered; without it close_raw is silently just
-- the adjusted close.
WITH p AS (SELECT ?::VARCHAR[] AS series_list),
ranked AS (
    SELECT b.date, b.symbol, b.series, b.open, b.high, b.low, b.close, b.volume, b.turnover,
           b.delivery_pct, b.trades, b.cumulative_price_factor,
           row_number() OVER (
               PARTITION BY b.symbol, b.date ORDER BY list_position(p.series_list, b.series)
           ) AS rn
    FROM bars_daily_adjusted b CROSS JOIN p
    WHERE b.exchange = ?
      AND b.date BETWEEN ? AND ?
      AND list_contains(p.series_list, b.series)
)
SELECT date, symbol, series, open, high, low, close, volume, turnover,
       delivery_pct, trades, cumulative_price_factor
FROM ranked
WHERE rn = 1
ORDER BY date, symbol
