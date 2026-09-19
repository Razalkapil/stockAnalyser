-- Phase 4: live picks, their daily marks and outcomes, and API tokens.
--
-- A pick is what a live strategy flagged on a signal date. Money-looking columns
-- here (ref/stop/target) are REAL and are DISPLAY values in unadjusted rupees as
-- of the signal date -- what a person would actually see and pay. Tracking never
-- uses them: it works on RATIOS of the back-adjusted series (stop_pct/target_pct),
-- so a split or bonus during the hold cannot fake a crash.

CREATE TABLE picks (
  pick_id              INTEGER PRIMARY KEY,
  strategy_id          INTEGER NOT NULL REFERENCES strategies(strategy_id),
  strategy_version_id  INTEGER NOT NULL REFERENCES strategy_versions(version_id),
  exchange             TEXT NOT NULL,
  symbol               TEXT NOT NULL,
  horizon              TEXT NOT NULL
                       CHECK (horizon IN ('short_term','swing','momentum','long_term')),
  signal_date          TEXT NOT NULL,
  ref_price            REAL NOT NULL,      -- unadjusted close on the signal date
  stop_price           REAL,
  target_price         REAL,
  stop_pct             REAL,               -- fraction below entry (tracking uses this)
  target_pct           REAL,
  hold_days            INTEGER NOT NULL,
  window_end           TEXT NOT NULL,      -- approximate last day of the holding window
  score                REAL NOT NULL,
  rank_in_strategy     INTEGER NOT NULL,
  reason               TEXT NOT NULL,
  conflict             TEXT,               -- filled by the AI evening review (phase 6)
  ai_reason            TEXT,               -- ditto
  status               TEXT NOT NULL
                       CHECK (status IN ('pending_entry','open','closed','void')),
  created_at           TEXT NOT NULL,
  UNIQUE (strategy_version_id, exchange, symbol, signal_date)
);
CREATE INDEX ix_picks_signal ON picks(signal_date, horizon);
CREATE INDEX ix_picks_status ON picks(status);
CREATE INDEX ix_picks_strategy ON picks(strategy_id, signal_date);

-- One row per session a pick was held: its net return marked to that day's close.
CREATE TABLE pick_marks (
  pick_id      INTEGER NOT NULL REFERENCES picks(pick_id) ON DELETE CASCADE,
  date         TEXT NOT NULL,
  net_return   REAL NOT NULL,
  PRIMARY KEY (pick_id, date)
) WITHOUT ROWID;

CREATE TABLE pick_outcomes (
  pick_id       INTEGER PRIMARY KEY REFERENCES picks(pick_id) ON DELETE CASCADE,
  entry_date    TEXT,
  entry_price   REAL,                      -- back-adjusted, as of the latest rebuild
  exit_date     TEXT,
  exit_price    REAL,
  exit_reason   TEXT NOT NULL CHECK (exit_reason IN ('stop','target','time','void')),
  net_return    REAL,
  holding_days  INTEGER,
  mfe           REAL,
  mae           REAL,
  closed_at     TEXT NOT NULL
);

-- Single-user auth. Only a SHA-256 of the token is stored; the token itself is shown once.
CREATE TABLE api_tokens (
  token_id      INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  token_sha256  TEXT NOT NULL UNIQUE,
  created_at    TEXT NOT NULL,
  last_used_at  TEXT,
  revoked_at    TEXT
);
