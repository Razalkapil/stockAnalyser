-- Phase 2: stored backtest runs.
--
-- strategy_version_id is a plain nullable INTEGER, deliberately WITHOUT a
-- foreign key: the strategies tables arrive in a later migration, and
-- SQLite cannot add a FK to an existing table. Runs are still keyed by
-- strategy_ref (a human-readable name/slug) so nothing here depends on it.

CREATE TABLE backtest_runs (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_ref        TEXT    NOT NULL,
    strategy_version_id INTEGER,
    kind                TEXT    NOT NULL CHECK (kind IN ('single', 'walk_forward')),
    status              TEXT    NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    exchange            TEXT    NOT NULL,
    data_start          TEXT    NOT NULL,
    data_end            TEXT    NOT NULL,
    benchmark_code      TEXT,
    benchmark_missing   INTEGER NOT NULL DEFAULT 0,
    params_json         TEXT    NOT NULL DEFAULT '{}',
    config_json         TEXT    NOT NULL DEFAULT '{}',
    code_version        TEXT,
    is_approximate      INTEGER NOT NULL DEFAULT 0,
    approx_reasons_json TEXT    NOT NULL DEFAULT '[]',
    stats_json          TEXT    NOT NULL DEFAULT '{}',
    error_message       TEXT,
    started_at          TEXT    NOT NULL,
    finished_at         TEXT
);
CREATE INDEX ix_backtest_runs_strategy ON backtest_runs (strategy_ref, started_at);

-- One row per walk-forward window (a 'single' run has none).
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
    -- pass: beat the benchmark after costs; fail: did not;
    -- no_benchmark: benchmark did not cover the window (not a fail, not a pass)
    result            TEXT    NOT NULL CHECK (result IN ('pass', 'fail', 'no_benchmark')),
    UNIQUE (run_id, label)
);

CREATE TABLE backtest_trades (
    trade_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES backtest_runs (run_id) ON DELETE CASCADE,
    window_label  TEXT,
    symbol        TEXT    NOT NULL,
    entry_date    TEXT    NOT NULL,
    entry_price   TEXT    NOT NULL,
    exit_date     TEXT    NOT NULL,
    exit_price    TEXT    NOT NULL,
    qty           INTEGER NOT NULL,
    entry_costs   TEXT    NOT NULL,
    exit_costs    TEXT    NOT NULL,
    gross_pnl     TEXT    NOT NULL,
    net_pnl       TEXT    NOT NULL,
    return_pct    REAL    NOT NULL,
    exit_reason   TEXT    NOT NULL,
    holding_days  INTEGER NOT NULL,
    reason        TEXT
);
CREATE INDEX ix_backtest_trades_run ON backtest_trades (run_id);

-- scope: 'overall', 'oos' (stitched out-of-sample), or 'window:<label>'.
CREATE TABLE backtest_metrics (
    run_id  INTEGER NOT NULL REFERENCES backtest_runs (run_id) ON DELETE CASCADE,
    scope   TEXT    NOT NULL,
    metric  TEXT    NOT NULL,
    value   REAL,
    PRIMARY KEY (run_id, scope, metric)
) WITHOUT ROWID;

CREATE TABLE backtest_equity (
    run_id     INTEGER NOT NULL REFERENCES backtest_runs (run_id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,
    equity     REAL    NOT NULL,
    benchmark  REAL,
    PRIMARY KEY (run_id, date)
) WITHOUT ROWID;
