-- What each traded symbol IS: an operating company's share, or a fund (ETF / mutual-fund unit).
--
-- Found by running real scans: bhavcopy lists ETFs (GOLDBEES, NIFTYBEES, ...) in the EQ series
-- beside stocks, and the security master (EQUITY_L) does not list them at all -- so without this
-- a "stock picker" recommends gold ETFs and index funds, and a momentum backtest trades them.
-- The ISIN is the reliable signal: INE... = a company's securities, INF... = funds. The price
-- files carry no ISIN before 2024-07, so it comes from NSE's UDiFF bhavcopy (which does).

CREATE TABLE instrument_class (
  exchange     TEXT NOT NULL,
  symbol       TEXT NOT NULL,
  isin         TEXT,
  class        TEXT NOT NULL CHECK (class IN ('equity','fund','other')),
  source_date  TEXT NOT NULL,           -- the UDiFF file this was read from
  updated_at   TEXT NOT NULL,
  PRIMARY KEY (exchange, symbol)
);
CREATE INDEX ix_instrument_class_class ON instrument_class(exchange, class);
