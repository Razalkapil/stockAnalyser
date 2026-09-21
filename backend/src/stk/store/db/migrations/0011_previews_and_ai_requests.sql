-- Preview picks, queued AI requests, and a fourth walk-forward window outcome.
--
-- Three changes that together make "nothing is here" legible:
--
--   1. backtest_windows.result gains 'no_trades'. A window in which the strategy made
--      no trades at all is not evidence that it loses -- it is evidence of nothing, and
--      the gate must not count it. SQLite cannot alter a CHECK, so the table is rebuilt.
--   2. strategy_previews: what a NOT-promoted strategy would have picked. Deliberately a
--      separate table from picks, not a flag on it, so tracking, out-of-sample stats and
--      the AI evening input cannot see a preview even by accident.
--   3. ai_requests: the dashboard may ASK for an AI run but can never make one -- the API
--      inserts a row here and a CLI worker executes it out of process.

-- 1 -------------------------------------------------------------------------------------
ALTER TABLE backtest_windows RENAME TO backtest_windows_old;

CREATE TABLE backtest_windows (
    window_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES backtest_runs (run_id) ON DELETE CASCADE,
    label             TEXT    NOT NULL,
    train_start       TEXT    NOT NULL,
    train_end         TEXT    NOT NULL,
    test_start        TEXT    NOT NULL,
    test_end          TEXT    NOT NULL,
    chosen_params_json TEXT   NOT NULL DEFAULT '{}',
    strat_return      REAL,
    bench_return      REAL,
    excess_return     REAL,
    max_drawdown      REAL,
    trade_count       INTEGER NOT NULL DEFAULT 0,
    -- pass: beat the benchmark after costs; fail: did not.
    -- The two unscored outcomes, neither a pass nor a fail, for different reasons:
    --   no_benchmark: the benchmark series did not cover the window -- nothing to beat.
    --   no_trades:    the strategy never traded in it -- nothing was tested.
    result            TEXT    NOT NULL
                      CHECK (result IN ('pass', 'fail', 'no_benchmark', 'no_trades')),
    UNIQUE (run_id, label)
);

INSERT INTO backtest_windows (
    window_id, run_id, label, train_start, train_end, test_start, test_end,
    chosen_params_json, strat_return, bench_return, excess_return, max_drawdown,
    trade_count, result
)
SELECT
    window_id, run_id, label, train_start, train_end, test_start, test_end,
    chosen_params_json, strat_return, bench_return, excess_return, max_drawdown,
    trade_count, result
FROM backtest_windows_old;

DROP TABLE backtest_windows_old;

-- 2 -------------------------------------------------------------------------------------
-- Mirrors picks, minus everything that only a real pick has: no status, no conflict/ai_reason
-- (the AI never sees a preview), no outcome or marks. status_at_preview records WHY this is a
-- preview -- the strategy's status at the moment it was computed -- so a row can never be
-- mistaken for something that earned its place.
CREATE TABLE strategy_previews (
  preview_id           INTEGER PRIMARY KEY,
  strategy_id          INTEGER NOT NULL REFERENCES strategies(strategy_id),
  strategy_version_id  INTEGER NOT NULL REFERENCES strategy_versions(version_id),
  status_at_preview    TEXT NOT NULL,
  exchange             TEXT NOT NULL,
  symbol               TEXT NOT NULL,
  horizon              TEXT NOT NULL
                       CHECK (horizon IN ('short_term','swing','momentum','long_term')),
  signal_date          TEXT NOT NULL,
  ref_price            REAL NOT NULL,      -- unadjusted close on the signal date
  stop_price           REAL,
  target_price         REAL,
  stop_pct             REAL,
  target_pct           REAL,
  hold_days            INTEGER NOT NULL,
  window_end           TEXT NOT NULL,
  score                REAL NOT NULL,
  rank_in_strategy     INTEGER NOT NULL,
  reason               TEXT NOT NULL,
  created_at           TEXT NOT NULL,
  UNIQUE (strategy_version_id, exchange, symbol, signal_date)
);
CREATE INDEX ix_strategy_previews_signal ON strategy_previews(signal_date, horizon);
CREATE INDEX ix_strategy_previews_strategy ON strategy_previews(strategy_id, signal_date);

-- 3 -------------------------------------------------------------------------------------
CREATE TABLE ai_requests (
  request_id     INTEGER PRIMARY KEY,
  kind           TEXT NOT NULL CHECK (kind IN ('evening_review','strategy_lab')),
  business_date  TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('queued','running','done','error')),
  force          INTEGER NOT NULL DEFAULT 0,
  requested_by   TEXT NOT NULL,             -- 'dashboard' | 'cli'
  requested_at   TEXT NOT NULL,
  started_at     TEXT,
  finished_at    TEXT,
  run_id         INTEGER REFERENCES ai_runs(run_id),
  error          TEXT
);

-- The cost guard: at most ONE open request per kind and day, so a double-clicked button
-- cannot become a second model call.
CREATE UNIQUE INDEX ux_ai_requests_open
  ON ai_requests(kind, business_date)
  WHERE status IN ('queued','running');

CREATE INDEX ix_ai_requests_queue ON ai_requests(status, requested_at);
