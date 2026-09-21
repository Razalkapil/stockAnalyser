# Graph Report - stockAnalyser  (2026-09-20)

## Corpus Check
- 314 files · ~199,178 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 40 file(s) not represented in the graph (top: (none) 12, .csv 8, .service 6)

## Summary
- 4618 nodes · 12136 edges · 261 communities (154 shown, 107 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 939 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c5fdadf4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_ai_lab.py
- assert_bars_sane
- get_price_provider
- package.json
- ContentValidationError
- test_deploy.py
- track_pick
- ConfigError
- backup
- connect
- build_factor_rows
- attach_dimensions
- Side
- rebuild_adjusted_bars
- derive_metric_rows
- validate.py
- health.py
- commands/playground.py
- job_run
- compute_metrics
- at
- domain/costs.py
- test_ai_client.py
- App.tsx
- ingest_calendar_year
- settings.py
- _write
- time.py
- IntradayCandle
- poller.py
- 0001_init.sql
- ingest/corpactions.py
- store/backup.py
- Position
- playground_routes.py
- Stocks.tsx
- Argument
- compute_indicators
- place
- transition
- api/schemas.py
- playground.test.tsx
- registry.py
- services.py
- doctor
- run_evening_review
- json
- test_dsl_backtest.py
- commands/backup.py
- parse_xbrl
- test_instruments.py
- stats.py
- Scripted
- flat
- NotSupportedError
- PointInTimeView
- compute_costs
- model.py
- today_ist
- ingest_indices_for_date
- mock
- backtest/runs.py
- test_xbrl_ingest.py
- hooks.ts
- base.py
- passes.py
- yfinance/__init__.py
- queries/__init__.py
- stk
- test_nightly.py
- errors_of
- NSE
- runner.py
- strategies/promotion.py
- check_ai_runs
- api.py
- nse/fundamentals.py
- apply_corporate_actions
- auth.py
- _mock
- semantic_problems
- pydantic
- eval_node
- TestAuth
- ai/schemas.py
- list_backups
- client.py
- _write_bars
- apiGet
- promote
- spec_problems
- datetime
- lab.py
- test_backtest_engine.py
- CanonicalBar
- xirr
- build_lab_input
- compilerOptions
- TestParseHolidays
- check_job_runs
- BaseModel
- check_poller
- Bar
- CostRates
- Any
- BriefListItem
- Pick
- get_strategy
- compute_liquidity_for_date
- ProposalOut
- StockDetail
- Playground.tsx
- upsert_partition
- Indian stock suggester + virtual playground — build plan
- StockHit
- backtest/__init__.py
- ingest_security_master
- is_weekend
- StrategyDetail
- circuit_lock
- BseLegacyBhavcopyProvider
- StrategySummary
- main.tsx
- config/backtest.py
- exists
- ai/__init__.py
- scan
- ingest_corporate_actions
- deps.py
- Brief
- TestUrlAndCapabilities
- Status
- test_health.py
- dsl/__init__.py
- strategies/__init__.py
- check_security_lifecycle
- NseSecBhavdataProvider
- entry_mask
- backup.sh
- install.sh
- restore.sh
- ingest/backfill.py
- track_picks
- playground/fills.py
- make_portfolio
- stk_api_deps
- test_costs_compute.py
- stk_backtest_runs
- is_liquid
- TestStatusAndBriefs
- test_master_ingest.py
- TestCli
- fundamentals_xbrl.py
- latest_backup_age_days
- ticker_for
- app.py
- schema.d.ts
- generate_windows
- Current status (update this section as phases complete)
- 0009_instrument_class.sql
- lifecycle_status
- ref_testing_library_jest_dom_vitest
- Argument
- .fetch_document
- TestPlacing
- exists
- RuntimeError
- get_settings
- stk_core_money
- DataFrame
- transaction
- parse_sec_bhavdata_full
- 0006_playground.sql
- stk_domain_costs
- test_yfinance_provider.py
- TestStrategies
- TestFetchHistory
- command
- help
- Option
- run_backtest
- check_backup_age
- get_rate_schedule
- stk_domain_fills
- TestSeeds
- stk_domain_indicators
- stk_domain_metrics
- BaseModel
- stk_domain_slippage
- listings
- get_fundamentals_provider
- nse/corpactions.py
- Protocol
- TestStocks
- conftest.py
- RuntimeError
- TestLiveEndpoint
- backtest/engine.py
- ValueError
- world
- validate
- command
- stk_ingest_normalise
- check_fundamentals_freshness
- help
- stk_playground_performance
- Option
- fixture
- parametrize
- Phase 1 — data pipeline + store
- stk_providers_yfinance_prices
- Connection
- check_adjusted_freshness
- .test_without_the_exclusion_the_funds_would_be_picked
- test_costs.py
- TestCostPreview
- test_schema_drift.py
- provider
- test_nse_udiff_provider.py
- ValueError
- stk_ingest_fundamentals_xbrl
- TestExchangeTxnBoundary
- fixture
- date
- TestCaddyfile
- parametrize
- mock
- datetime
- stk_ingest_xbrl
- mock
- stk_ai_lab_inputs
- stk_ai_prompts
- fixture
- parametrize
- XbrlFacts
- Connection
- parametrize
- Path
- BaseModel
- StrEnum

## God Nodes (most connected - your core abstractions)
1. `connect()` - 96 edges
2. `_mock()` - 74 edges
3. `migrate()` - 72 edges
4. `RawArtifact` - 61 edges
5. `get_settings()` - 61 edges
6. `place()` - 50 edges
7. `Current status (update this section as phases complete)` - 42 edges
8. `Side` - 42 edges
9. `candle()` - 42 edges
10. `DataNotPublished` - 41 edges

## Surprising Connections (you probably didn't know these)
- `Working here` --references--> `live()`  [INFERRED]
  CLAUDE.md → tests/integration/test_picks_pipeline.py
- `Daily EOD prices (primary source): `sec_bhavdata_full`` --references--> `NseSecBhavdataProvider`  [INFERRED]
  docs/data-sources.md → backend/src/stk/providers/nse/prices.py
- `Ingest pipeline` --references--> `ContentValidationError`  [INFERRED]
  docs/BUILD_PLAN.md → backend/src/stk/core/errors.py
- `Verification` --references--> `ContentValidationError`  [INFERRED]
  docs/BUILD_PLAN.md → backend/src/stk/core/errors.py
- `Failure playbook` --references--> `ContentValidationError`  [INFERRED]
  docs/runbook.md → backend/src/stk/core/errors.py

## Import Cycles
- None detected.

## Communities (261 total, 107 thin omitted)

### Community 0 - "test_ai_lab.py"
Cohesion: 0.15
Nodes (11): list_proposals(), fastapi_testclient, idea(), Model, The weekly strategy lab against a fake model: validation, backtest, gate, and…, reply(), run(), TestApi (+3 more)

### Community 1 - "assert_bars_sane"
Cohesion: 0.07
Nodes (34): IngestAssertionError, A post-ingest sanity check failed (row counts, OHLC invariants, ...)., assert_bars_match_requested_date(), assert_bars_sane(), assert_index_bars_match_requested_date(), assert_index_bars_sane(), _assert_turnover_plausible(), _judge_delivery_violations() (+26 more)

### Community 2 - "get_price_provider"
Cohesion: 0.06
Nodes (29): KitePriceProvider, Zerodha Kite Connect adapter -- a deliberate, documented STUB. Why it exists:…, Placeholder. Constructing it raises, so selecting ``kite`` in config fails at…, NseLegacyBhavcopyProvider, PriceProvider backed by NSE's legacy per-date cm*bhav.csv.zip archive., get_bse_price_provider_for_date(), get_nse_price_provider_for_date(), get_price_provider() (+21 more)

### Community 3 - "package.json"
Cohesion: 0.05
Nodes (42): @fontsource/ibm-plex-mono, @fontsource/ibm-plex-sans, jsdom, lightweight-charts, openapi-typescript, react-dom, @testing-library/jest-dom, @types/react (+34 more)

### Community 4 - "ContentValidationError"
Cohesion: 0.08
Nodes (30): ContentValidationError, A response passed HTTP status but failed content-type/magic-byte checks. This…, build_client(), Response, Shared HTTP client factory and response validation. This module is the single…, Validate a response that is expected to be an XBRL/XML document. Guards the…, Construct an httpx.Client with sane defaults for exchange fetches., Validate a response that is expected to be a zip file. Checks status, then… (+22 more)

### Community 5 - "test_deploy.py"
Cohesion: 0.11
Nodes (19): ConfigParser, Path, shlex, shutil, skipif, stk_cli_main, parse(), The deploy artifacts, checked against the code they invoke. Nothing here runs… (+11 more)

### Community 6 - "track_pick"
Cohesion: 0.14
Nodes (14): Bar, _exit_on(), Live pick tracking -- pure. Given the bars that followed a pick's signal date,…, ``bars`` must be strictly AFTER the signal date, in date order., track_pick(), TrackedPick, bar(), flat() (+6 more)

### Community 7 - "ConfigError"
Cohesion: 0.15
Nodes (17): _DatedRate, _DatedSeries, _dec(), BaseModel, date, Decimal, RateSchedule, product() (+9 more)

### Community 8 - "backup"
Cohesion: 0.13
Nodes (9): at(), backup(), date, datetime, parametrize, The checksum only proves the file is what was WRITTEN; integrity_check proves…, Copying app.db while the API is writing can miss WAL content or copy a torn…, TestRun (+1 more)

### Community 9 - "connect"
Cohesion: 0.05
Nodes (47): FundamentalsIngestResult, ingest_fundamentals_for_security(), Path, Fetch one security's recent filings and upsert into fundamentals_snapshots. One…, connect(), _discover_migrations(), migrate(), Path (+39 more)

### Community 10 - "build_factor_rows"
Cohesion: 0.09
Nodes (33): ActionFactor, build_factor_rows(), _factor_table(), FactorRow, factors_for_bar(), load_actions(), _LoadedActions, BaseModel (+25 more)

### Community 11 - "attach_dimensions"
Cohesion: 0.07
Nodes (23): attach_dimensions(), _attach_via_arrow(), DimensionMode, DuckSession, _load_named_queries(), named_query(), Path, Schema (+15 more)

### Community 12 - "Side"
Cohesion: 0.08
Nodes (40): Side, can_buy(), can_sell(), Lock, StrEnum, Fill-price rules -- pure. Two rules matter and both are easy to get subtly…, _blocked(), Fill (+32 more)

### Community 13 - "rebuild_adjusted_bars"
Cohesion: 0.10
Nodes (27): AdjustmentResult, Path, Rebuild adjustment_factors and bars_daily_adjusted for one exchange. Network-…, rebuild_adjusted_bars wrapped in a job_run scope. Kept separate so the rebuild…, rebuild_adjusted_bars(), rebuild_adjusted_bars_job(), adjustment_factors_path(), bars_daily_adjusted_partition() (+19 more)

### Community 14 - "derive_metric_rows"
Cohesion: 0.08
Nodes (33): attach_fundamentals(), available_on(), _borrowings(), _cagr(), derive_metric_rows(), FilingFacts, DataFrame, date (+25 more)

### Community 15 - "validate.py"
Cohesion: 0.18
Nodes (21): _i(), Indicator, Kind, StrEnum, The closed catalogue of indicators a strategy may reference. A spec naming…, Add, Div, Mul (+13 more)

### Community 16 - "health.py"
Cohesion: 0.18
Nodes (18): `stk doctor` -- ingest health check. Thin by design: every actual check lives…, check_calendar_coverage(), check_instrument_classes(), check_stale_symbols(), check_unparsed_corporate_actions(), Problem, date, Path (+10 more)

### Community 17 - "commands/playground.py"
Cohesion: 0.09
Nodes (30): create_app(), openapi_document(), Path, The OpenAPI JSON, deterministic, with no database or lake needed to produce it., make_rates_fn(), RatesFn, Rates in force on each fill's own date, memoised per (exchange, date)., _ctx() (+22 more)

### Community 18 - "job_run"
Cohesion: 0.08
Nodes (24): code_version(), The running code's version, for attributing written data to a commit. Both…, Short git SHA of HEAD, or "unknown" outside a git checkout. Never raises: an…, job_run(), JobRunHandle, JobSkipped, _next_attempt(), Connection (+16 more)

### Community 19 - "compute_metrics"
Cohesion: 0.10
Nodes (17): cagr(), compute_metrics(), max_drawdown(), date, Backtest performance metrics -- pure. Statistics, not money: inputs are…, One closed round trip, net of all costs., Worst peak-to-trough decline as a NEGATIVE fraction (0.0 if never below a peak)., Annualised Sharpe from daily equity. 0.0 when there is no variance to divide by. (+9 more)

### Community 20 - "at"
Cohesion: 0.12
Nodes (17): Write MANY symbols across the year partitions in one go (both bars datasets). A…, write_panel_by_year(), at(), date, datetime, Rs 10 lakh deposited exactly 365 days ago, now worth Rs 11 lakh: XIRR is 10%., FakeFeed, poll() (+9 more)

### Community 21 - "domain/costs.py"
Cohesion: 0.10
Nodes (22): command, quote(), `stk costs` -- inspect the transaction-cost model., Itemise the charges on one order leg, using the rates in force on a date. Rates…, bps(), format_inr(), Decimal, Decimal-safe money arithmetic and Indian-style (lakh/crore) formatting. Every… (+14 more)

### Community 22 - "test_ai_client.py"
Cohesion: 0.16
Nodes (9): call(), err(), groq(), ok(), Structured calling: fences, one retry with the errors, and never raising., TestGroqFailures, TestGroqRequestAndReply, handler() (+1 more)

### Community 23 - "App.tsx"
Cohesion: 0.11
Nodes (31): react, queryClient, Shell(), EmptyState(), PickMarker, PriceChart(), Segmented(), bar (+23 more)

### Community 24 - "ingest_calendar_year"
Cohesion: 0.10
Nodes (27): CalendarIngestResult, ingest_calendar_from_bars(), ingest_calendar_year(), Connection, date, Path, Populate one calendar year for one exchange from NSE's holiday master. Writes a…, Derive calendar rows from the dates actually present in bars_daily. Covers only… (+19 more)

### Community 25 - "settings.py"
Cohesion: 0.13
Nodes (17): AppMeta, AppSettings, HttpConfig, HttpEndpointConfig, IngestConfig, PathsConfig, ProvidersConfig, BaseModel (+9 more)

### Community 26 - "_write"
Cohesion: 0.09
Nodes (12): _bars(), date, fixture, Path, Table, The load-bearing case for query-time identity resolution: a bar written under a…, exchange/year come from the directory names, not the file -- the liquidity and…, A fresh checkout has no bars_daily_adjusted. Querying it must return zero rows… (+4 more)

### Community 27 - "time.py"
Cohesion: 0.06
Nodes (36): format_ddmmyy_compact(), format_ddmmyyyy_compact(), format_yyyymmdd(), parse_ddmmmyyyy(), parse_ddmmyyyy_compact(), previous_calendar_day(), date, IST timezone helpers and trading-day arithmetic primitives. All business logic… (+28 more)

### Community 28 - "IntradayCandle"
Cohesion: 0.09
Nodes (17): IntradayCandle, datetime, One intraday OHLCV candle. ``start`` is timezone-AWARE (IST) -- naive datetimes…, Parse a previously fetched artifact (offline; no network)., parse_candles_json(), Pure: bytes -> candles, sorted by start, in IST. Rejects a malformed record…, YFinanceIntradayProvider, field_validator (+9 more)

### Community 29 - "poller.py"
Cohesion: 0.12
Nodes (27): PollerConfig, BaseModel, is_market_hours(), now_ist(), datetime, Current wall-clock time in IST., Whether the given (or current) IST instant is within 9:15-15:30. Does not check…, is_trading_day() (+19 more)

### Community 30 - "0001_init.sql"
Cohesion: 0.14
Nodes (23): corporate_actions, fundamentals_snapshots, ix_ca_exdate, ix_ca_parse_status, ix_ca_security_ex, ix_fund_provider, ix_fund_sec_period, ix_job_lookup (+15 more)

### Community 31 - "ingest/corpactions.py"
Cohesion: 0.06
Nodes (68): ActionType, _bond_interest(), _bonus(), _cash_distribution(), _cash_dividend(), _ClauseResult, _face_value_change(), build() (+60 more)

### Community 32 - "store/backup.py"
Cohesion: 0.16
Nodes (22): _backup_dirs(), BackupResult, _check_archive(), _check_database(), _check_files(), _is_within(), datetime, Path (+14 more)

### Community 33 - "Position"
Cohesion: 0.13
Nodes (17): apply_buy(), apply_sell(), apply_split_or_bonus(), dividend_cash(), Position, PositionError, Decimal, ValueError (+9 more)

### Community 34 - "playground_routes.py"
Cohesion: 0.08
Nodes (37): _index_moves(), date, Path, Assemble the evening review's input from what the pipeline already stored.…, _err(), _f(), play_ctx(), Decimal (+29 more)

### Community 35 - "Stocks.tsx"
Cohesion: 0.18
Nodes (23): Num(), label, PickCard(), useBars(), useStock(), DASH, fmtClock(), fmtDate() (+15 more)

### Community 37 - "compute_indicators"
Cohesion: 0.08
Nodes (32): all_columns(), Every concrete column name the catalogue can produce., _breakout_levels(), compute_indicators(), _grouped(), _momentum(), _oscillators(), DataFrame (+24 more)

### Community 38 - "place"
Cohesion: 0.11
Nodes (18): cash_balance(), Cash is the LAST ledger row's balance -- there is no other copy to fall out of…, candle(), ledger_reconciles(), order(), place(), The paper-trading ledger, end to end: orders -> fills -> cash/positions ->…, If booking fails part-way (here: a sell that no longer has the shares), no cash… (+10 more)

### Community 39 - "transition"
Cohesion: 0.25
Nodes (6): IllegalTransition, ValueError, Return ``new`` if the move is legal, else raise. Terminal orders never change…, transition(), parametrize, TestStateMachine

### Community 40 - "api/schemas.py"
Cohesion: 0.08
Nodes (45): new_portfolio(), portfolio(), portfolios(), preview(), get, post, What an order would cost, using the SAME model the fills use -- so the ticket's…, _summary() (+37 more)

### Community 41 - "playground.test.tsx"
Cohesion: 0.13
Nodes (28): react-router-dom, @tanstack/react-query, @testing-library/react, @testing-library/user-event, vitest, TicketProbe(), StaleBanner(), StatusPill() (+20 more)

### Community 42 - "registry.py"
Cohesion: 0.06
Nodes (42): Connection, Fundamentals ingest: fetch a security's filings and upsert into…, _resolve_security_id(), Path, Sweep the liquid universe's filing metadata (quarterly + annual) into…, sweep_liquid_universe(), SweepResult, upsert_snapshot() (+34 more)

### Community 43 - "services.py"
Cohesion: 0.13
Nodes (31): _brief_dates(), build_status(), _company_names(), expected_data_date(), _fundamentals_for(), get_brief(), _job_alerts(), latest_bar_date() (+23 more)

### Community 44 - "doctor"
Cohesion: 0.17
Nodes (12): _check_endpoints(), doctor(), _previous_weekday(), command, date, help, Option, Path (+4 more)

### Community 45 - "run_evening_review"
Cohesion: 0.11
Nodes (24): AiConfig, Connection, date, The evening review: one model call per day, validated, stored, and NEVER…, _record(), ReviewResult, run_evening_review(), _store() (+16 more)

### Community 46 - "json"
Cohesion: 0.06
Nodes (40): load_market_data(), prepare_bars(), DataFrame, Load market data for a backtest, and prepare it point-in-time. Everything a…, Add prev_close and adv_turnover (both past-only) to a raw adjusted-bars frame.…, Adjusted bars for [start - warmup, end], prepared for the engine., The only window a strategy gets onto the data. A strategy decides on the close…, Turn stored XBRL line items into point-in-time fundamental metric rows. Reads… (+32 more)

### Community 47 - "test_dsl_backtest.py"
Cohesion: 0.16
Nodes (17): DslStrategy, prepare_frame(), DataFrame, Series, Raw adjusted bars -> the frame a ``DslStrategy`` and the engine both read., engine_config(), make_bars(), oversold_spec() (+9 more)

### Community 48 - "commands/backup.py"
Cohesion: 0.14
Nodes (20): list_cmd(), command, help, Option, Path, `stk backup` -- back up, verify and restore the application state., Snapshot app.db (consistent, WAL-safe) and the lake; verify; rotate. app.db…, Check a backup directory: checksums, database integrity, readable archives. (+12 more)

### Community 49 - "parse_xbrl"
Cohesion: 0.06
Nodes (32): _index_facts(), _local(), _parse_date(), parse_xbrl(), take(), _plain_contexts(), date, Parse an NSE Ind-AS XBRL filing into normalised line items. WHAT THE REAL… (+24 more)

### Community 50 - "test_instruments.py"
Cohesion: 0.13
Nodes (17): classes_known(), classify_isin(), fund_symbols(), ingest_instrument_classes(), Connection, date, Path, Classify traded symbols as company shares or funds (ETFs / mutual-fund units).… (+9 more)

### Community 51 - "stats.py"
Cohesion: 0.12
Nodes (21): DecayConfig, load_promotion_config(), PromotionConfig, BaseModel, Path, Typed loader for config/promotion.yaml., GateThresholds, backtest_stats() (+13 more)

### Community 52 - "Scripted"
Cohesion: 0.18
Nodes (10): Out, BaseModel, Replies with each scripted item in turn; an Exception item is raised., reply(), run(), Scripted, TestFailureModes, TestInputGuard (+2 more)

### Community 53 - "flat"
Cohesion: 0.27
Nodes (7): buy(), flat(), run(), TestCircuitLocks, TestFillTiming, TestParticipationCap, TestStopsAndTargets

### Community 54 - "NotSupportedError"
Cohesion: 0.06
Nodes (28): NotSupportedError, A provider does not implement an optional capability., ProviderCapabilities, Filings from the newer "Integrated Filing" system, which replaced the legacy…, Declares what a provider can actually do, so callers can degrade gracefully…, BseUdiffProvider, date, PriceProvider backed by BSE's UDiFF daily bhavcopy. (+20 more)

### Community 55 - "PointInTimeView"
Cohesion: 0.10
Nodes (20): AssertionError, Protocol, An intent to buy at the next open., Signal, Strategy, LookAheadError, PointInTimeView, DataFrame (+12 more)

### Community 56 - "compute_costs"
Cohesion: 0.18
Nodes (11): compute_costs(), Product, StrEnum, Itemised charges for one order leg of ``turnover`` rupees. Excludes the DP…, date, rates(), Rs 5,000 NSE delivery sell on 2026-09-18 (post 2026-03-01 rates)., Rs 13 + 18% GST = Rs 15.34; on Rs 5,000 that is ~30.7 bps -- the build plan's… (+3 more)

### Community 57 - "model.py"
Cohesion: 0.12
Nodes (31): explain(), prev_columns_needed(), The DSL interpreter: a validated ``StrategySpec`` + a feature frame -> masks…, Columns whose previous-day value the spec's crosses_* conditions read., Human-readable rule lines (what the Strategy lab's `rules[]` shows)., resolve_params(), All, Cond (+23 more)

### Community 58 - "today_ist"
Cohesion: 0.09
Nodes (25): prompt_json(), The prompt payload as COMPACT, deterministic JSON. Indentation is whitespace…, evening(), lab(), AiConfig, Every AI call in the last N days: how it ended, tokens, and the estimated cost., Prompt size, and whether the configured guard would refuse it (~4 characters a…, Rank and explain the day's picks, flag conflicts, and write the market brief.… (+17 more)

### Community 59 - "ingest_indices_for_date"
Cohesion: 0.09
Nodes (21): IndicesIngestResult, ingest_indices_for_date(), date, Path, Table, Ingest one day of NSE index closes end-to-end. Idempotent., _to_table(), _guess_suffix() (+13 more)

### Community 60 - "mock"
Cohesion: 0.15
Nodes (9): NseFundamentalsProvider, FundamentalsProvider backed by NSE's corporates-financial-results API., mock, integrated_payload(), Seen live: a filing landing between NSE's count and its page (16 vs 15, then…, TestFetchFilingsIndex, TestFetchStatements, TestIntegratedFilings (+1 more)

### Community 61 - "backtest/runs.py"
Cohesion: 0.24
Nodes (17): BacktestResult, _begin(), _finish(), _insert_trades(), load_run_summary(), _metric_rows(), Connection, date (+9 more)

### Community 62 - "test_xbrl_ingest.py"
Cohesion: 0.26
Nodes (10): add_snapshot(), meta_row(), Path, XBRL ingest end to end: real filings served through a mocked network., A parser fix takes effect on documents already on disk -- no network., rows(), run(), TestIngest (+2 more)

### Community 63 - "hooks.ts"
Cohesion: 0.12
Nodes (28): ref_schema, useProposalAction(), useProposals(), useStrategies(), useStrategy(), useStrategyAction(), Bar, Brief (+20 more)

### Community 64 - "base.py"
Cohesion: 0.05
Nodes (65): ABC, DataNotPublished, ParseError, ProviderUnavailable, Transport-level failure: timeout, connection refused, DNS, 5xx., The source has not yet published data for the requested date. Distinct from…, A response was structurally valid but semantically un-parseable. Used by the…, CalendarProvider (+57 more)

### Community 65 - "passes.py"
Cohesion: 0.21
Nodes (23): Candle, FillContext, Where a fill's price came from -- recorded on every trade and shown in the UI., active_orders(), eod_pass(), _evaluate(), intraday_pass(), _lock() (+15 more)

### Community 69 - "test_nightly.py"
Cohesion: 0.05
Nodes (54): _finish(), nightly(), command, help, Option, `stk nightly` / `stk weekly` -- the scheduled runs (systemd timers call these)., Corporate actions, prices, indices, liquidity, scan, track, paper EOD, AI…, Security master, calendar, filings + XBRL, then the AI strategy lab. (+46 more)

### Community 84 - "errors_of"
Cohesion: 0.11
Nodes (7): param_combinations(), Every grid combination (or just the defaults when nothing has a grid)., errors_of(), close > 500 would mean different things depending on when corporate actions…, spec_dict(), TestSchemaStrictness, TestSemanticValidation

### Community 85 - "NSE"
Cohesion: 0.12
Nodes (16): index_archive_url(), NseIndicesProvider, date, Fetches NSE's daily all-index close file., Fetch one date's index file, validated and ready to persist., Corporate actions, Daily EOD prices (ISIN-bearing companion): UDiFF, Daily EOD prices (primary source): `sec_bhavdata_full` (+8 more)

### Community 86 - "runner.py"
Cohesion: 0.09
Nodes (36): build_engine_config(), approx_reasons(), benchmark_reason(), build_market_data(), indicators_used(), node(), operand(), LakeSpan (+28 more)

### Community 87 - "strategies/promotion.py"
Cohesion: 0.13
Nodes (14): evaluate_gate(), GateCheck, GateReport, The promotion gate -- pure. A strategy goes live only if, over its walk-forward…, WindowSummary, Run a strategy through walk-forward and the promotion gate, then record the…, (new status, reason) for a gate verdict., status_for() (+6 more)

### Community 88 - "check_ai_runs"
Cohesion: 0.38
Nodes (4): check_ai_runs(), The AI never blocks the pipeline, which means its failures are silent unless…, _ai_run(), TestAiRuns

### Community 89 - "api.py"
Cohesion: 0.14
Nodes (16): list_tokens(), Row, HTTP API for the dashboard. Reads what the pipeline wrote; never calls an LLM…, openapi(), command, help, Option, Path (+8 more)

### Community 90 - "nse/fundamentals.py"
Cohesion: 0.18
Nodes (14): _fetch_rows(), _integrated_row_to_snapshot(), _parse_broadcast_at(), _parse_integrated_ts(), NSE fundamentals provider -- filing METADATA, not parsed line items. Verified…, One integrated-filing row. Differences from the legacy feed, all live-verified:…, 17-Jul-2026 19:50:03' (or upper-case '19-SEP-2026 15:17:04') -- %b is case-…, _row_to_snapshot() (+6 more)

### Community 91 - "apply_corporate_actions"
Cohesion: 0.32
Nodes (7): apply_corporate_actions(), CorpActionResult, date, get_position(), add_action(), NSE republishing a corrected subject creates a second row by design., TestCorporateActions

### Community 92 - "auth.py"
Cohesion: 0.33
Nodes (8): create_token(), hash_token(), Connection, Single-user bearer-token auth. Only a SHA-256 of each token is stored, so a…, Create a named token and return it. This is the ONLY time it is available in…, revoke_token(), verify_token(), secrets

### Community 93 - "_mock"
Cohesion: 0.08
Nodes (29): _bars_to_table(), _enrich_identity(), _identity_map(), ingest_bse_prices_for_date(), ingest_nse_prices_for_date(), _ingest_prices_for_date(), IngestResult, Connection (+21 more)

### Community 94 - "semantic_problems"
Cohesion: 0.45
Nodes (3): semantic_problems(), ReviewInput, TestSemanticChecks

### Community 95 - "pydantic"
Cohesion: 0.10
Nodes (22): StructuredResult, Connection, datetime, Recording an AI call in ``ai_runs`` -- one place, so every kind is logged the…, Insert the row; returns (run_id, estimated cost in USD or None if the model is…, record_run(), AiConfig, EveningReviewConfig (+14 more)

### Community 96 - "eval_node"
Cohesion: 0.15
Nodes (19): column_for(), add_prev_columns(), _arith(), _as_series(), _column(), _eval_cond(), eval_node(), eval_operand() (+11 more)

### Community 97 - "TestAuth"
Cohesion: 0.28
Nodes (3): anon(), parametrize, TestAuth

### Community 98 - "ai/schemas.py"
Cohesion: 0.39
Nodes (7): EveningReview, HorizonReview, BaseModel, RankedPick, The shape of an evening review. Kept flat and simple: it is what the model is…, _Strict, SymbolNote

### Community 100 - "client.py"
Cohesion: 0.09
Nodes (30): AnthropicClient, call_structured(), _errors(), _groq_error_body(), _groq_failure(), GroqClient, LlmClient, LlmError (+22 more)

### Community 101 - "_write_bars"
Cohesion: 0.18
Nodes (13): check_partition_manifests(), Every partition file against its recorded row count and sha256. A mismatch…, _add_calendar(), date, Path, Trading days before the first ingested bar are history we have not backfilled…, A fresh install must not report every symbol as stale., The whole point of the manifest: a file rewritten without going through… (+5 more)

### Community 102 - "apiGet"
Cohesion: 0.25
Nodes (11): SearchBox(), apiDelete(), ApiError, apiGet(), apiPatch(), apiPost(), getToken(), request() (+3 more)

### Community 103 - "promote"
Cohesion: 0.15
Nodes (21): LabResult, AiConfig, Connection, date, Path, run_strategy_lab(), promote_cmd(), Walk-forward backtest, then the promotion gate. Records the run and the status… (+13 more)

### Community 104 - "spec_problems"
Cohesion: 0.11
Nodes (18): lab_problems(), Everything that can be wrong with a proposed spec, checked without running…, Semantic problems in a reply. Drives the retry; per-idea failures are handled…, Demotion, LabReply, NewStrategyIdea, BaseModel, What the weekly lab is asked to emit. The strategy itself travels as a JSON… (+10 more)

### Community 105 - "datetime"
Cohesion: 0.07
Nodes (53): Exception hierarchy for the ingest/provider stack. The rule this hierarchy…, Trading-calendar domain logic built from raw holiday data. Combines a…, _adjust_bar(), Decimal, Corporate-action back-adjustment: factor timelines and the derived…, Trading-calendar ingest: populating `trading_calendar` from NSE, and from what…, Nightly ingest orchestration. NSE and BSE prices both go through…, Index (benchmark) ingest. Same shape as ingest.daily's price path -- fetch,… (+45 more)

### Community 106 - "lab.py"
Cohesion: 0.09
Nodes (33): The weekly strategy lab. input (DB + the DSL's own catalogue and schema) -> ONE…, Prompts. Static and small; all variable content travels in the user message as…, `stk ai` -- the evening review and AI spend., `stk db` -- database management commands., list_cmd(), command, `stk scan` and `stk picks` -- generate, track and list live picks., Run every live/decaying strategy on a date and record its picks (idempotent). (+25 more)

### Community 107 - "test_backtest_engine.py"
Cohesion: 0.11
Nodes (24): MarketData, Adjusted daily bars for one exchange (+ optional point-in-time tables).…, Fundamentals (official filing metadata + XBRL documents), config(), days_of(), make_data(), poison_after(), Bar (+16 more)

### Community 108 - "CanonicalBar"
Cohesion: 0.05
Nodes (35): canonical_index_code(), _decimal_or_none(), _int_or_none(), parse_bse_legacy_bhavcopy(), parse_ind_close_all(), _parse_iso_date(), parse_legacy_bhavcopy(), parse_udiff() (+27 more)

### Community 109 - "xirr"
Cohesion: 0.18
Nodes (11): _bisect(), _dnpv(), _npv(), date, XIRR -- pure. Annualised internal rate of return for dated cash flows, on the…, Rate as a fraction (0.12 = 12% a year), or None if undefined., xirr(), Flow (+3 more)

### Community 110 - "build_lab_input"
Cohesion: 0.12
Nodes (25): build_lab_input(), catalogue_doc(), dsl_schema(), Any, Connection, Path, _r(), Assemble the strategy lab's input: what exists, how it is doing, and what the… (+17 more)

### Community 111 - "compilerOptions"
Cohesion: 0.11
Nodes (17): compilerOptions, isolatedModules, jsx, lib, module, moduleResolution, noEmit, noFallthroughCasesInSwitch (+9 more)

### Community 112 - "TestParseHolidays"
Cohesion: 0.23
Nodes (5): _artifact(), CBM (corporate bond market) is the first key in NSE's payload and is…, NSE lists holidays falling on a Saturday/Sunday. The PROVIDER must not drop…, An out-of-range year (2010, 2027) returns HTTP 200 with no CM rows. Returning…, TestParseHolidays

### Community 116 - "check_job_runs"
Cohesion: 0.33
Nodes (4): check_job_runs(), Degraded or failed job runs in the lookback window. Only the LATEST attempt per…, job_runs is observability, not a lock -- repeated attempts are expected, and…, TestJobRuns

### Community 118 - "check_poller"
Cohesion: 0.36
Nodes (4): check_poller(), datetime, Orders resting while the feed has been down are the failure to make visible:…, TestPoller

### Community 120 - "CostRates"
Cohesion: 0.50
Nodes (3): CostRates, ProductRates, Every rate in force on one date for one exchange.

### Community 121 - "Any"
Cohesion: 0.17
Nodes (16): load_horizons(), Path, Typed loader for config/horizons.yaml -> the DSL validator's HorizonWindow map., _deep_merge(), find_config_dir(), load_named_yaml(), load_yaml_config(), Path (+8 more)

### Community 124 - "get_strategy"
Cohesion: 0.10
Nodes (30): approve(), StrategySummary, Take a gated candidate live. Refuses anything that has not passed the gate., Take a strategy out of service. Requires explicit confirmation., retire(), One backtest over a single span (no walk-forward, no gate). Stores the run. Use…, run(), explain_cmd() (+22 more)

### Community 125 - "compute_liquidity_for_date"
Cohesion: 0.12
Nodes (23): UniverseConfig, build_liquidity_daily_table(), compute_liquidity_for_date(), compute_liquidity_metrics(), LiquidityResult, Connection, date, Path (+15 more)

### Community 128 - "Playground.tsx"
Cohesion: 0.09
Nodes (24): EquityChart(), points(), input, label, num(), OrderDrawer(), OrderType, useCancelOrder() (+16 more)

### Community 129 - "upsert_partition"
Cohesion: 0.07
Nodes (36): manifest_path(), Where the row-count + sha256 sidecar for one partition lives. ``exchange`` is…, Path, Schema, Table, Overwrite-by-partition write. Returns the row count of the resulting file.…, Read a partition file, or return an empty table matching ``schema`` if absent., Streaming sha256 of a file on disk. (+28 more)

### Community 130 - "Indian stock suggester + virtual playground — build plan"
Cohesion: 0.04
Nodes (40): Context, Decisions locked this session, Design system (extracted from the handoff), Guiding principles for phases 0–1, Indian stock suggester + virtual playground — build plan, Open items for later phases, Phase 0 — repo, config, VM notes, history spike, Phases 2–8 (outline only) (+32 more)

### Community 133 - "ingest_security_master"
Cohesion: 0.10
Nodes (22): LifecycleConfig, load_universe_config(), Path, Suspension/delisting detection from absence across security-master snapshots., _fetch_all_records(), ingest_security_master(), MasterIngestResult, Connection (+14 more)

### Community 134 - "is_weekend"
Cohesion: 0.11
Nodes (13): is_weekend(), True for Saturday/Sunday. NSE's holiday-master API includes holidays that fall…, build_trading_day_set(), last_trading_day_on_or_before(), date, All weekday dates in [start, end] that are not in holiday_dates., Walk backward from target (inclusive) to find the nearest trading day. Bounded…, date (+5 more)

### Community 136 - "circuit_lock"
Cohesion: 0.25
Nodes (8): BarPrices, circuit_lock(), Decimal, Classify a bar as upper-locked, lower-locked or neither. See module docstring., frozen(), Slippage tiers, participation cap, circuit-lock heuristic., An illiquid name that simply didn't trade and closed +3.2% is not locked., TestCircuitLock

### Community 137 - "BseLegacyBhavcopyProvider"
Cohesion: 0.12
Nodes (17): fetch_bse_csv_file(), fetch_bse_zip_file(), _get_and_check_shell(), date, Response, GET the URL and raise DataNotPublished if the response is BSE's SPA shell --…, GET and content-validate a zip file from www.bseindia.com. Used by the legacy…, _to_artifact() (+9 more)

### Community 139 - "main.tsx"
Cohesion: 0.17
Nodes (11): ref_fontsource_ibm_plex_mono_400_css, ref_fontsource_ibm_plex_mono_500_css, ref_fontsource_ibm_plex_mono_600_css, ref_fontsource_ibm_plex_mono_700_css, ref_fontsource_ibm_plex_sans_400_css, ref_fontsource_ibm_plex_sans_500_css, ref_fontsource_ibm_plex_sans_600_css, ref_fontsource_ibm_plex_sans_700_css (+3 more)

### Community 140 - "config/backtest.py"
Cohesion: 0.16
Nodes (20): Turn config files into the engine's inputs., BacktestConfig, BaseModel, Typed loader for config/backtest.yaml., SlippageTierConfig, WalkForwardConfig, Applies when trailing ADV turnover >= ``min_adv_turnover_inr``., SlippageTier (+12 more)

### Community 143 - "scan"
Cohesion: 0.19
Nodes (12): Connection, date, Path, scan(), ScanResult, _window_end(), build_lake(), days() (+4 more)

### Community 145 - "ingest_corporate_actions"
Cohesion: 0.20
Nodes (10): CorpActionIngestResult, ingest_corporate_actions(), date, Path, Raised AFTER every row has been stored, naming every subject that matched…, Fetch corporate actions, parse subjects, and upsert into corporate_actions. One…, UnparsedCorporateActionsError, Regression, found on real data: the ingest used to raise on the FIRST unparsed… (+2 more)

### Community 147 - "deps.py"
Cohesion: 0.23
Nodes (12): ApiContext, get_conn(), get_ctx(), Connection, Request, Dependencies shared by every router: the request context, a per-request SQLite…, require_token(), _bearer (+4 more)

### Community 151 - "test_health.py"
Cohesion: 0.29
Nodes (6): stk_store_parquet_layout, stk_store_parquet_schema, stk_store_parquet_writer, db(), fixture, Unit tests for the individual `stk doctor` checks. Each check is exercised…

### Community 154 - "check_security_lifecycle"
Cohesion: 0.38
Nodes (3): check_security_lifecycle(), Suspended/delisted counts (info), and a stale master (problem): with no recent…, TestSecurityLifecycle

### Community 155 - "NseSecBhavdataProvider"
Cohesion: 0.15
Nodes (10): NseSecBhavdataProvider, PriceProvider backed by NSE's sec_bhavdata_full daily file., _csv_response(), Response, Defence-in-depth: even though NSE's archive host has not been observed doing…, Real network smoke test -- excluded from the default run. Run explicitly with…, TestCapabilities, TestFetchEod (+2 more)

### Community 156 - "entry_mask"
Cohesion: 0.30
Nodes (5): entry_mask(), frame(), DataFrame, No delivery data / no benchmark / no ROCE must read as 'condition false'., TestInterpreter

### Community 160 - "ingest/backfill.py"
Cohesion: 0.08
Nodes (31): `stk backfill` -- historical price backfill., ProviderError, Exception, Base class for all application-raised errors., Base class for provider-adapter failures., StkError, backfill_bse_prices(), backfill_nse_prices() (+23 more)

### Community 161 - "track_picks"
Cohesion: 0.24
Nodes (11): _bars_by_symbol(), Connection, date, Path, round_trip_cost_pct(), track_picks(), TrackResult, _write() (+3 more)

### Community 162 - "playground/fills.py"
Cohesion: 0.08
Nodes (55): delete_order(), journal(), new_order(), Conn, OrderStatus, _key(), Connection, Decimal (+47 more)

### Community 163 - "make_portfolio"
Cohesion: 0.22
Nodes (5): make_portfolio(), parametrize, TestAuth, TestOrders, TestPortfolios

### Community 165 - "test_costs_compute.py"
Cohesion: 0.19
Nodes (9): BrokerageRule, How brokerage is charged for one product. model: flat_per_order -> ``flat``…, hypothesis, Decimal, given, compute_costs against hand-worked examples. A wrong rate or a mis-scoped GST…, Changing STT or stamp duty must not change GST -- the one-line bug the config…, _synthetic() (+1 more)

### Community 167 - "is_liquid"
Cohesion: 0.13
Nodes (15): LiquidityConfig, Loader for config/universe.yaml -- liquidity thresholds and the…, is_liquid(), is_tradeable_intraday(), LiquidityMetrics, LiquidityThresholds, Liquidity/tradeable-universe eligibility rules. Pure functions: no I/O, no…, Whether a security passes the liquidity filter. Returns (passed, reason) --… (+7 more)

### Community 169 - "test_master_ingest.py"
Cohesion: 0.19
Nodes (15): _bse_row(), db(), _isin(), _mock_bse(), _mock_nse(), _nse_row(), fixture, Integration tests for ingest_security_master's ISIN-keyed merge. Mocks both… (+7 more)

### Community 170 - "TestCli"
Cohesion: 0.29
Nodes (3): fixture, `stk backup ...` end to end, pointed at a temp data root through the env…, TestCli

### Community 171 - "fundamentals_xbrl.py"
Cohesion: 0.15
Nodes (17): Any, ingest_xbrl_documents(), _pending(), _process(), Path, Fetch, persist, parse and store the XBRL behind each filing-metadata snapshot.…, Write a parsed filing's line items (replacing any earlier parse of the same…, Re-run the parser over documents ALREADY on disk (no network) for filings whose… (+9 more)

### Community 172 - "latest_backup_age_days"
Cohesion: 0.40
Nodes (4): latest_backup_age_days(), date, Days since the newest backup, or None if there is none., TestAge

### Community 173 - "ticker_for"
Cohesion: 0.47
Nodes (3): Yahoo ticker for an Indian listing., ticker_for(), TestTickerMapping

### Community 174 - "app.py"
Cohesion: 0.12
Nodes (31): alias, bars(), brief(), briefs(), health(), picks(), proposal_approve(), proposal_dismiss() (+23 more)

### Community 175 - "schema.d.ts"
Cohesion: 0.33
Nodes (5): components, $defs, operations, paths, webhooks

### Community 176 - "generate_windows"
Cohesion: 0.26
Nodes (7): _add_months(), generate_windows(), date, Walk-forward window generation -- pure. Tune on a training window, evaluate on…, Rolling windows over [start, end]. A window is kept only if its whole test span…, Window, TestWindows

### Community 177 - "Current status (update this section as phases complete)"
Cohesion: 0.06
Nodes (45): AppSettings, adjustments(), calendar(), corpactions(), daily(), fundamentals(), fundamentals_sweep(), indices() (+37 more)

### Community 179 - "lifecycle_status"
Cohesion: 0.50
Nodes (3): lifecycle_status(), A security's status from how many consecutive master snapshots it has been…, TestLifecycleRule

### Community 182 - ".fetch_document"
Cohesion: 0.40
Nodes (3): Download one filing's XBRL document from nsearchives (a browser UA suffices).…, RawArtifact, date

### Community 186 - "get_settings"
Cohesion: 0.11
Nodes (20): prices(), command, Backfill daily prices over a date range for one exchange. NSE source (legacy vs…, migrate_cmd(), command, Apply all pending SQLite migrations., list_cmd(), _init() (+12 more)

### Community 189 - "transaction"
Cohesion: 0.17
Nodes (18): Connection, Explicit transaction context manager (conn is opened in autocommit mode).…, transaction(), approve(), create_proposal(), _decide(), dismiss(), get_proposal() (+10 more)

### Community 190 - "parse_sec_bhavdata_full"
Cohesion: 0.24
Nodes (5): parse_sec_bhavdata_full(), Parse NSE's sec_bhavdata_full_{DDMMYYYY}.csv into canonical bars. This file…, The real NSE file has a leading space on every header/value after the first…, This is the critical rule: '-' means unreported, not zero., TestParseSecBhavdataFull

### Community 192 - "0006_playground.sql"
Cohesion: 0.08
Nodes (38): backtest_equity, backtest_metrics, backtest_runs, backtest_trades, backtest_windows, ix_backtest_runs_strategy, ix_backtest_trades_run, ix_status_events_strategy (+30 more)

### Community 194 - "test_yfinance_provider.py"
Cohesion: 0.22
Nodes (8): enabled(), provider(), fixture, Unit tests for the yfinance fallback provider. Almost every test here is about…, Turn the feature flag on for tests that need the provider built. get_settings()…, The flag the UI's `approx` badge and every backtest honesty check ultimately…, TestCapabilities, unittest_mock

### Community 196 - "TestFetchHistory"
Cohesion: 0.29
Nodes (5): _frame(), DataFrame, Yahoo reports no rupee turnover. close*volume is derived and must never be…, An empty result means a wrong ticker, a delisted name, or a rate limit -- never…, TestFetchHistory

### Community 202 - "run_backtest"
Cohesion: 0.19
Nodes (13): _align_benchmark(), EngineConfig, DataFrame, RatesFn, Benchmark closes aligned to ``dates`` (forward-filled), or (None, True) if…, run_backtest(), _outcome(), DataFrame (+5 more)

### Community 204 - "get_rate_schedule"
Cohesion: 0.29
Nodes (7): get_rate_schedule(), Path, Return the process-wide RateSchedule singleton, loading config/costs.yaml on…, fixture, schedule(), fixture, schedule()

### Community 213 - "get_fundamentals_provider"
Cohesion: 0.40
Nodes (4): get_fundamentals_provider(), Construct a FundamentalsProvider by its config name (see providers.fundamentals…, FundamentalsProvider, TestGetFundamentalsProvider

### Community 214 - "nse/corpactions.py"
Cohesion: 0.11
Nodes (17): FilingRef, date, A corporate-action row with the subject text UNPARSED. Parsing free-text…, A pointer to a fundamentals filing that exists, before fetching it., Per-symbol history. Optional -- full-market-file providers (bhavcopy-based)…, Corporate actions since ``since`` (or all available if None)., What filings exist -- cheap, used to decide what to fetch., RawCorporateAction (+9 more)

### Community 217 - "conftest.py"
Cohesion: 0.36
Nodes (7): _isolated_config_dir(), fixture, Path, Shared pytest fixtures., Point STK_CONFIG_DIR at the real repo config/ for every test. Tests run from…, tmp_db_path(), tmp_parquet_root()

### Community 220 - "TestLiveEndpoint"
Cohesion: 0.33
Nodes (3): Documented shape checks. Run deliberately: `pytest -m live`., The finding that justified using this endpoint for the whole backfill range…, TestLiveEndpoint

### Community 221 - "backtest/engine.py"
Cohesion: 0.12
Nodes (20): _d(), _Position, date, Decimal, Row, Daily event-loop backtester. Sequence for each trading date d (the order is the…, Mutable state and steps of one backtest run., Which exit (if any) this bar triggers, and at what pre-slippage price. (+12 more)

### Community 223 - "world"
Cohesion: 0.40
Nodes (5): load_backtest_config(), fixture, Synthetic stocks trade ~Rs 1 lakh/day, far below the real liquidity floor;…, A migrated db, a 3-stock lake, one live strategy with picks (some closed), one…, world()

### Community 224 - "validate"
Cohesion: 0.18
Nodes (14): Argument, _load_spec_file(), command, help, Option, Path, StrategySpec, Validate a strategy spec file (schema + semantic checks). Exits non-zero on any… (+6 more)

### Community 234 - "Phase 1 — data pipeline + store"
Cohesion: 0.50
Nodes (4): Cost config scaffold, Ingest pipeline, Parquet layout, Phase 1 — data pipeline + store

### Community 237 - "check_adjusted_freshness"
Cohesion: 0.38
Nodes (4): check_adjusted_freshness(), Whether bars_daily_adjusted has kept up with known ex-dates. A corporate action…, Dividends carry no price factor by this project's convention, so they cannot…, TestAdjustedFreshness

### Community 238 - ".test_without_the_exclusion_the_funds_would_be_picked"
Cohesion: 0.50
Nodes (3): load_backtest_config(), The mutation check: proves the test above is really about the exclusion., TestFundsAreNeverPicked

### Community 239 - "test_costs.py"
Cohesion: 0.09
Nodes (11): Tests for the dated cost-rate schedule (config/costs.yaml + RateSchedule).…, DP charge: flat, per-scrip, per-day, sell leg only -- dominates cost on small…, NSE IPFT dropped from Rs 10/crore to Rs 0.01/crore on 2026-03-01., Stamp duty became uniform nationwide on 2020-07-01., STT: delivery both legs; intraday sell-leg only., GST must apply to brokerage/exchange_txn/sebi fee/IPFT and NOT to STT or stamp…, TestDpCharge, TestGstScope (+3 more)

### Community 243 - "test_nse_udiff_provider.py"
Cohesion: 0.31
Nodes (5): provider(), fixture, Unit tests for the NSE UDiFF provider. The behaviour that matters most here is…, TestParse, _zip_artifact()

### Community 250 - "parametrize"
Cohesion: 0.20
Nodes (5): Remove a Markdown code fence around a JSON reply, if the model added one., strip_fences(), parametrize, TestFences, TestScripts

## Knowledge Gaps
- **143 isolated node(s):** `What this is`, `Repo layout`, `graphify`, `OrderType`, `components` (+138 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1433 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **107 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Current status (update this section as phases complete)` connect `Current status (update this section as phases complete)` to `assert_bars_sane`, `get_price_provider`, `upsert_partition`, `ingest_security_master`, `ConfigError`, `connect`, `build_factor_rows`, `ingest_corporate_actions`, `domain/costs.py`, `time.py`, `ingest/corpactions.py`, `Stocks.tsx`, `is_liquid`, `json`, `lifecycle_status`, `NotSupportedError`, `PointInTimeView`, `compute_costs`, `today_ist`, `mock`, `transaction`, `base.py`, `nse/corpactions.py`, `nse/fundamentals.py`, `client.py`?**
  _High betweenness centrality (0.138) - this node is a cross-community bridge._
- **Why does `tradingViewUrl()` connect `Stocks.tsx` to `Current status (update this section as phases complete)`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Why does `connect()` connect `connect` to `test_ai_lab.py`, `rebuild_adjusted_bars`, `commands/playground.py`, `ingest_corporate_actions`, `deps.py`, `ingest_calendar_year`, `_write`, `ingest/corpactions.py`, `ingest/backfill.py`, `make_portfolio`, `registry.py`, `flat`, `ingest_indices_for_date`, `transaction`, `backtest/runs.py`, `api.py`, `_mock`, `datetime`, `test_backtest_engine.py`, `get_strategy`, `compute_liquidity_for_date`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `migrate()` (e.g. with `.test_no_picks_at_all_is_an_empty_list()` and `.test_empty_lake_is_a_warning_not_a_crash()`) actually correct?**
  _`migrate()` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `What this is`, `Repo layout`, `graphify` to the rest of the system?**
  _143 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `assert_bars_sane` be split into smaller, more focused modules?**
  _Cohesion score 0.06554019457245264 - nodes in this community are weakly interconnected._
- **Should `get_price_provider` be split into smaller, more focused modules?**
  _Cohesion score 0.05697278911564626 - nodes in this community are weakly interconnected._