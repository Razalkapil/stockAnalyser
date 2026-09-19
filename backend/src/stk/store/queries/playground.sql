-- Reads for the paper-trading playground. UNADJUSTED prices throughout: a fill is "what you
-- would actually have paid", which is bars_daily, never the back-adjusted series.

-- name: adv_for_symbols
-- Median turnover (rupees) over each symbol's last N sessions on or before a date: the input to
-- the same liquidity-tiered slippage the backtest uses. Params, in order: tradeable_series,
-- symbols, exchange, as_of, lookback_days.
WITH p AS (SELECT ?::VARCHAR[] AS series_list, ?::VARCHAR[] AS symbol_list),
ranked AS (
    SELECT b.symbol, b.turnover,
           row_number() OVER (PARTITION BY b.symbol, b.date
                              ORDER BY list_position(p.series_list, b.series)) AS series_rn,
           b.date
    FROM bars_daily b CROSS JOIN p
    WHERE b.exchange = ? AND b.date <= ?
      AND list_contains(p.series_list, b.series)
      AND list_contains(p.symbol_list, b.symbol)
),
one_per_day AS (
    SELECT symbol, date, turnover,
           row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS day_rn
    FROM ranked WHERE series_rn = 1
)
SELECT symbol, median(turnover) AS adv_turnover
FROM one_per_day WHERE day_rn <= ?
GROUP BY symbol

-- name: bars_on_day
-- One unadjusted bar per symbol for a date (tradeable series by precedence), with the previous
-- close the exchange reported -- what circuit-lock detection needs.
-- Params: tradeable_series, symbols, exchange, day.
WITH p AS (SELECT ?::VARCHAR[] AS series_list, ?::VARCHAR[] AS symbol_list),
ranked AS (
    SELECT b.symbol, b.open, b.high, b.low, b.close, b.prev_close, b.volume,
           row_number() OVER (PARTITION BY b.symbol
                              ORDER BY list_position(p.series_list, b.series)) AS rn
    FROM bars_daily b CROSS JOIN p
    WHERE b.exchange = ? AND b.date = ?
      AND list_contains(p.series_list, b.series)
      AND list_contains(p.symbol_list, b.symbol)
)
SELECT symbol, open, high, low, close, prev_close, volume FROM ranked WHERE rn = 1

-- name: last_close_on_or_before
-- Each symbol's most recent unadjusted close on or before a date, and which date that was.
-- Params: tradeable_series, symbols, exchange, as_of.
WITH p AS (SELECT ?::VARCHAR[] AS series_list, ?::VARCHAR[] AS symbol_list),
ranked AS (
    SELECT b.symbol, b.date, b.close,
           row_number() OVER (PARTITION BY b.symbol
                              ORDER BY b.date DESC, list_position(p.series_list, b.series)) AS rn
    FROM bars_daily b CROSS JOIN p
    WHERE b.exchange = ? AND b.date <= ?
      AND list_contains(p.series_list, b.series)
      AND list_contains(p.symbol_list, b.symbol)
)
SELECT symbol, date, close FROM ranked WHERE rn = 1
