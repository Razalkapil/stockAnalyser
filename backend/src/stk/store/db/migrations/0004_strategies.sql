-- Phase 3: strategies, their immutable versions, and status history.
--
-- A strategy's spec is data (DSL JSON). Editing a spec creates a NEW version;
-- versions are never mutated, so a backtest run stays attributable to exactly
-- the rules it ran.

CREATE TABLE strategies (
  strategy_id        INTEGER PRIMARY KEY,
  slug               TEXT NOT NULL UNIQUE,
  name               TEXT NOT NULL,
  horizon            TEXT NOT NULL
                     CHECK (horizon IN ('short_term','swing','momentum','long_term')),
  origin             TEXT NOT NULL CHECK (origin IN ('seed','ai','manual')),
  -- rejected: failed the promotion gate. retired: taken out of service by a person.
  status             TEXT NOT NULL
                     CHECK (status IN ('candidate','live','decaying','retired','rejected')),
  status_reason      TEXT,
  status_changed_at  TEXT NOT NULL,
  created_at         TEXT NOT NULL
);

CREATE TABLE strategy_versions (
  version_id    INTEGER PRIMARY KEY,
  strategy_id   INTEGER NOT NULL REFERENCES strategies(strategy_id),
  version       INTEGER NOT NULL,
  spec_json     TEXT NOT NULL,
  spec_sha256   TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  UNIQUE (strategy_id, version),
  UNIQUE (strategy_id, spec_sha256)
);

CREATE TABLE strategy_status_events (
  event_id         INTEGER PRIMARY KEY,
  strategy_id      INTEGER NOT NULL REFERENCES strategies(strategy_id),
  from_status      TEXT,
  to_status        TEXT NOT NULL,
  actor            TEXT NOT NULL CHECK (actor IN ('system','gate','user')),
  reason           TEXT,
  backtest_run_id  INTEGER,
  created_at       TEXT NOT NULL
);
CREATE INDEX ix_status_events_strategy ON strategy_status_events(strategy_id, created_at);

-- Gate outcome recorded on the run that produced it.
ALTER TABLE backtest_runs ADD COLUMN gate_verdict TEXT;
ALTER TABLE backtest_runs ADD COLUMN gate_report_json TEXT;
