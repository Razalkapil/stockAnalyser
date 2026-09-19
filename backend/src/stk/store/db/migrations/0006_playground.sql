-- Phase 5: the virtual playground.
--
-- Every rupee amount here is TEXT holding an exact Decimal, never REAL: this is a ledger, and a
-- float would make cash, cost basis and P&L drift apart by fractions of a paisa over time.
-- Timestamps are ISO-8601 WITH the IST offset.

CREATE TABLE portfolios (
  portfolio_id   INTEGER PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  start_capital  TEXT NOT NULL,
  benchmark_code TEXT NOT NULL DEFAULT 'NIFTY_500',
  created_at     TEXT NOT NULL,
  archived_at    TEXT
);

CREATE TABLE orders (
  order_id            INTEGER PRIMARY KEY,
  portfolio_id        INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
  exchange            TEXT NOT NULL,
  symbol              TEXT NOT NULL,
  side                TEXT NOT NULL CHECK (side IN ('buy','sell')),
  order_type          TEXT NOT NULL CHECK (order_type IN ('MARKET','LIMIT','SL','TARGET')),
  qty                 INTEGER NOT NULL CHECK (qty > 0),
  limit_price         TEXT,
  trigger_price       TEXT,
  -- optional bracket on a BUY: when it fills, a stop-loss and/or target SELL (an OCO pair)
  -- are created for the filled quantity
  bracket_stop        TEXT,
  bracket_target      TEXT,
  oco_group           TEXT,
  status              TEXT NOT NULL
                      CHECK (status IN ('open','pending_eod','filled','cancelled','rejected')),
  status_note         TEXT,
  source_pick_id      INTEGER REFERENCES picks(pick_id),
  parent_order_id     INTEGER REFERENCES orders(order_id),
  journal_note        TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  closed_at           TEXT
);
CREATE INDEX ix_orders_active ON orders(status, exchange, symbol);
CREATE INDEX ix_orders_portfolio ON orders(portfolio_id, created_at);
CREATE INDEX ix_orders_oco ON orders(oco_group);

CREATE TABLE trades (
  trade_id        INTEGER PRIMARY KEY,
  order_id        INTEGER NOT NULL REFERENCES orders(order_id),
  portfolio_id    INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
  exchange        TEXT NOT NULL,
  symbol          TEXT NOT NULL,
  side            TEXT NOT NULL CHECK (side IN ('buy','sell')),
  qty             INTEGER NOT NULL,
  price           TEXT NOT NULL,             -- after slippage: what was actually paid/received
  raw_price       TEXT NOT NULL,             -- the touched price before slippage
  slippage_bps    TEXT NOT NULL,
  gross_value     TEXT NOT NULL,
  charges_total   TEXT NOT NULL,
  charges_json    TEXT NOT NULL,
  realised_pnl    TEXT,                      -- sells only; gross of charges
  -- Provenance of the price this fill was made from. Shown in the UI as the "delayed feed" tag.
  fill_basis      TEXT NOT NULL CHECK (fill_basis IN ('delayed_intraday','eod_fallback')),
  fill_reason     TEXT NOT NULL,
  feed_source     TEXT,
  feed_lag_s      INTEGER,
  journal_note    TEXT,
  filled_at       TEXT NOT NULL
);
CREATE INDEX ix_trades_portfolio ON trades(portfolio_id, filled_at);

CREATE TABLE positions (
  portfolio_id   INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
  exchange       TEXT NOT NULL,
  symbol         TEXT NOT NULL,
  qty            INTEGER NOT NULL,
  avg_cost       TEXT NOT NULL,              -- excludes charges (tracked separately)
  realised_pnl   TEXT NOT NULL,              -- gross of charges
  opened_at      TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  PRIMARY KEY (portfolio_id, exchange, symbol)
) WITHOUT ROWID;

-- Every movement of cash. balance_after makes the ledger auditable line by line, and cash is
-- always the last row's balance -- there is no separate "cash" column to fall out of step.
CREATE TABLE cash_ledger (
  entry_id       INTEGER PRIMARY KEY,
  portfolio_id   INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
  ts             TEXT NOT NULL,
  kind           TEXT NOT NULL
                 CHECK (kind IN ('deposit','buy','sell','charges','dividend','ca_adjustment')),
  amount         TEXT NOT NULL,              -- signed: credits positive, debits negative
  balance_after  TEXT NOT NULL,
  ref_trade_id   INTEGER REFERENCES trades(trade_id),
  ref_ca_key     TEXT,
  note           TEXT
);
CREATE INDEX ix_cash_portfolio ON cash_ledger(portfolio_id, entry_id);

-- Idempotency for corporate actions: one row per (portfolio, action), so re-running the
-- adjustment for a date can never apply a split or credit a dividend twice.
CREATE TABLE position_ca_events (
  id             INTEGER PRIMARY KEY,
  portfolio_id   INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
  ca_key         TEXT NOT NULL,              -- economic identity, not source_hash
  exchange       TEXT NOT NULL,
  symbol         TEXT NOT NULL,
  kind           TEXT NOT NULL,
  detail_json    TEXT NOT NULL,
  applied_at     TEXT NOT NULL,
  UNIQUE (portfolio_id, ca_key)
);

CREATE TABLE portfolio_daily (
  portfolio_id   INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
  date           TEXT NOT NULL,
  value          TEXT NOT NULL,
  cash           TEXT NOT NULL,
  invested       TEXT NOT NULL,
  bench_close    REAL,
  PRIMARY KEY (portfolio_id, date)
) WITHOUT ROWID;

CREATE TABLE poller_runs (
  run_id         INTEGER PRIMARY KEY,
  started_at     TEXT NOT NULL,
  finished_at    TEXT,
  symbols        INTEGER NOT NULL DEFAULT 0,
  fills          INTEGER NOT NULL DEFAULT 0,
  status         TEXT NOT NULL CHECK (status IN ('ok','stale','failed','idle')),
  newest_candle  TEXT,
  lag_s          INTEGER,
  error          TEXT
);
