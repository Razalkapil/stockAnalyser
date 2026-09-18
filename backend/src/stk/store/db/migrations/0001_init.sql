-- Phase 1 schema. Forward-only migration; never edit after it has
-- shipped -- add a new numbered file instead.

CREATE TABLE securities (
  security_id       INTEGER PRIMARY KEY,
  isin              TEXT NOT NULL UNIQUE,
  canonical_symbol  TEXT NOT NULL,
  company_name      TEXT NOT NULL,
  primary_exchange  TEXT NOT NULL CHECK (primary_exchange IN ('NSE','BSE')),
  face_value        REAL,
  status            TEXT NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE','SUSPENDED','DELISTED')),
  first_seen_on     TEXT NOT NULL,
  last_seen_on      TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);
CREATE INDEX ix_securities_symbol ON securities(canonical_symbol);
CREATE INDEX ix_securities_status ON securities(status);

CREATE TABLE listings (
  listing_id        INTEGER PRIMARY KEY,
  security_id       INTEGER NOT NULL REFERENCES securities(security_id),
  exchange          TEXT NOT NULL CHECK (exchange IN ('NSE','BSE')),
  symbol            TEXT NOT NULL,
  exchange_token    TEXT,
  series            TEXT,
  listing_date      TEXT,
  lot_size          INTEGER,
  price_band_pct    REAL,
  is_tradeable_intraday INTEGER NOT NULL DEFAULT 1,
  status            TEXT NOT NULL DEFAULT 'ACTIVE',
  source            TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  UNIQUE (exchange, symbol, series)
);
CREATE INDEX ix_listings_security ON listings(security_id);

CREATE TABLE symbol_history (
  id                INTEGER PRIMARY KEY,
  security_id       INTEGER NOT NULL REFERENCES securities(security_id),
  exchange          TEXT NOT NULL,
  symbol            TEXT NOT NULL,
  valid_from        TEXT NOT NULL,
  valid_to          TEXT,
  UNIQUE (exchange, symbol, valid_from)
);
CREATE INDEX ix_symbol_history_lookup ON symbol_history(exchange, symbol, valid_from);

CREATE TABLE corporate_actions (
  ca_id             INTEGER PRIMARY KEY,
  security_id       INTEGER REFERENCES securities(security_id),
  isin              TEXT,
  symbol            TEXT NOT NULL,
  exchange          TEXT NOT NULL,
  ex_date           TEXT,
  record_date       TEXT,
  bc_start_date     TEXT,
  bc_end_date       TEXT,
  subject_raw       TEXT NOT NULL,
  action_type       TEXT,
  dividend_per_share REAL,
  ratio_numerator   INTEGER,
  ratio_denominator INTEGER,
  face_value_from   REAL,
  face_value_to     REAL,
  price_factor      REAL,
  volume_factor     REAL,
  parse_status      TEXT NOT NULL CHECK (parse_status IN ('parsed','ambiguous','unparsed')),
  parser_version    INTEGER NOT NULL,
  source            TEXT NOT NULL,
  source_hash       TEXT NOT NULL,
  captured_at       TEXT NOT NULL,
  UNIQUE (source, source_hash)
);
CREATE INDEX ix_ca_security_ex ON corporate_actions(security_id, ex_date);
CREATE INDEX ix_ca_parse_status ON corporate_actions(parse_status);
CREATE INDEX ix_ca_exdate ON corporate_actions(ex_date);

CREATE TABLE fundamentals_snapshots (
  snapshot_id       INTEGER PRIMARY KEY,
  security_id       INTEGER NOT NULL REFERENCES securities(security_id),
  provider          TEXT NOT NULL,
  statement_type    TEXT NOT NULL,
  period_type       TEXT NOT NULL CHECK (period_type IN ('Q','H','FY','TTM')),
  period_end        TEXT NOT NULL,
  fiscal_year       INTEGER,
  fiscal_quarter    INTEGER,
  consolidated      INTEGER,
  audited           INTEGER,
  filing_system     TEXT,
  broadcast_at      TEXT,
  captured_at       TEXT NOT NULL,
  is_approximate    INTEGER NOT NULL DEFAULT 0,
  is_restated       INTEGER NOT NULL DEFAULT 0,
  currency          TEXT NOT NULL DEFAULT 'INR',
  unit_multiplier   REAL NOT NULL DEFAULT 1.0,
  data_json         TEXT NOT NULL,
  source_url        TEXT,
  source_hash       TEXT NOT NULL,
  parser_version    INTEGER NOT NULL,
  UNIQUE (provider, security_id, statement_type, period_type, period_end, consolidated, source_hash)
);
CREATE INDEX ix_fund_sec_period ON fundamentals_snapshots(security_id, period_end DESC);
CREATE INDEX ix_fund_provider ON fundamentals_snapshots(provider, captured_at);

CREATE TABLE job_runs (
  run_id            INTEGER PRIMARY KEY,
  job_name          TEXT NOT NULL,
  business_date     TEXT,
  status            TEXT NOT NULL
                    CHECK (status IN ('running','success','degraded','failed','skipped_holiday')),
  started_at        TEXT NOT NULL,
  finished_at       TEXT,
  rows_in           INTEGER,
  rows_written      INTEGER,
  rows_rejected     INTEGER,
  attempt           INTEGER NOT NULL DEFAULT 1,
  error_type        TEXT,
  error_message     TEXT,
  traceback         TEXT,
  metrics_json      TEXT,
  code_version      TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_job_success ON job_runs(job_name, business_date, attempt);
CREATE INDEX ix_job_lookup ON job_runs(job_name, business_date, status);

CREATE TABLE raw_artifacts (
  artifact_id       INTEGER PRIMARY KEY,
  source            TEXT NOT NULL,
  business_date     TEXT,
  url               TEXT NOT NULL,
  path              TEXT NOT NULL,
  sha256            TEXT NOT NULL,
  bytes             INTEGER NOT NULL,
  content_type      TEXT,
  http_status       INTEGER NOT NULL,
  fetched_at        TEXT NOT NULL,
  validation        TEXT NOT NULL CHECK (validation IN ('ok','wrong_content_type','magic_mismatch','empty')),
  UNIQUE (source, business_date, sha256)
);

CREATE TABLE trading_calendar (
  cal_date          TEXT NOT NULL,
  exchange          TEXT NOT NULL DEFAULT 'NSE',
  segment           TEXT NOT NULL DEFAULT 'CBM',
  is_trading_day    INTEGER NOT NULL,
  holiday_description TEXT,
  source            TEXT NOT NULL,
  captured_at       TEXT NOT NULL,
  PRIMARY KEY (cal_date, exchange, segment)
);

CREATE TABLE universe_current (
  security_id       INTEGER PRIMARY KEY REFERENCES securities(security_id),
  as_of_date        TEXT NOT NULL,
  is_liquid         INTEGER NOT NULL,
  reason            TEXT
);
