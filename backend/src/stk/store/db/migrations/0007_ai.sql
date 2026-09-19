-- Phase 6/7: AI runs and their stored outputs.
--
-- Every model call is a row in ai_runs -- what was sent (by hash), what came back, tokens, an
-- estimated cost, and how it ended -- so spend is auditable and a failure is visible rather than
-- an absence. The AI never blocks the pipeline: a failed run is recorded, not raised.

CREATE TABLE ai_runs (
  run_id           INTEGER PRIMARY KEY,
  kind             TEXT NOT NULL CHECK (kind IN ('evening_review','strategy_lab')),
  business_date    TEXT,
  model            TEXT NOT NULL,
  status           TEXT NOT NULL CHECK (status IN ('success','invalid_output','failed','skipped')),
  attempts         INTEGER NOT NULL DEFAULT 0,
  input_tokens     INTEGER NOT NULL DEFAULT 0,
  output_tokens    INTEGER NOT NULL DEFAULT 0,
  cost_usd_est     REAL,                    -- NULL when the model has no configured price
  prompt_sha256    TEXT,
  response_text    TEXT,
  error            TEXT,
  started_at       TEXT NOT NULL,
  finished_at      TEXT,
  code_version     TEXT
);
CREATE INDEX ix_ai_runs_kind_date ON ai_runs(kind, business_date);

CREATE TABLE ai_outputs (
  output_id      INTEGER PRIMARY KEY,
  run_id         INTEGER NOT NULL REFERENCES ai_runs(run_id),
  kind           TEXT NOT NULL CHECK (kind IN ('brief','proposal')),
  business_date  TEXT NOT NULL,
  payload_json   TEXT NOT NULL,
  created_at     TEXT NOT NULL
);
CREATE INDEX ix_ai_outputs_lookup ON ai_outputs(kind, business_date, output_id);
