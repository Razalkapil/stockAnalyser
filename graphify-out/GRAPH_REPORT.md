# Graph Report - stockAnalyser  (2026-09-19)

## Corpus Check
- 307 files · ~182,826 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 37 file(s) not represented in the graph (top: (none) 12, .csv 7, .service 6)

## Summary
- 4304 nodes · 11766 edges · 246 communities (137 shown, 109 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 759 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `275d8062`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- get_strategy
- assert_bars_sane
- ingest/backfill.py
- package.json
- validate_json_response
- test_deploy.py
- track_pick
- Indian stock suggester + virtual playground — build plan
- backup
- migrate
- build_factor_rows
- connect
- domain/orders.py
- rebuild_adjusted_bars
- derive_metric_rows
- lab.py
- health.py
- base.py
- job_run
- compute_metrics
- config/costs.py
- compute_liquidity_for_date
- run_evening_review
- Stocks.tsx
- time.py
- RateSchedule
- _write
- test_costs.py
- get_intraday_provider
- commands/playground.py
- 0001_init.sql
- ingest/corpactions.py
- Side
- Position
- ProviderCapabilities
- StrategyLab.tsx
- commands/backup.py
- compute_indicators
- place
- Any
- playground_routes.py
- playground.test.tsx
- store/backup.py
- IngestAssertionError
- doctor
- IntradayCandle
- datetime
- ingest_security_master
- parse_sec_bhavdata_full
- parse_xbrl
- stk_backtest_data
- flag_decay
- TestPicks
- _mock
- CLAUDE.md
- PointInTimeView
- parse_candles_json
- test_dsl_backtest.py
- RawArtifact
- test_xbrl_ingest.py
- apply_corporate_actions
- backtest/runs.py
- list_backups
- hooks.ts
- ContentValidationError
- passes.py
- yfinance/__init__.py
- queries/__init__.py
- stk
- test_nightly.py
- errors_of
- slippage.py
- runner.py
- evaluate_gate
- check_ai_runs
- spec_problems
- ingest.py
- cap_quantity
- auth.py
- ingest_fundamentals_for_security
- YFinanceIntradayProvider
- backtest/engine.py
- NotSupportedError
- repo.py
- TestIsolatedDeliveryInconsistency
- test_yfinance_provider.py
- spec_dict
- test_health.py
- App.tsx
- strategies/promotion.py
- model.py
- upsert_partition
- Brief.tsx
- test_backtest_engine.py
- ADR 0003: Historical price source
- days_from
- services.py
- compilerOptions
- NSE
- check_job_runs
- connect
- check_poller
- evaluate.py
- devDependencies
- settings.py
- AppSettings
- entry_mask
- app.py
- is_liquid
- assert_bars_match_requested_date
- verify_backup
- OrderDrawer.tsx
- _make_bars
- Project brief for Claude Code — Indian stock suggester + virtual playground
- catalogue.py
- backtest/__init__.py
- Data sources — verified endpoints
- TestParseHolidays
- TestCli
- main.tsx
- backtest/walkforward.py
- test_schema_drift.py
- TestNestedTransactions
- manifest_path
- PathsConfig
- ai/__init__.py
- playground/fills.py
- latest_backup_age_days
- TestAuth
- ingest_corporate_actions
- Runbook
- TestExchangeTxnBoundary
- TestUrlAndCapabilities
- test_yfinance_intraday.py
- TestAdjustedFreshness
- dsl/__init__.py
- strategies/__init__.py
- _DatedSeries
- Phase 1 — data pipeline + store
- TestIpftBoundary
- backup.sh
- install.sh
- restore.sh
- backfill_nse_prices
- stk_ai_inputs
- stk_ai_schemas
- stk_api
- stk_api_deps
- stk_backtest_engine
- stk_backtest_runs
- stk_ingest_adjustments
- stk_ingest_corpactions
- stk_backtest_setup
- stk_backtest_view
- stk_backtest_walkforward
- read_manifest
- last_trading_day_on_or_before
- operand
- schema.d.ts
- stk_cli_commands
- stk_config_ai
- stk_config_backtest
- stk_config_horizons
- ref_testing_library_jest_dom_vitest
- stk_config_loader
- stk_config_promotion
- stk_config_settings
- stk_config_universe
- stk_core_errors
- stk_core_logging
- stk_core_money
- stk_core_time
- stk_core_version
- get_settings
- make_portfolio
- 0006_playground.sql
- stk_domain_costs
- TestParse
- TestStatusAndBriefs
- TestFetchHistory
- stk_domain_dsl_catalogue
- logging.py
- TestStocks
- stk_domain_dsl_evaluate
- TestLiquidityFloor
- stk_domain_dsl_model
- stk_domain_dsl_validate
- get_rate_schedule
- stk_domain_fills
- stockAnalyser
- stk_domain_indicators
- stk_domain_metrics
- MarketData
- stk_domain_slippage
- stk_domain_walkforward
- stk_ingest_calendar
- NseCorporateActionsProvider
- Oracle Cloud Always Free VM — setup notes
- stk_ingest_daily
- stk_ingest_fundamentals
- stk_ingest_fundamentals_metrics
- stk_ingest_fundamentals_sweep
- stk_ingest_fundamentals_xbrl
- stk_ingest_indices
- stk_ingest_jobs
- stk_ingest_liquidity
- stk_ingest_master
- TestAuxiliarySeriesOhlc
- stk_ingest_normalise
- stk_ingest_raw_store
- stk_playground_context
- stk_playground_performance
- stk_strategies_promotion
- stk_providers_base
- stk_providers_nse_indices
- stk_providers_registry
- stk_providers_yfinance_prices
- stk_store
- stk_store_db_engine
- stk_store_parquet_layout
- stk_store_parquet_schema
- stk_store_parquet_writer
- stk_strategies_dsl_strategy
- stk_strategies_repo
- stk_strategies_runner
- stk_strategies_stats
- stk_strategies_tracking

## God Nodes (most connected - your core abstractions)
1. `connect()` - 146 edges
2. `_mock()` - 90 edges
3. `get_settings()` - 68 edges
4. `RawArtifact` - 64 edges
5. `migrate()` - 63 edges
6. `place()` - 50 edges
7. `StrategySpec` - 45 edges
8. `DataNotPublished` - 42 edges
9. `NotSupportedError` - 42 edges
10. `Side` - 42 edges

## Surprising Connections (you probably didn't know these)
- `Ground rules (from the brief, do not relitigate without asking)` --references--> `corpactions()`  [INFERRED]
  CLAUDE.md → backend/src/stk/cli/commands/ingest.py
- `Things never verified live` --references--> `xbrl()`  [INFERRED]
  docs/runbook.md → backend/src/stk/cli/commands/ingest.py
- `Ingest pipeline` --references--> `ContentValidationError`  [INFERRED]
  docs/BUILD_PLAN.md → backend/src/stk/core/errors.py
- `Verification` --references--> `ContentValidationError`  [INFERRED]
  docs/BUILD_PLAN.md → backend/src/stk/core/errors.py
- `Failure playbook` --references--> `ContentValidationError`  [INFERRED]
  docs/runbook.md → backend/src/stk/core/errors.py

## Import Cycles
- None detected.

## Communities (246 total, 109 thin omitted)

### Community 0 - "get_strategy"
Cohesion: 0.17
Nodes (11): list_proposals(), get_strategy(), idea(), Model, The weekly strategy lab against a fake model: validation, backtest, gate, and…, reply(), run(), TestApi (+3 more)

### Community 1 - "assert_bars_sane"
Cohesion: 0.24
Nodes (6): assert_bars_sane(), Cheap, fast invariant checks over a batch of parsed bars. Returns a list of…, _bar(), Regression test: a real live-ingest failure. Thin government securities…, The floor must not swallow real bugs once absolute values are large enough to…, TestAssertBarsSane

### Community 2 - "ingest/backfill.py"
Cohesion: 0.07
Nodes (29): prices(), command, `stk backfill` -- historical price backfill., Backfill daily prices over a date range for one exchange. NSE source (legacy vs…, backfill_bse_prices(), _backfill_prices(), BackfillSummary, date (+21 more)

### Community 3 - "package.json"
Cohesion: 0.06
Nodes (30): @fontsource/ibm-plex-mono, @fontsource/ibm-plex-sans, jsdom, lightweight-charts, openapi-typescript, react-dom, @testing-library/jest-dom, @types/react (+22 more)

### Community 4 - "validate_json_response"
Cohesion: 0.12
Nodes (13): Validate a response that is expected to be JSON., validate_json_response(), Response, Tests for the content-type/magic-byte guard against the BSE 'silent 200'…, The exact BSE failure: 200 OK, HTML body -- must raise, not parse., The trap must not be swallowed anywhere -- calling code should never see a…, Exchanges do serve real CSVs with inconsistent content-type headers (e.g.…, A misleading content-type header must not override the actual body check. (+5 more)

### Community 5 - "test_deploy.py"
Cohesion: 0.08
Nodes (21): ConfigParser, re, shlex, shutil, skipif, parse(), parametrize, Path (+13 more)

### Community 6 - "track_pick"
Cohesion: 0.06
Nodes (33): Bar, _exit_on(), Live pick tracking -- pure. Given the bars that followed a pick's signal date,…, ``bars`` must be strictly AFTER the signal date, in date order., track_pick(), TrackedPick, _bars_by_symbol(), Connection (+25 more)

### Community 7 - "Indian stock suggester + virtual playground — build plan"
Cohesion: 0.14
Nodes (14): Amendments, Context, Decisions locked this session, Design system (extracted from the handoff), Guiding principles for phases 0–1, Indian stock suggester + virtual playground — build plan, Open items for later phases, Phase 0 — repo, config, VM notes, history spike (+6 more)

### Community 8 - "backup"
Cohesion: 0.14
Nodes (13): BackupError, RuntimeError, Restore ``backup`` into ``data_root`` (app.db and parquet/). Returns what was…, restore_backup(), tarfile, at(), backup(), date (+5 more)

### Community 9 - "migrate"
Cohesion: 0.05
Nodes (38): migrate_cmd(), command, Apply all pending SQLite migrations., _discover_migrations(), migrate(), Path, Return (sequence_number, name, path) for every migrations/*.sql file, sorted., Apply all pending migrations in order. Returns the names applied. (+30 more)

### Community 10 - "build_factor_rows"
Cohesion: 0.08
Nodes (35): ActionFactor, _adjust_bar(), build_factor_rows(), _factor_table(), FactorRow, factors_for_bar(), load_actions(), _LoadedActions (+27 more)

### Community 11 - "connect"
Cohesion: 0.09
Nodes (31): adv_turnover(), bars_on_day(), _d(), last_closes(), date, Decimal, Path, Playground reads from the price lake (all via store.duck; all UNADJUSTED). (+23 more)

### Community 12 - "domain/orders.py"
Cohesion: 0.07
Nodes (44): can_buy(), can_sell(), Lock, StrEnum, Fill-price rules -- pure. Two rules matter and both are easy to get subtly…, _blocked(), Candle, Fill (+36 more)

### Community 13 - "rebuild_adjusted_bars"
Cohesion: 0.11
Nodes (25): AdjustmentResult, Path, Rebuild adjustment_factors and bars_daily_adjusted for one exchange. Network-…, rebuild_adjusted_bars wrapped in a job_run scope. Kept separate so the rebuild…, rebuild_adjusted_bars(), rebuild_adjusted_bars_job(), adjustment_factors_path(), _adjusted() (+17 more)

### Community 14 - "derive_metric_rows"
Cohesion: 0.09
Nodes (27): attach_fundamentals(), available_on(), _borrowings(), _cagr(), derive_metric_rows(), FilingFacts, DataFrame, date (+19 more)

### Community 15 - "lab.py"
Cohesion: 0.07
Nodes (47): AnthropicClient, call_structured(), _errors(), LlmClient, Protocol, ValueError, The LLM boundary: a tiny protocol, the real Anthropic client, and structured-…, The real client. Credentials come from the environment (ANTHROPIC_API_KEY, or… (+39 more)

### Community 16 - "health.py"
Cohesion: 0.20
Nodes (17): check_adjusted_freshness(), check_calendar_coverage(), check_stale_symbols(), check_unparsed_corporate_actions(), Problem, Connection, date, Path (+9 more)

### Community 17 - "base.py"
Cohesion: 0.05
Nodes (54): ABC, ConfigError, Configuration failed to load or validate., _fetch_all_records(), Fetch every exchange's master snapshot, tolerating one exchange's fetch failing…, CalendarProvider, CorporateActionsProvider, FundamentalsProvider (+46 more)

### Community 18 - "job_run"
Cohesion: 0.07
Nodes (32): The nightly and weekly runs: an ordered list of `stk` commands, each isolated.…, ingest_xbrl_documents(), _pending(), _process(), Connection, Path, Fetch, persist, parse and store the XBRL behind each filing-metadata snapshot.…, Write a parsed filing's line items (replacing any earlier parse of the same… (+24 more)

### Community 19 - "compute_metrics"
Cohesion: 0.10
Nodes (18): cagr(), compute_metrics(), max_drawdown(), date, Backtest performance metrics -- pure. Statistics, not money: inputs are…, One closed round trip, net of all costs., Worst peak-to-trough decline as a NEGATIVE fraction (0.0 if never below a peak)., Annualised Sharpe from daily equity. 0.0 when there is no variance to divide by. (+10 more)

### Community 20 - "config/costs.py"
Cohesion: 0.16
Nodes (15): _dec(), Decimal, product(), Dated cost-rate schedule loader. Loads config/costs.yaml -- a history of…, Decimal from a YAML number without inheriting float noise (0.1 ->…, BrokerageRule, CostRates, ProductRates (+7 more)

### Community 21 - "compute_liquidity_for_date"
Cohesion: 0.15
Nodes (20): compute_liquidity_for_date(), compute_liquidity_metrics(), LiquidityResult, Connection, date, Path, Table, Truncate-and-replace universe_current for symbols resolvable to a security_id… (+12 more)

### Community 22 - "run_evening_review"
Cohesion: 0.06
Nodes (39): LlmError, LlmReply, RuntimeError, The call failed (network, auth, rate limit, refusal). Carries a message safe to…, Connection, date, ReviewResult, run_evening_review() (+31 more)

### Community 23 - "Stocks.tsx"
Cohesion: 0.13
Nodes (23): react, EmptyState(), EquityChart(), points(), Num(), PickMarker, PriceChart(), Segmented() (+15 more)

### Community 24 - "time.py"
Cohesion: 0.03
Nodes (76): `stk db` -- database management commands., _check_endpoints(), _previous_weekday(), date, `stk doctor` -- ingest health check. Thin by design: every actual check lives…, Probe each documented endpoint for reachability. Reports a transport or…, Step back to the nearest weekday. Holidays are not filtered -- a holiday simply…, `stk nightly` / `stk weekly` -- the scheduled runs (systemd timers call these). (+68 more)

### Community 25 - "RateSchedule"
Cohesion: 0.27
Nodes (8): _DatedRate, BaseModel, date, RateSchedule, Every rate in force for ``exchange`` on ``as_of_date``, as pure domain data., A rate that takes effect from a given date, until superseded., Return the rate in effect on ``as_of_date``. If ``as_of_date`` predates the…, Typed, date-resolvable view over config/costs.yaml.

### Community 26 - "_write"
Cohesion: 0.09
Nodes (12): _bars(), date, fixture, Path, Table, The load-bearing case for query-time identity resolution: a bar written under a…, exchange/year come from the directory names, not the file -- the liquidity and…, A fresh checkout has no bars_daily_adjusted. Querying it must return zero rows… (+4 more)

### Community 27 - "test_costs.py"
Cohesion: 0.11
Nodes (9): Tests for the dated cost-rate schedule (config/costs.yaml + RateSchedule).…, DP charge: flat, per-scrip, per-day, sell leg only -- dominates cost on small…, Stamp duty became uniform nationwide on 2020-07-01., STT: delivery both legs; intraday sell-leg only., GST must apply to brokerage/exchange_txn/sebi fee/IPFT and NOT to STT or stamp…, TestDpCharge, TestGstScope, TestStampDutyBoundary (+1 more)

### Community 28 - "get_intraday_provider"
Cohesion: 0.26
Nodes (8): get_intraday_provider(), The DELAYED intraday candle source for the paper-trading poller. Gated by its…, fixture, Set the two yfinance switches and force settings to re-read them; restore…, The whole point of a separate switch., switches(), set_(), TestSeparateSwitch

### Community 29 - "commands/playground.py"
Cohesion: 0.08
Nodes (32): _ctx(), eod(), poll(), portfolio_create(), portfolio_list(), command, help, Option (+24 more)

### Community 30 - "0001_init.sql"
Cohesion: 0.14
Nodes (23): corporate_actions, fundamentals_snapshots, ix_ca_exdate, ix_ca_parse_status, ix_ca_security_ex, ix_fund_provider, ix_fund_sec_period, ix_job_lookup (+15 more)

### Community 31 - "ingest/corpactions.py"
Cohesion: 0.07
Nodes (64): ActionType, _bond_interest(), _bonus(), _cash_distribution(), _cash_dividend(), _ClauseResult, _face_value_change(), build() (+56 more)

### Community 32 - "Side"
Cohesion: 0.08
Nodes (32): command, quote(), `stk costs` -- inspect the transaction-cost model., Itemise the charges on one order leg, using the rates in force on a date. Rates…, bps(), Decimal, Decimal-safe money arithmetic and Indian-style (lakh/crore) formatting. Every…, Express ``value`` as basis points of ``basis``. Returns 0 if basis is 0. (+24 more)

### Community 33 - "Position"
Cohesion: 0.08
Nodes (28): apply_buy(), apply_sell(), apply_split_or_bonus(), dividend_cash(), Position, PositionError, Decimal, ValueError (+20 more)

### Community 34 - "ProviderCapabilities"
Cohesion: 0.07
Nodes (19): ProviderCapabilities, Declares what a provider can actually do, so callers can degrade gracefully…, NseLegacyBhavcopyProvider, PriceProvider backed by NSE's legacy per-date cm*bhav.csv.zip archive., NseSecBhavdataProvider, PriceProvider backed by NSE's sec_bhavdata_full daily file., TestCapabilities, TestFetchEod (+11 more)

### Community 35 - "StrategyLab.tsx"
Cohesion: 0.17
Nodes (26): label, PickCard(), useProposalAction(), useProposals(), useStrategyAction(), DASH, fmtClock(), fmtDate() (+18 more)

### Community 36 - "commands/backup.py"
Cohesion: 0.19
Nodes (16): list_cmd(), Argument, command, exists, help, Option, Path, `stk backup` -- back up, verify and restore the application state. (+8 more)

### Community 37 - "compute_indicators"
Cohesion: 0.08
Nodes (32): all_columns(), Every concrete column name the catalogue can produce., _breakout_levels(), compute_indicators(), _grouped(), _momentum(), _oscillators(), DataFrame (+24 more)

### Community 38 - "place"
Cohesion: 0.08
Nodes (29): at(), candle(), ledger_reconciles(), order(), place(), date, datetime, parametrize (+21 more)

### Community 39 - "Any"
Cohesion: 0.11
Nodes (27): build_lab_input(), catalogue_doc(), dsl_schema(), Connection, Path, _r(), Assemble the strategy lab's input: what exists, how it is doing, and what the…, load_horizons() (+19 more)

### Community 40 - "playground_routes.py"
Cohesion: 0.05
Nodes (68): _err(), _f(), new_order(), new_portfolio(), play_ctx(), portfolio(), portfolios(), preview() (+60 more)

### Community 41 - "playground.test.tsx"
Cohesion: 0.14
Nodes (26): react-router-dom, @tanstack/react-query, @testing-library/react, @testing-library/user-event, vitest, TicketProbe(), Ctx, TicketCtx (+18 more)

### Community 42 - "store/backup.py"
Cohesion: 0.22
Nodes (14): BackupResult, _check_archive(), _check_database(), _check_files(), _is_within(), datetime, Path, Backups: a consistent SQLite snapshot, the parquet lake, and a checksummed… (+6 more)

### Community 43 - "IngestAssertionError"
Cohesion: 0.17
Nodes (14): IngestAssertionError, Exception, Base class for all application-raised errors., A post-ingest sanity check failed (row counts, OHLC invariants, ...)., StkError, assert_index_bars_sane(), _assert_turnover_plausible(), _judge_delivery_violations() (+6 more)

### Community 44 - "doctor"
Cohesion: 0.19
Nodes (9): doctor(), command, help, Option, Path, Report on ingest health. Exits non-zero if anything looks wrong., check_backup_age(), envvar (+1 more)

### Community 45 - "IntradayCandle"
Cohesion: 0.17
Nodes (6): IntradayCandle, datetime, One intraday OHLCV candle. ``start`` is timezone-AWARE (IST) -- naive datetimes…, Parse a previously fetched artifact (offline; no network)., field_validator, Exception

### Community 46 - "datetime"
Cohesion: 0.05
Nodes (61): `stk api` -- serve the dashboard's API and manage its tokens., Exception hierarchy for the ingest/provider stack. The rule this hierarchy…, Corporate-action back-adjustment: factor timelines and the derived…, Nightly ingest orchestration. NSE and BSE prices both go through…, Index (benchmark) ingest. Same shape as ingest.daily's price path -- fetch,…, Liquidity feature computation and the tradeable-universe snapshot. Reads…, Security-master ingest: ISIN-keyed merge of NSE + BSE listings into…, SQLite connection factory, pragmas, and the forward-only migration runner. No… (+53 more)

### Community 47 - "ingest_security_master"
Cohesion: 0.19
Nodes (14): ingest_security_master(), MasterIngestResult, Connection, Path, Returns True if this upsert closed out a rename (a different symbol was…, Fetch and merge the NSE + BSE security masters into securities/…, _upsert_listing_and_detect_rename(), _upsert_security() (+6 more)

### Community 48 - "parse_sec_bhavdata_full"
Cohesion: 0.24
Nodes (5): parse_sec_bhavdata_full(), Parse NSE's sec_bhavdata_full_{DDMMYYYY}.csv into canonical bars. This file…, The real NSE file has a leading space on every header/value after the first…, This is the critical rule: '-' means unreported, not zero., TestParseSecBhavdataFull

### Community 49 - "parse_xbrl"
Cohesion: 0.07
Nodes (28): _index_facts(), _local(), _parse_date(), parse_xbrl(), take(), _plain_contexts(), date, ValueError (+20 more)

### Community 51 - "flag_decay"
Cohesion: 0.47
Nodes (3): flag_decay(), Move live strategies whose live hit rate has slumped to ``decaying``. Returns…, TestStatsAndDecay

### Community 53 - "_mock"
Cohesion: 0.13
Nodes (15): IndicesIngestResult, ingest_indices_for_date(), date, Path, Table, Ingest one day of NSE index closes end-to-end. Idempotent., _to_table(), indices_daily_partition() (+7 more)

### Community 54 - "CLAUDE.md"
Cohesion: 0.29
Nodes (5): graphify, Ground rules (from the brief, do not relitigate without asking), Repo layout, What this is, Working here

### Community 55 - "PointInTimeView"
Cohesion: 0.12
Nodes (19): An intent to buy at the next open., Signal, PointInTimeView, DataFrame, Every bar dated <= ``decision_date`` (all symbols)., Fundamentals rows whose ``available_at`` <= ``decision_date`` (else None if no…, Read-only view of ``MarketData`` as it stood at the close of ``decision_date``., All symbols' bars dated exactly ``decision_date``. (+11 more)

### Community 56 - "parse_candles_json"
Cohesion: 0.36
Nodes (6): parse_candles_json(), Pure: bytes -> candles, sorted by start, in IST. Rejects a malformed record…, payload(), parametrize, rec(), TestParse

### Community 57 - "test_dsl_backtest.py"
Cohesion: 0.17
Nodes (14): prepare_frame(), DataFrame, Series, Raw adjusted bars -> the frame a ``DslStrategy`` and the engine both read., engine_config(), make_bars(), oversold_spec(), DataFrame (+6 more)

### Community 58 - "RawArtifact"
Cohesion: 0.04
Nodes (82): DataNotPublished, ProviderUnavailable, Transport-level failure: timeout, connection refused, DNS, 5xx., The source has not yet published data for the requested date. Distinct from…, build_client(), Response, Shared HTTP client factory and response validation. This module is the single…, Validate a response that is expected to be an XBRL/XML document. Guards the… (+74 more)

### Community 59 - "test_xbrl_ingest.py"
Cohesion: 0.26
Nodes (11): add_snapshot(), db(), meta_row(), fixture, Path, XBRL ingest end to end: real filings served through a mocked network., rows(), run() (+3 more)

### Community 60 - "apply_corporate_actions"
Cohesion: 0.34
Nodes (5): apply_corporate_actions(), date, add_action(), NSE republishing a corrected subject creates a second row by design., TestCorporateActions

### Community 61 - "backtest/runs.py"
Cohesion: 0.16
Nodes (22): BacktestResult, _begin(), _finish(), _insert_trades(), load_run_summary(), _metric_rows(), Connection, date (+14 more)

### Community 62 - "list_backups"
Cohesion: 0.27
Nodes (6): _backup_dirs(), list_backups(), Directories this module created: date-named AND holding a manifest. Nothing…, Keep the newest ``keep_daily`` backups, plus the newest ``keep_weekly`` SUNDAY…, rotate(), TestRotation

### Community 63 - "hooks.ts"
Cohesion: 0.10
Nodes (32): ref_schema, useCancelOrder(), useCreatePortfolio(), useJournal(), usePlaceOrder(), usePortfolio(), usePortfolioInvalidation(), usePortfolios() (+24 more)

### Community 64 - "ContentValidationError"
Cohesion: 0.04
Nodes (51): ContentValidationError, ParseError, A response passed HTTP status but failed content-type/magic-byte checks. This…, A response was structurally valid but semantically un-parseable. Used by the…, format_yyyymmdd(), Format a date as 'YYYYMMDD' for UDiFF filename construction., canonical_index_code(), _decimal_or_none() (+43 more)

### Community 65 - "passes.py"
Cohesion: 0.12
Nodes (35): PlayCtx, CorpActionResult, FillContext, Where a fill's price came from -- recorded on every trade and shown in the UI., EodResult, Connection, date, The end-of-day playground step: corporate actions, then EOD fills, then… (+27 more)

### Community 69 - "test_nightly.py"
Cohesion: 0.07
Nodes (39): _job_alerts(), Scheduled steps (nightly.*, weekly.*) whose NEWEST attempt for a date did not…, _finish(), nightly(), command, help, Option, Corporate actions, prices, indices, liquidity, scan, track, paper EOD, AI… (+31 more)

### Community 84 - "errors_of"
Cohesion: 0.20
Nodes (3): errors_of(), close > 500 would mean different things depending on when corporate actions…, TestSemanticValidation

### Community 85 - "slippage.py"
Cohesion: 0.13
Nodes (15): BarPrices, circuit_lock(), Decimal, Classify a bar as upper-locked, lower-locked or neither. See module docstring., apply_slippage(), Decimal, Tiered slippage and the participation cap -- pure. Slippage is a function of…, Basis points of slippage for a name with the given trailing ADV turnover.… (+7 more)

### Community 86 - "runner.py"
Cohesion: 0.04
Nodes (80): _index_moves(), Path, create_app(), Path, ApiContext, get_conn(), get_ctx(), Connection (+72 more)

### Community 87 - "evaluate_gate"
Cohesion: 0.12
Nodes (14): evaluate_gate(), GateCheck, GateReport, GateThresholds, The promotion gate -- pure. A strategy goes live only if, over its walk-forward…, WindowSummary, (new status, reason) for a gate verdict., status_for() (+6 more)

### Community 88 - "check_ai_runs"
Cohesion: 0.38
Nodes (4): check_ai_runs(), The AI never blocks the pipeline, which means its failures are silent unless…, _ai_run(), TestAiRuns

### Community 89 - "spec_problems"
Cohesion: 0.13
Nodes (15): lab_problems(), Everything that can be wrong with a proposed spec, checked without running…, Semantic problems in a reply. Drives the retry; per-idea failures are handled…, Demotion, LabReply, NewStrategyIdea, BaseModel, What the weekly lab is asked to emit. The strategy itself travels as a JSON… (+7 more)

### Community 90 - "ingest.py"
Cohesion: 0.05
Nodes (65): adjustments(), calendar(), corpactions(), daily(), fundamentals(), fundamentals_sweep(), indices(), liquidity() (+57 more)

### Community 91 - "cap_quantity"
Cohesion: 0.36
Nodes (4): cap_quantity(), Largest fillable quantity given a bar's volume and a participation cap (0..1]., parametrize, TestParticipationCap

### Community 92 - "auth.py"
Cohesion: 0.12
Nodes (22): create_token(), hash_token(), list_tokens(), Connection, Row, Single-user bearer-token auth. Only a SHA-256 of each token is stored, so a…, Create a named token and return it. This is the ONLY time it is available in…, revoke_token() (+14 more)

### Community 93 - "ingest_fundamentals_for_security"
Cohesion: 0.27
Nodes (6): FundamentalsIngestResult, ingest_fundamentals_for_security(), Path, Fetch one security's recent filings and upsert into fundamentals_snapshots. One…, _insert_security(), TestIngestFundamentalsForSecurity

### Community 94 - "YFinanceIntradayProvider"
Cohesion: 0.33
Nodes (3): YFinanceIntradayProvider, TestFetch, history()

### Community 95 - "backtest/engine.py"
Cohesion: 0.16
Nodes (20): _align_benchmark(), _d(), EngineConfig, _Position, DataFrame, date, Decimal, Protocol (+12 more)

### Community 96 - "NotSupportedError"
Cohesion: 0.05
Nodes (40): NotSupportedError, A provider does not implement an optional capability., The verbatim filing document (e.g. XBRL) behind a ``FilingRef.source_url``.…, KitePriceProvider, Zerodha Kite Connect adapter -- a deliberate, documented STUB. Why it exists:…, Placeholder. Constructing it raises, so selecting ``kite`` in config fails at…, BseLegacyBhavcopyProvider, PriceProvider backed by BSE's legacy per-date EQ*.CSV.ZIP archive. (+32 more)

### Community 97 - "repo.py"
Cohesion: 0.08
Nodes (25): canonical_json(), list_strategies(), _now(), Connection, Row, Strategy registry: strategies, immutable versions, and status history. A spec…, Change a strategy's status and record the event. Returns False if the status is…, Stable serialisation so equal rules always hash equal. (+17 more)

### Community 98 - "TestIsolatedDeliveryInconsistency"
Cohesion: 0.33
Nodes (3): Regression from a real backfill: NSE's 2024-02-19 file has WTICAB with…, e.g. a units/column-shift bug: 5% of rows violate it., TestIsolatedDeliveryInconsistency

### Community 99 - "test_yfinance_provider.py"
Cohesion: 0.15
Nodes (9): enabled(), provider(), fixture, Unit tests for the yfinance fallback provider. Almost every test here is about…, Turn the feature flag on for tests that need the provider built. get_settings()…, The flag the UI's `approx` badge and every backtest honesty check ultimately…, TestCapabilities, TestUnsupportedOperations (+1 more)

### Community 101 - "test_health.py"
Cohesion: 0.17
Nodes (14): check_partition_manifests(), Every partition file against its recorded row count and sha256. A mismatch…, _add_calendar(), date, Path, Unit tests for the individual `stk doctor` checks. Each check is exercised…, Trading days before the first ingested bar are history we have not backfilled…, A fresh install must not report every symbol as stale. (+6 more)

### Community 102 - "App.tsx"
Cohesion: 0.13
Nodes (23): queryClient, Shell(), chip, NAV, SearchBox(), TopBar(), apiDelete(), ApiError (+15 more)

### Community 103 - "strategies/promotion.py"
Cohesion: 0.16
Nodes (19): DecayConfig, PromotionConfig, BaseModel, Typed loader for config/promotion.yaml., _Thresholds, promote(), Connection, date (+11 more)

### Community 104 - "model.py"
Cohesion: 0.14
Nodes (32): Add, Cond, Div, ExitRules, Horizon, Ind, Mul, Not (+24 more)

### Community 105 - "upsert_partition"
Cohesion: 0.12
Nodes (23): load_market_data(), date, Path, Adjusted bars for [start - warmup, end], prepared for the engine., bars_daily_adjusted_partition(), Overwrite-by-partition write. Returns the row count of the resulting file.…, upsert_partition(), adjusted_table() (+15 more)

### Community 106 - "Brief.tsx"
Cohesion: 0.24
Nodes (8): bar, StaleBanner(), useBrief(), useBriefs(), tint, Brief(), card, cardTitle

### Community 107 - "test_backtest_engine.py"
Cohesion: 0.11
Nodes (24): buy(), config(), days_of(), flat(), make_data(), poison_after(), Bar, date (+16 more)

### Community 108 - "ADR 0003: Historical price source"
Cohesion: 0.22
Nodes (6): RunReport, A more important finding: NSE's own archive occasionally serves mislabeled content, ADR 0003: Historical price source, Consequences, Context, Daily EOD prices (deep history, 2010-2019): legacy `cm*bhav.csv.zip`

### Community 109 - "days_from"
Cohesion: 0.44
Nodes (4): days_from(), parametrize, Regression for a bug found by a real backfill: NSE publishes several series for…, TestOneBarPerSymbolPerDay

### Community 110 - "services.py"
Cohesion: 0.09
Nodes (45): _brief_dates(), build_status(), _company_names(), expected_data_date(), _fundamentals_for(), get_brief(), latest_bar_date(), latest_pick_date() (+37 more)

### Community 111 - "compilerOptions"
Cohesion: 0.11
Nodes (17): compilerOptions, isolatedModules, jsx, lib, module, moduleResolution, noEmit, noFallthroughCasesInSwitch (+9 more)

### Community 112 - "NSE"
Cohesion: 0.22
Nodes (9): assert_index_bars_match_requested_date(), date, Same guard as assert_bars_match_requested_date, for index bars. ADR 0003…, Corporate actions, Daily EOD prices (primary source): `sec_bhavdata_full`, Index closes (benchmark) — `ind_close_all`, NSE, Price bands (for circuit-lock detection) (+1 more)

### Community 116 - "check_job_runs"
Cohesion: 0.33
Nodes (4): check_job_runs(), Degraded or failed job runs in the lookback window. Only the LATEST attempt per…, job_runs is observability, not a lock -- repeated attempts are expected, and…, TestJobRuns

### Community 117 - "connect"
Cohesion: 0.13
Nodes (14): ingest_nse_prices_for_date(), Ingest one day of NSE prices end-to-end: fetch, validate, persist raw, parse,…, connect(), Connection, Open a connection with the app's standard pragmas applied., bars_daily_partition(), TestJobAlerts, The full-stack version of the parquet writer's idempotency property: running… (+6 more)

### Community 118 - "check_poller"
Cohesion: 0.36
Nodes (4): check_poller(), datetime, Orders resting while the feed has been down are the failure to make visible:…, TestPoller

### Community 119 - "evaluate.py"
Cohesion: 0.19
Nodes (21): column_for(), add_prev_columns(), _arith(), _as_series(), _column(), _eval_cond(), eval_node(), eval_operand() (+13 more)

### Community 120 - "devDependencies"
Cohesion: 0.17
Nodes (12): devDependencies, jsdom, openapi-typescript, @testing-library/jest-dom, @testing-library/react, @testing-library/user-event, @types/react, @types/react-dom (+4 more)

### Community 121 - "settings.py"
Cohesion: 0.31
Nodes (9): AppMeta, HttpConfig, HttpEndpointConfig, IngestConfig, ProvidersConfig, BaseModel, Typed application settings. Loads config/defaults.yaml + config/env/{env}.yaml…, YFinanceHttpConfig (+1 more)

### Community 122 - "AppSettings"
Cohesion: 0.32
Nodes (6): AppSettings, pydantic-settings source that loads config/defaults.yaml + env overlay., Root settings object. Construct via ``get_settings()``., _YamlSettingsSource, BaseSettings, PydanticBaseSettingsSource

### Community 123 - "entry_mask"
Cohesion: 0.30
Nodes (5): entry_mask(), frame(), DataFrame, No delivery data / no benchmark / no ROCE must read as 'condition false'., TestInterpreter

### Community 124 - "app.py"
Cohesion: 0.07
Nodes (52): alias, approve(), bars(), brief(), briefs(), health(), openapi_document(), picks() (+44 more)

### Community 125 - "is_liquid"
Cohesion: 0.10
Nodes (19): LiquidityConfig, BaseModel, Loader for config/universe.yaml -- liquidity thresholds and the…, UniverseConfig, is_liquid(), is_tradeable_intraday(), LiquidityMetrics, LiquidityThresholds (+11 more)

### Community 126 - "assert_bars_match_requested_date"
Cohesion: 0.32
Nodes (5): assert_bars_match_requested_date(), Assert every parsed bar's date matches the date we actually requested from the…, Regression tests for a real bug found via live backfill testing: NSE's own…, Even if only some rows are wrong, the whole file must be rejected., TestAssertBarsMatchRequestedDate

### Community 127 - "verify_backup"
Cohesion: 0.36
Nodes (4): Everything that can be checked without restoring: manifest, checksums, the…, verify_backup(), The checksum only proves the file is what was WRITTEN; integrity_check proves…, TestVerify

### Community 128 - "OrderDrawer.tsx"
Cohesion: 0.27
Nodes (7): input, label, num(), OrderDrawer(), OrderType, useCostPreview(), useStock()

### Community 129 - "_make_bars"
Cohesion: 0.14
Nodes (15): Schema, Table, Read a partition file, or return an empty table matching ``schema`` if absent., read_partition(), _make_bars(), date, Table, A stronger idempotency check: not just the same row count, but the same file… (+7 more)

### Community 130 - "Project brief for Claude Code — Indian stock suggester + virtual playground"
Cohesion: 0.14
Nodes (14): 10. Screens (designs come from Claude Design), 11. Build phases (do them in order; stop and check in with me after each), 12. How to work with me, 1. What the app does, 2. Hard constraints, 3. Stack, 4. Data layer, 5. Strategies — four horizons (+6 more)

### Community 131 - "catalogue.py"
Cohesion: 0.38
Nodes (5): _i(), Indicator, Kind, StrEnum, The closed catalogue of indicators a strategy may reference. A spec naming…

### Community 133 - "Data sources — verified endpoints"
Cohesion: 0.29
Nodes (6): Blocking behaviour summary, BSE, Data sources — verified endpoints, Security master, Things still to verify (do not treat as settled), Transaction charges — verification ledger

### Community 134 - "TestParseHolidays"
Cohesion: 0.23
Nodes (5): _artifact(), CBM (corporate bond market) is the first key in NSE's payload and is…, NSE lists holidays falling on a Saturday/Sunday. The PROVIDER must not drop…, An out-of-range year (2010, 2027) returns HTTP 200 with no CM rows. Returning…, TestParseHolidays

### Community 135 - "TestCli"
Cohesion: 0.29
Nodes (3): fixture, `stk backup ...` end to end, pointed at a temp data root through the env…, TestCli

### Community 136 - "main.tsx"
Cohesion: 0.17
Nodes (11): ref_fontsource_ibm_plex_mono_400_css, ref_fontsource_ibm_plex_mono_500_css, ref_fontsource_ibm_plex_mono_600_css, ref_fontsource_ibm_plex_mono_700_css, ref_fontsource_ibm_plex_sans_400_css, ref_fontsource_ibm_plex_sans_500_css, ref_fontsource_ibm_plex_sans_600_css, ref_fontsource_ibm_plex_sans_700_css (+3 more)

### Community 137 - "backtest/walkforward.py"
Cohesion: 0.12
Nodes (19): _outcome(), DataFrame, RatesFn, Walk-forward harness: tune on the training window, judge on the unseen test…, run_walk_forward(), WindowResult, _add_months(), generate_windows() (+11 more)

### Community 140 - "manifest_path"
Cohesion: 0.20
Nodes (10): manifest_path(), Path, Where the row-count + sha256 sidecar for one partition lives. ``exchange`` is…, Path, Streaming sha256 of a file on disk., Write the row-count + sha256 sidecar for a just-written partition. The sha256…, sha256_of_file(), write_manifest() (+2 more)

### Community 143 - "playground/fills.py"
Cohesion: 0.07
Nodes (63): delete_order(), journal(), Convert any numeric input to a Decimal rounded to paise., to_money(), is_market_hours(), now_ist(), datetime, Current wall-clock time in IST. (+55 more)

### Community 144 - "latest_backup_age_days"
Cohesion: 0.40
Nodes (4): latest_backup_age_days(), date, Days since the newest backup, or None if there is none., TestAge

### Community 145 - "TestAuth"
Cohesion: 0.28
Nodes (3): anon(), parametrize, TestAuth

### Community 146 - "ingest_corporate_actions"
Cohesion: 0.20
Nodes (10): CorpActionIngestResult, ingest_corporate_actions(), date, Path, Raised AFTER every row has been stored, naming every subject that matched…, Fetch corporate actions, parse subjects, and upsert into corporate_actions. One…, UnparsedCorporateActionsError, Regression, found on real data: the ingest used to raise on the FIRST unparsed… (+2 more)

### Community 147 - "Runbook"
Cohesion: 0.33
Nodes (6): Backups and restore, Failure playbook, First install, Runbook, Things never verified live, Watching it

### Community 150 - "test_yfinance_intraday.py"
Cohesion: 0.33
Nodes (4): FakeFrame, The intraday provider: gated by its own switch, raw-bytes-first, and strict…, Just enough of a pandas frame for fetch_candles_raw., yfinance

### Community 155 - "Phase 1 — data pipeline + store"
Cohesion: 0.50
Nodes (4): Cost config scaffold, Ingest pipeline, Parquet layout, Phase 1 — data pipeline + store

### Community 160 - "backfill_nse_prices"
Cohesion: 0.13
Nodes (18): backfill_nse_prices(), Path, Ingest every weekday of NSE prices in [start, end] (inclusive), sequentially.…, _bse_fixture_for_date(), _bse_legacy_fixture(), _fixture_for_date(), _mock_bse_date(), _mock_bse_legacy_date() (+10 more)

### Community 172 - "read_manifest"
Cohesion: 0.13
Nodes (14): The manifest for one partition, or None if none was written., read_manifest(), _isolated_config_dir(), fixture, Path, Point STK_CONFIG_DIR at the real repo config/ for every test. Tests run from…, tmp_db_path(), tmp_parquet_root() (+6 more)

### Community 173 - "last_trading_day_on_or_before"
Cohesion: 0.38
Nodes (4): last_trading_day_on_or_before(), date, Walk backward from target (inclusive) to find the nearest trading day. Bounded…, TestLastTradingDayOnOrBefore

### Community 175 - "schema.d.ts"
Cohesion: 0.33
Nodes (5): components, $defs, operations, paths, webhooks

### Community 190 - "get_settings"
Cohesion: 0.06
Nodes (48): evening(), lab(), command, help, Option, Every AI call in the last N days: how it ended, tokens, and the estimated cost., Rank and explain the day's picks, flag conflicts, and write the market brief.…, Weekly strategy lab: ask for new strategy ideas and demotions. Each idea is… (+40 more)

### Community 191 - "make_portfolio"
Cohesion: 0.22
Nodes (5): make_portfolio(), parametrize, TestAuth, TestOrders, TestPortfolios

### Community 192 - "0006_playground.sql"
Cohesion: 0.08
Nodes (38): backtest_equity, backtest_metrics, backtest_runs, backtest_trades, backtest_windows, ix_backtest_runs_strategy, ix_backtest_trades_run, ix_status_events_strategy (+30 more)

### Community 196 - "TestFetchHistory"
Cohesion: 0.29
Nodes (5): _frame(), DataFrame, Yahoo reports no rupee turnover. close*volume is derived and must never be…, An empty result means a wrong ticker, a delisted name, or a rate limit -- never…, TestFetchHistory

### Community 198 - "logging.py"
Cohesion: 0.15
Nodes (12): _init(), configure_logging(), get_logger(), Structured logging setup. JSON output in production (so the systemd journal /…, Configure structlog + stdlib logging. Call once at process startup., BoundLogger, callback, main() (+4 more)

### Community 204 - "get_rate_schedule"
Cohesion: 0.29
Nodes (7): get_rate_schedule(), Path, Return the process-wide RateSchedule singleton, loading config/costs.yaml on…, fixture, schedule(), fixture, schedule()

### Community 206 - "stockAnalyser"
Cohesion: 0.33
Nodes (6): A note on scope, Common commands, Layout, Setup, Status, stockAnalyser

### Community 209 - "MarketData"
Cohesion: 0.12
Nodes (12): AssertionError, prepare_bars(), DataFrame, Load market data for a backtest, and prepare it point-in-time. Everything a…, Add prev_close and adv_turnover (both past-only) to a raw adjusted-bars frame.…, LookAheadError, MarketData, date (+4 more)

### Community 214 - "NseCorporateActionsProvider"
Cohesion: 0.16
Nodes (12): A corporate-action row with the subject text UNPARSED. Parsing free-text…, RawCorporateAction, NseCorporateActionsProvider, _parse_ddmmmyyyy_or_none(), date, Stable hash of the fields that define this action's identity and content --…, CorporateActionsProvider backed by NSE's corporates-corporateActions API., _source_hash() (+4 more)

### Community 215 - "Oracle Cloud Always Free VM — setup notes"
Cohesion: 0.29
Nodes (7): ARM wheel availability (checked), Known friction points during signup, Oracle Cloud Always Free VM — setup notes, Provisioning the instance (once signup succeeds), Swap (important on ARM Always Free), What is set up on this box, What you're aiming for

### Community 226 - "TestAuxiliarySeriesOhlc"
Cohesion: 0.32
Nodes (4): parametrize, Regression for a real failure found by a live backfill (2025-07 .. 2025-11).…, Only the OHLC-ordering check is relaxed -- a non-positive close is wrong…, TestAuxiliarySeriesOhlc

## Knowledge Gaps
- **143 isolated node(s):** `stk`, `raw_artifacts`, `trading_calendar`, `api_tokens`, `poller_runs` (+138 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1349 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **109 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `connect()` connect `connect` to `get_strategy`, `ingest/backfill.py`, `backup`, `migrate`, `backtest/walkforward.py`, `TestNestedTransactions`, `rebuild_adjusted_bars`, `lab.py`, `TestAuth`, `ingest_corporate_actions`, `job_run`, `compute_liquidity_for_date`, `time.py`, `_write`, `commands/playground.py`, `ingest/corpactions.py`, `backfill_nse_prices`, `doctor`, `datetime`, `ingest_security_master`, `TestPicks`, `_mock`, `test_xbrl_ingest.py`, `backtest/runs.py`, `get_settings`, `make_portfolio`, `TestStatusAndBriefs`, `test_nightly.py`, `runner.py`, `ingest.py`, `auth.py`, `ingest_fundamentals_for_security`, `repo.py`, `test_backtest_engine.py`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Why does `Current status (update this section as phases complete)` connect `ingest.py` to `assert_bars_sane`, `lab.py`, `base.py`, `ingest_corporate_actions`, `ingest/corpactions.py`, `Side`, `ingest_security_master`, `CLAUDE.md`, `PointInTimeView`, `RawArtifact`, `ContentValidationError`, `MarketData`, `NseCorporateActionsProvider`, `ingest_fundamentals_for_security`, `backtest/engine.py`, `NotSupportedError`, `upsert_partition`, `ADR 0003: Historical price source`, `app.py`, `is_liquid`, `assert_bars_match_requested_date`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Why does `transaction()` connect `app.py` to `repo.py`, `track_pick`, `migrate`, `TestNestedTransactions`, `datetime`, `ingest_security_master`, `lab.py`, `playground/fills.py`, `connect`, `run_evening_review`, `runner.py`, `ingest.py`, `apply_corporate_actions`, `backtest/runs.py`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **What connects `stk`, `raw_artifacts`, `trading_calendar` to the rest of the system?**
  _143 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `ingest/backfill.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07357357357357357 - nodes in this community are weakly interconnected._
- **Should `package.json` be split into smaller, more focused modules?**
  _Cohesion score 0.06451612903225806 - nodes in this community are weakly interconnected._
- **Should `validate_json_response` be split into smaller, more focused modules?**
  _Cohesion score 0.11965811965811966 - nodes in this community are weakly interconnected._