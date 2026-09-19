-- Phase 7: proposals from the weekly AI strategy lab.
--
-- A proposal is either a NEW strategy (a DSL spec, validated and backtested before anyone sees
-- it) or a DEMOTION of an existing one. Nothing here takes effect on its own: approving or
-- dismissing is a person's decision, made through the UI.

CREATE TABLE strategy_proposals (
  proposal_id       INTEGER PRIMARY KEY,
  ai_run_id         INTEGER REFERENCES ai_runs(run_id),
  business_date     TEXT NOT NULL,
  type              TEXT NOT NULL CHECK (type IN ('new','demote')),
  title             TEXT NOT NULL,
  rationale         TEXT NOT NULL,
  target_slug       TEXT,                    -- demote: the strategy it would retire
  spec_json         TEXT,                    -- new: the DSL exactly as proposed
  strategy_id       INTEGER REFERENCES strategies(strategy_id),
  validation_errors_json TEXT,
  backtest_run_id   INTEGER REFERENCES backtest_runs(run_id),
  gate_verdict      TEXT,
  status            TEXT NOT NULL CHECK (status IN (
                      'invalid',              -- failed schema/semantic validation; never backtested
                      'backtest_error',       -- valid, but the backtest could not run
                      'rejected_by_gate',     -- backtested and failed the promotion gate
                      'insufficient_evidence',-- backtested; the gate could not decide
                      'awaiting_approval',    -- passed the gate; waiting on a person
                      'approved', 'dismissed')),
  status_note       TEXT,
  created_at        TEXT NOT NULL,
  decided_at        TEXT
);
CREATE INDEX ix_proposals_status ON strategy_proposals(status, created_at);
CREATE INDEX ix_proposals_date ON strategy_proposals(business_date);
