# Graph Report - stockAnalyser  (2026-09-19)

## Corpus Check
- 151 files · ~85,944 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 22 file(s) not represented in the graph (top: (none) 11, .csv 7, .CSV 2)

## Summary
- 2008 nodes · 4987 edges · 138 communities (99 shown, 39 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 368 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `32bfb35d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- doctor.py
- assert_bars_sane
- backfill_nse_prices
- liquidity.py
- validate_json_response
- time.py
- _make_bars
- Project brief for Claude Code — Indian stock suggester + virtual playground
- RawArtifact
- connect
- build_factor_rows
- duck.py
- CalendarProvider
- rebuild_adjusted_bars
- datetime
- TestFetchHistory
- parse_ind_close_all
- registry.py
- job_run
- compute_metrics
- compute_costs
- daily.py
- test_migrations.py
- _mock
- ingest_calendar_year
- config/costs.py
- _write
- test_costs.py
- _ingest_prices_for_date
- domain/costs.py
- 0001_init.sql
- ingest/corpactions.py
- ingest.py
- BseUdiffProvider
- NseSecBhavdataProvider
- test_health.py
- NseLegacyBhavcopyProvider
- ingest_security_master
- backfill_bse_prices
- ingest_calendar_from_bars
- BseLegacyBhavcopyProvider
- loader.py
- data.py
- adjustments.py
- run_backtest
- main.py
- settings.py
- test_master_ingest.py
- AppSettings
- ingest/calendar.py
- parse_legacy_bhavcopy
- NSE
- get_rate_schedule
- ingest_indices_for_date
- CLAUDE.md
- PointInTimeView
- TestLiveEndpoint
- PathsConfig
- backtest/engine.py
- ingest_corporate_actions
- TestUrlAndCapabilities
- runs.py
- parse_sec_bhavdata_full
- Current status (update this section as phases complete)
- TestParse
- Indian stock suggester + virtual playground — build plan
- yfinance/__init__.py
- queries/__init__.py
- stk
- upsert_partition
- circuit_lock
- bse/archives.py
- NseIndicesProvider
- normalise.py
- IndexBar
- Side
- _Run
- conftest.py
- flat
- test_backtest_engine.py
- canonical_index_code
- NotSupportedError
- Oracle Cloud Always Free VM — setup notes
- TestDimensions
- ticker_for
- Data sources — verified endpoints
- stockAnalyser
- run_walk_forward
- Phase 1 — data pipeline + store
- NseCorporateActionsProvider
- build_client
- get_nse_price_provider_for_date
- TestLiveEndpoint
- enabled
- TestLiveEndpoint
- TestCapabilities
- env
- MarketData
- ConfigError
- get_price_provider
- generate_windows
- check_job_runs
- parse_udiff
- 0002_backtest.sql
- get_bse_price_provider_for_date
- history_probe.py
- commands/backtest.py
- TestAdjustedFreshness
- _bars_to_table
- .parse_holidays
- TestRegistryWiring
- _identity_map
- TestUnparsedCorporateActions
- backtest/__init__.py
- data_dirs
- data_dirs
- data_dirs
- data_dirs
- env

## God Nodes (most connected - your core abstractions)
1. `_mock()` - 81 edges
2. `connect()` - 80 edges
3. `RawArtifact` - 51 edges
4. `migrate()` - 48 edges
5. `CanonicalBar` - 37 edges
6. `NotSupportedError` - 36 edges
7. `ContentValidationError` - 35 edges
8. `DataNotPublished` - 34 edges
9. `ConfigError` - 31 edges
10. `job_run()` - 31 edges

## Surprising Connections (you probably didn't know these)
- `Ground rules (from the brief, do not relitigate without asking)` --references--> `corpactions()`  [INFERRED]
  CLAUDE.md → backend/src/stk/cli/commands/ingest.py
- `Verification` --references--> `ContentValidationError`  [INFERRED]
  docs/BUILD_PLAN.md → backend/src/stk/core/errors.py
- `Daily EOD prices (primary source): `sec_bhavdata_full`` --references--> `NseSecBhavdataProvider`  [INFERRED]
  docs/data-sources.md → backend/src/stk/providers/nse/prices.py
- `Current status (update this section as phases complete)` --references--> `Strategy`  [INFERRED]
  CLAUDE.md → backend/src/stk/backtest/engine.py
- `Current status (update this section as phases complete)` --references--> `LookAheadError`  [INFERRED]
  CLAUDE.md → backend/src/stk/backtest/view.py

## Import Cycles
- None detected.

## Communities (138 total, 39 thin omitted)

### Community 0 - "doctor.py"
Cohesion: 0.12
Nodes (27): _check_endpoints(), doctor(), _previous_weekday(), command, date, `stk doctor` -- ingest health check. Thin by design: every actual check lives…, Step back to the nearest weekday. Holidays are not filtered -- a holiday simply…, Report on ingest health. Exits non-zero if anything looks wrong. (+19 more)

### Community 1 - "assert_bars_sane"
Cohesion: 0.16
Nodes (11): assert_bars_match_requested_date(), assert_bars_sane(), Cheap, fast invariant checks over a batch of parsed bars. Deliberately does NOT…, Assert every parsed bar's date matches the date we actually requested from the…, _bar(), Regression tests for a real bug found via live backfill testing: NSE's own…, Even if only some rows are wrong, the whole file must be rejected., Regression test: a real live-ingest failure. Thin government securities… (+3 more)

### Community 2 - "backfill_nse_prices"
Cohesion: 0.28
Nodes (9): backfill_nse_prices(), Ingest every weekday of NSE prices in [start, end] (inclusive), sequentially.…, _fixture_for_date(), _mock_date(), date, 2026-09-19/20 is a Sat/Sun -- must not even attempt a request., The core resilience property: one bad date must not abort the whole range --…, Real fixture content, with every DATE1 value rewritten to `d`. (+1 more)

### Community 3 - "liquidity.py"
Cohesion: 0.06
Nodes (41): LiquidityConfig, BaseModel, Loader for config/universe.yaml -- liquidity thresholds and the…, UniverseConfig, is_liquid(), is_tradeable_intraday(), LiquidityMetrics, LiquidityThresholds (+33 more)

### Community 4 - "validate_json_response"
Cohesion: 0.12
Nodes (15): Response, Validate a response that is expected to be a plain CSV file.…, Validate a response that is expected to be JSON., validate_csv_response(), validate_json_response(), Response, The exact BSE failure: 200 OK, HTML body -- must raise, not parse., The trap must not be swallowed anywhere -- calling code should never see a… (+7 more)

### Community 5 - "time.py"
Cohesion: 0.05
Nodes (37): format_ddmmyy_compact(), is_market_hours(), is_weekend(), now_ist(), parse_ddmmmyyyy(), parse_ddmmyyyy_compact(), previous_calendar_day(), date (+29 more)

### Community 6 - "_make_bars"
Cohesion: 0.11
Nodes (18): The manifest for one partition, or None if none was written., read_manifest(), _make_bars(), partition_path(), date, fixture, Table, A stronger idempotency check: not just the same row count, but the same file… (+10 more)

### Community 7 - "Project brief for Claude Code — Indian stock suggester + virtual playground"
Cohesion: 0.14
Nodes (14): 10. Screens (designs come from Claude Design), 11. Build phases (do them in order; stop and check in with me after each), 12. How to work with me, 1. What the app does, 2. Hard constraints, 3. Stack, 4. Data layer, 5. Strategies — four horizons (+6 more)

### Community 8 - "RawArtifact"
Cohesion: 0.06
Nodes (39): ContentValidationError, A response passed HTTP status but failed content-type/magic-byte checks. This…, format_ddmmyyyy_compact(), format_yyyymmdd(), Format a date as 'DDMMYYYY' for bhavcopy filename construction., Format a date as 'YYYYMMDD' for UDiFF filename construction., CanonicalBar, PriceProvider (+31 more)

### Community 9 - "connect"
Cohesion: 0.15
Nodes (15): connect(), _discover_migrations(), migrate(), Path, Open a connection with the app's standard pragmas applied., Return (sequence_number, name, path) for every migrations/*.sql file, sorted., Apply all pending migrations in order. Returns the names applied., conn() (+7 more)

### Community 10 - "build_factor_rows"
Cohesion: 0.12
Nodes (22): ActionFactor, build_factor_rows(), factors_for_bar(), date, Compose per-action factors into a cumulative back-adjustment timeline. For each…, The cumulative factors applying to one bar, given that symbol's timeline (any…, One price/volume-affecting action, already deduped and resolved., _action() (+14 more)

### Community 11 - "duck.py"
Cohesion: 0.10
Nodes (27): attach_dimensions(), _attach_via_arrow(), connect(), DimensionMode, DuckSession, _load_named_queries(), named_query(), Any (+19 more)

### Community 12 - "CalendarProvider"
Cohesion: 0.16
Nodes (11): ABC, CalendarProvider, CorporateActionsProvider, date, Source of the trading-holiday calendar. Fetch and parse are separate, exactly…, The raw, unparsed holiday response for a calendar year., Holiday rows for one segment. Callers must intersect with weekdays themselves…, Convenience composition for callers that do not need the raw bytes (interactive… (+3 more)

### Community 13 - "rebuild_adjusted_bars"
Cohesion: 0.14
Nodes (21): Path, Rebuild adjustment_factors and bars_daily_adjusted for one exchange. Network-…, rebuild_adjusted_bars wrapped in a job_run scope. Kept separate so the rebuild…, rebuild_adjusted_bars(), rebuild_adjusted_bars_job(), _adjusted(), _insert_action(), date (+13 more)

### Community 14 - "datetime"
Cohesion: 0.06
Nodes (49): `stk backfill` -- historical price backfill., Exception hierarchy for the ingest/provider stack. The rule this hierarchy…, Shared HTTP client factory and response validation. This module is the single…, Post-ingest sanity assertions. Run after every parse, before a partition write…, Historical price backfill. Reuses the same per-exchange ingest function…, JobRun bookkeeping: a context manager that records start/success/ skip/failure…, HolidayRecord, Provider adapter interfaces. Every external data source (NSE, BSE, yfinance,… (+41 more)

### Community 15 - "TestFetchHistory"
Cohesion: 0.29
Nodes (5): _frame(), DataFrame, Yahoo reports no rupee turnover. close*volume is derived and must never be…, An empty result means a wrong ticker, a delisted name, or a rate limit -- never…, TestFetchHistory

### Community 16 - "parse_ind_close_all"
Cohesion: 0.17
Nodes (8): parse_ind_close_all(), Parse NSE's ind_close_all_DDMMYYYY.csv into canonical index bars. Two…, 18775.3 crore = 1,87,753,000,000 rupees. The word "crore" must never survive…, NSE's file carries rows like "Nifty50 Dividend Points" that have a real close…, A row with no closing value is not a price bar at all., TestMalformedInput, TestNullHandling, TestParseRealFixture

### Community 17 - "registry.py"
Cohesion: 0.07
Nodes (32): ProviderUnavailable, Transport-level failure: timeout, connection refused, DNS, 5xx., _fetch_all_records(), Security-master ingest: ISIN-keyed merge of NSE + BSE listings into…, Fetch every exchange's master snapshot, tolerating one exchange's fetch failing…, MasterRecord, PriceBand, One row of a security-master snapshot (NSE EQUITY_L.csv / BSE ListofScripData). (+24 more)

### Community 18 - "job_run"
Cohesion: 0.10
Nodes (18): job_run(), JobRunHandle, JobSkipped, _next_attempt(), Connection, date, Exception, Raise inside a job_run() block to record status='skipped_holiday' and exit the… (+10 more)

### Community 19 - "compute_metrics"
Cohesion: 0.10
Nodes (18): cagr(), compute_metrics(), max_drawdown(), date, Backtest performance metrics -- pure. Statistics, not money: inputs are…, One closed round trip, net of all costs., Worst peak-to-trough decline as a NEGATIVE fraction (0.0 if never below a peak)., Annualised Sharpe from daily equity. 0.0 when there is no variance to divide by. (+10 more)

### Community 20 - "compute_costs"
Cohesion: 0.14
Nodes (15): compute_costs(), Itemised charges for one order leg of ``turnover`` rupees. Excludes the DP…, date, Decimal, given, rates(), compute_costs against hand-worked examples. A wrong rate or a mis-scoped GST…, Changing STT or stamp duty must not change GST -- the one-line bug the config… (+7 more)

### Community 21 - "daily.py"
Cohesion: 0.13
Nodes (18): _enrich_identity(), Nightly ingest orchestration. NSE and BSE prices both go through…, Fill security_id/isin on bars that did not carry them. Never OVERWRITES a value…, Index (benchmark) ingest. Same shape as ingest.daily's price path -- fetch,…, manifest_path(), Parquet path conventions. Partitioned by exchange then year:…, Where the row-count + sha256 sidecar for one partition lives. ``exchange`` is…, Canonical Arrow schema for daily bars. NSE UDiFF, BSE UDiFF and… (+10 more)

### Community 23 - "_mock"
Cohesion: 0.19
Nodes (10): ingest_nse_prices_for_date(), Ingest one day of NSE prices end-to-end: fetch, validate, persist raw, parse,…, bars_daily_partition(), Tri-state, not boolean: no calendar row means UNKNOWN, and unknown must be…, The full-stack version of the parquet writer's idempotency property: running…, Regression test: a real live backfill run caught upsert_partition's cumulative…, Freshly-ingested bars get security_id/isin filled in from the securities master…, TestIdentityEnrichment (+2 more)

### Community 24 - "ingest_calendar_year"
Cohesion: 0.17
Nodes (14): ingest_calendar_year(), Populate one calendar year for one exchange from NSE's holiday master. Writes a…, _holiday_payload(), _mock_holidays(), A Sunday holiday is not a trading-calendar gap. NSE lists it; the calendar must…, BSE has no separate feed wired up. Using NSE's calendar is a reasonable…, The precedence rule. NSE says 26-Jan-2026 was a holiday; the lake has no bars…, The reverse direction IS allowed -- learning NSE's real answer for a date we… (+6 more)

### Community 25 - "config/costs.py"
Cohesion: 0.16
Nodes (16): _DatedRate, _dec(), BaseModel, date, Decimal, RateSchedule, product(), Dated cost-rate schedule loader. Loads config/costs.yaml -- a history of… (+8 more)

### Community 26 - "_write"
Cohesion: 0.14
Nodes (9): _bars(), date, Path, Table, exchange/year come from the directory names, not the file -- the liquidity and…, A fresh checkout has no bars_daily_adjusted. Querying it must return zero rows…, TestNamedQueries, TestViewRegistration (+1 more)

### Community 27 - "test_costs.py"
Cohesion: 0.07
Nodes (15): fixture, Tests for the dated cost-rate schedule (config/costs.yaml + RateSchedule).…, DP charge: flat, per-scrip, per-day, sell leg only -- dominates cost on small…, NSE exchange transaction charge changed 2024-10-01 and again 2026-03-01., NSE IPFT dropped from Rs 10/crore to Rs 0.01/crore on 2026-03-01., Stamp duty became uniform nationwide on 2020-07-01., STT: delivery both legs; intraday sell-leg only., GST must apply to brokerage/exchange_txn/sebi fee/IPFT and NOT to STT or stamp… (+7 more)

### Community 28 - "_ingest_prices_for_date"
Cohesion: 0.13
Nodes (18): daily(), date, Run one exchange's ingest, print its outcome, and return whether it succeeded…, Ingest one day of NSE and BSE prices, then rebuild adjusted bars. Both…, _run_one(), ingest_bse_prices_for_date(), _ingest_prices_for_date(), IngestResult (+10 more)

### Community 29 - "domain/costs.py"
Cohesion: 0.09
Nodes (23): command, quote(), `stk costs` -- inspect the transaction-cost model., Itemise the charges on one order leg, using the rates in force on a date. Rates…, bps(), format_inr(), Decimal, Decimal-safe money arithmetic and Indian-style (lakh/crore) formatting. Every… (+15 more)

### Community 30 - "0001_init.sql"
Cohesion: 0.17
Nodes (20): corporate_actions, fundamentals_snapshots, ix_ca_exdate, ix_ca_parse_status, ix_ca_security_ex, ix_fund_provider, ix_fund_sec_period, ix_job_lookup (+12 more)

### Community 31 - "ingest/corpactions.py"
Cohesion: 0.09
Nodes (39): ActionType, _ClauseResult, _parse_bonus(), _parse_clause(), _parse_decimal(), _parse_dividend(), _parse_face_value_split(), _parse_rights() (+31 more)

### Community 32 - "ingest.py"
Cohesion: 0.05
Nodes (58): adjustments(), calendar(), corpactions(), fundamentals(), indices(), liquidity(), master(), command (+50 more)

### Community 33 - "BseUdiffProvider"
Cohesion: 0.20
Nodes (9): BseUdiffProvider, PriceProvider backed by BSE's UDiFF daily bhavcopy., _csv_response(), Response, The confirmed-live BSE trap: a weekend, holiday, or invalid date returns HTTP…, Not text/html, but also doesn't look like the expected CSV -- must still be…, TestCapabilities, TestFetchEod (+1 more)

### Community 34 - "NseSecBhavdataProvider"
Cohesion: 0.16
Nodes (11): NseSecBhavdataProvider, PriceProvider backed by NSE's sec_bhavdata_full daily file., _csv_response(), live, Response, Defence-in-depth: even though NSE's archive host has not been observed doing…, Real network smoke test -- excluded from the default run. Run explicitly with…, TestCapabilities (+3 more)

### Community 35 - "test_health.py"
Cohesion: 0.19
Nodes (14): check_calendar_coverage(), Trading days the calendar knows about that have no bars. Bounded to the…, _add_calendar(), date, Path, Unit tests for the individual `stk doctor` checks. Each check is exercised…, Trading days before the first ingested bar are history we have not backfilled…, A fresh install must not report every symbol as stale. (+6 more)

### Community 36 - "NseLegacyBhavcopyProvider"
Cohesion: 0.21
Nodes (8): NseLegacyBhavcopyProvider, PriceProvider backed by NSE's legacy per-date cm*bhav.csv.zip archive., live, TestCapabilities, TestFetchEod, TestLiveEndpoint, TestParseEod, _zip_bytes()

### Community 37 - "ingest_security_master"
Cohesion: 0.25
Nodes (8): ingest_security_master(), MasterIngestResult, Connection, Path, Returns True if this upsert closed out a rename (a different symbol was…, Fetch and merge the NSE + BSE security masters into securities/…, _upsert_listing_and_detect_rename(), _upsert_security()

### Community 38 - "backfill_bse_prices"
Cohesion: 0.13
Nodes (15): backfill_bse_prices(), _backfill_prices(), BackfillSummary, date, Path, Ingest every weekday of BSE prices in [start, end] (inclusive). Identical shape…, Shared date-range iteration used by both backfill_nse_prices and…, _bse_fixture_for_date() (+7 more)

### Community 39 - "ingest_calendar_from_bars"
Cohesion: 0.20
Nodes (8): CalendarIngestResult, ingest_calendar_from_bars(), Path, Derive calendar rows from the dates actually present in bars_daily. Covers only…, date, Path, TestIngestCalendarFromBars, _write_bars()

### Community 40 - "BseLegacyBhavcopyProvider"
Cohesion: 0.21
Nodes (8): BseLegacyBhavcopyProvider, PriceProvider backed by BSE's legacy per-date EQ*.CSV.ZIP archive., live, TestCapabilities, TestFetchEod, TestLiveEndpoint, TestParseEod, _zip_bytes()

### Community 41 - "loader.py"
Cohesion: 0.22
Nodes (13): _deep_merge(), find_config_dir(), load_named_yaml(), load_yaml_config(), Any, Path, YAML config loading and layering. Precedence, highest wins: 1. Process env /…, Recursively merge ``overlay`` onto ``base``. ``overlay`` wins on conflicts. (+5 more)

### Community 42 - "data.py"
Cohesion: 0.12
Nodes (18): load_benchmark(), load_market_data(), prepare_bars(), DataFrame, date, Path, Load market data for a backtest, and prepare it point-in-time. Everything a…, Add prev_close and adv_turnover (both past-only) to a raw adjusted-bars frame. (+10 more)

### Community 43 - "adjustments.py"
Cohesion: 0.16
Nodes (15): _adjust_bar(), AdjustmentResult, _factor_table(), FactorRow, load_actions(), _LoadedActions, BaseModel, Connection (+7 more)

### Community 44 - "run_backtest"
Cohesion: 0.17
Nodes (13): _align_benchmark(), DataFrame, Benchmark closes aligned to ``dates`` (forward-filled), or (None, True) if…, run_backtest(), config(), days_of(), make_data(), date (+5 more)

### Community 45 - "main.py"
Cohesion: 0.13
Nodes (14): migrate_cmd(), command, `stk db` -- database management commands., Apply all pending SQLite migrations., _init(), `stk` -- the project's single CLI entry point. Subcommands are grouped by…, configure_logging(), get_logger() (+6 more)

### Community 46 - "settings.py"
Cohesion: 0.20
Nodes (12): AppMeta, HttpConfig, HttpEndpointConfig, IngestConfig, ProvidersConfig, BaseModel, Typed application settings. Loads config/defaults.yaml + config/env/{env}.yaml…, YFinanceHttpConfig (+4 more)

### Community 47 - "test_master_ingest.py"
Cohesion: 0.44
Nodes (6): _bse_row(), _mock_bse(), _mock_nse(), _nse_row(), Integration tests for ingest_security_master's ISIN-keyed merge. Mocks both…, TestIngestSecurityMaster

### Community 48 - "AppSettings"
Cohesion: 0.27
Nodes (7): AppSettings, Any, pydantic-settings source that loads config/defaults.yaml + env overlay., Root settings object. Construct via ``get_settings()``., _YamlSettingsSource, BaseSettings, PydanticBaseSettingsSource

### Community 49 - "ingest/calendar.py"
Cohesion: 0.13
Nodes (20): is_trading_day(), Connection, date, Trading-calendar ingest: populating `trading_calendar` from NSE, and from what…, Whether the calendar knows this date traded. Returns None for "the calendar has…, Known trading days in [start, end], or None if the calendar does not fully…, Insert or improve one calendar row, respecting source precedence., trading_days_between() (+12 more)

### Community 50 - "parse_legacy_bhavcopy"
Cohesion: 0.29
Nodes (5): parse_legacy_bhavcopy(), Parse NSE's legacy cm{DDMONYYYY}bhav.csv format (2010 through ~2019-10-01,…, The real 2010 file uses '4-JAN-2010', not '04-JAN-2010'., This format predates delivery reporting -- delivery fields must be None, not…, TestParseLegacyBhavcopy

### Community 51 - "NSE"
Cohesion: 0.20
Nodes (10): assert_index_bars_match_requested_date(), date, Same guard as assert_bars_match_requested_date, for index bars. ADR 0003…, Corporate actions, Daily EOD prices (primary source): `sec_bhavdata_full`, Fundamentals (official, no XBRL parsing needed), Index closes (benchmark) — `ind_close_all`, NSE (+2 more)

### Community 52 - "get_rate_schedule"
Cohesion: 0.22
Nodes (8): make_rates_fn(), RatesFn, Rates in force on each fill's own date, memoised per (exchange, date)., get_rate_schedule(), Path, Return the process-wide RateSchedule singleton, loading config/costs.yaml on…, fixture, schedule()

### Community 53 - "ingest_indices_for_date"
Cohesion: 0.20
Nodes (9): IndicesIngestResult, ingest_indices_for_date(), date, Path, Ingest one day of NSE index closes end-to-end. Idempotent., indices_daily_partition(), ADR 0003's mislabeled-content trap, applied to the index archive: writing this…, TestIngestIndicesForDate (+1 more)

### Community 54 - "CLAUDE.md"
Cohesion: 0.29
Nodes (5): graphify, Ground rules (from the brief, do not relitigate without asking), Repo layout, What this is, Working here

### Community 55 - "PointInTimeView"
Cohesion: 0.14
Nodes (15): An intent to buy at the next open., Signal, Strategy, PointInTimeView, DataFrame, Every bar dated <= ``decision_date`` (all symbols)., Fundamentals rows whose ``available_at`` <= ``decision_date`` (else None if no…, Read-only view of ``MarketData`` as it stood at the close of ``decision_date``. (+7 more)

### Community 56 - "TestLiveEndpoint"
Cohesion: 0.29
Nodes (4): live, Documented shape checks. Run deliberately: `pytest -m live`., The finding that justified using this endpoint for the whole backfill range…, TestLiveEndpoint

### Community 58 - "backtest/engine.py"
Cohesion: 0.15
Nodes (18): EngineConfig, Daily event-loop backtester. Sequence for each trading date d (the order is the…, Trade, build_engine_config(), Turn config files into the engine's inputs., BacktestConfig, load_backtest_config(), BaseModel (+10 more)

### Community 59 - "ingest_corporate_actions"
Cohesion: 0.27
Nodes (7): CorpActionIngestResult, ingest_corporate_actions(), date, Path, Fetch corporate actions, parse subjects, and upsert into corporate_actions. One…, _row(), TestIngestCorporateActions

### Community 61 - "runs.py"
Cohesion: 0.19
Nodes (21): BacktestResult, _begin(), _finish(), _insert_trades(), load_run_summary(), _metric_rows(), Any, Connection (+13 more)

### Community 62 - "parse_sec_bhavdata_full"
Cohesion: 0.24
Nodes (5): parse_sec_bhavdata_full(), Parse NSE's sec_bhavdata_full_{DDMMYYYY}.csv into canonical bars. This file…, The real NSE file has a leading space on every header/value after the first…, This is the critical rule: '-' means unreported, not zero., TestParseSecBhavdataFull

### Community 63 - "Current status (update this section as phases complete)"
Cohesion: 0.19
Nodes (10): FundamentalsIngestResult, ingest_fundamentals_for_security(), Connection, Path, Fetch one security's recent filings and upsert into fundamentals_snapshots. One…, _resolve_security_id(), _upsert_snapshot(), Current status (update this section as phases complete) (+2 more)

### Community 65 - "Indian stock suggester + virtual playground — build plan"
Cohesion: 0.15
Nodes (13): Context, Decisions locked this session, Design system (extracted from the handoff), Guiding principles for phases 0–1, Indian stock suggester + virtual playground — build plan, Open items for later phases, Phase 0 — repo, config, VM notes, history spike, Phases 2–8 (outline only) (+5 more)

### Community 84 - "upsert_partition"
Cohesion: 0.16
Nodes (15): adjustment_factors_path(), bars_daily_adjusted_partition(), Path, Path, Schema, Table, Overwrite-by-partition write. Returns the row count of the resulting file.…, Read a partition file, or return an empty table matching ``schema`` if absent. (+7 more)

### Community 85 - "circuit_lock"
Cohesion: 0.17
Nodes (14): BarPrices, can_buy(), can_sell(), circuit_lock(), Lock, Decimal, StrEnum, Fill-price rules -- pure. Two rules matter and both are easy to get subtly… (+6 more)

### Community 86 - "bse/archives.py"
Cohesion: 0.22
Nodes (13): Validate a response that is expected to be a zip file. Checks status, then…, validate_zip_response(), fetch_bse_csv_file(), fetch_bse_zip_file(), _get_and_check_shell(), date, Response, Fetch helper for www.bseindia.com CSV downloads. Verified 2026-09-18 by direct… (+5 more)

### Community 87 - "NseIndicesProvider"
Cohesion: 0.18
Nodes (11): index_archive_url(), NseIndicesProvider, date, Fetches NSE's daily all-index close file., Fetch one date's index file, validated and ready to persist., get_indices_provider(), Construct the index (benchmark) provider by name. Not behind an ABC yet: there…, live (+3 more)

### Community 88 - "normalise.py"
Cohesion: 0.24
Nodes (11): _decimal_or_none(), _int_or_none(), parse_bse_legacy_bhavcopy(), _parse_iso_date(), date, Decimal, Normalisation of raw provider text into CanonicalBar rows. Every source format…, Parse BSE's legacy EQ{DDMMYY}_CSV.ZIP bhavcopy (2010 through 2024-07-05,… (+3 more)

### Community 89 - "IndexBar"
Cohesion: 0.33
Nodes (5): Table, _to_table(), IndexBar, BaseModel, One index's OHLC for one date, canonicalised.

### Community 90 - "Side"
Cohesion: 0.14
Nodes (13): StrEnum, Side, apply_slippage(), cap_quantity(), Decimal, Tiered slippage and the participation cap -- pure. Slippage is a function of…, Basis points of slippage for a name with the given trailing ADV turnover.…, Adverse slippage: buys fill higher, sells fill lower. (+5 more)

### Community 91 - "_Run"
Cohesion: 0.27
Nodes (10): _d(), _Position, Any, date, Decimal, RatesFn, Mutable state and steps of one backtest run., Which exit (if any) this bar triggers, and at what pre-slippage price. (+2 more)

### Community 92 - "conftest.py"
Cohesion: 0.36
Nodes (7): _isolated_config_dir(), fixture, Path, Shared pytest fixtures., Point STK_CONFIG_DIR at the real repo config/ for every test. Tests run from…, tmp_db_path(), tmp_parquet_root()

### Community 93 - "flat"
Cohesion: 0.27
Nodes (7): buy(), flat(), run(), TestCircuitLocks, TestFillTiming, TestParticipationCap, TestStopsAndTargets

### Community 94 - "test_backtest_engine.py"
Cohesion: 0.17
Nodes (14): AssertionError, LookAheadError, The only window a strategy gets onto the data. A strategy decides on the close…, A read would have returned data not available at the decision date., Walk-forward harness: tune on the training window, judge on the unseen test…, Walk-forward window generation -- pure. Tune on a training window, evaluate on…, Bar, dataclasses (+6 more)

### Community 95 - "canonical_index_code"
Cohesion: 0.33
Nodes (5): canonical_index_code(), Stable identity for an index whose printed name changes over time. Returns None…, parametrize, The finding this mapping exists for: NSE's benchmark is printed as three…, TestCanonicalIndexCode

### Community 96 - "NotSupportedError"
Cohesion: 0.09
Nodes (23): prices(), command, Backfill daily prices over a date range for one exchange. NSE source (legacy vs…, DataNotPublished, NotSupportedError, ProviderError, Base class for provider-adapter failures., The source has not yet published data for the requested date. Distinct from… (+15 more)

### Community 97 - "Oracle Cloud Always Free VM — setup notes"
Cohesion: 0.29
Nodes (7): Known friction points during signup, Oracle Cloud Always Free VM — setup notes, Provisioning the instance (once signup succeeds), Swap (important on ARM Always Free), Verifying capacity/ARM compatibility for Python deps now (optional, can do anytime), What phase 8 will set up on this box, What you're aiming for

### Community 98 - "TestDimensions"
Cohesion: 0.29
Nodes (3): fixture, The load-bearing case for query-time identity resolution: a bar written under a…, TestDimensions

### Community 99 - "ticker_for"
Cohesion: 0.47
Nodes (3): Yahoo ticker for an Indian listing., ticker_for(), TestTickerMapping

### Community 100 - "Data sources — verified endpoints"
Cohesion: 0.25
Nodes (7): Blocking behaviour summary, BSE, Daily EOD prices (deep history, 2010 – 2024-07-05): legacy `EQ*.CSV.ZIP`, Data sources — verified endpoints, Security master, Things still to verify (do not treat as settled), Transaction charges — verification ledger

### Community 101 - "stockAnalyser"
Cohesion: 0.33
Nodes (6): A note on scope, Common commands, Layout, Setup, Status, stockAnalyser

### Community 102 - "run_walk_forward"
Cohesion: 0.23
Nodes (11): _outcome(), DataFrame, RatesFn, run_walk_forward(), Window, Params, StrategyFactory, TestStorage (+3 more)

### Community 104 - "Phase 1 — data pipeline + store"
Cohesion: 0.33
Nodes (5): Cost config scaffold, Ingest pipeline, Parquet layout, Phase 1 — data pipeline + store, SQLite schema (phase 1 tables)

### Community 105 - "NseCorporateActionsProvider"
Cohesion: 0.22
Nodes (9): A corporate-action row with the subject text UNPARSED. Parsing free-text…, RawCorporateAction, NseCorporateActionsProvider, _parse_ddmmmyyyy_or_none(), date, Stable hash of the fields that define this action's identity and content --…, CorporateActionsProvider backed by NSE's corporates-corporateActions API., _source_hash() (+1 more)

### Community 106 - "build_client"
Cohesion: 0.67
Nodes (3): build_client(), Construct an httpx.Client with sane defaults for exchange fetches., Client

### Community 107 - "get_nse_price_provider_for_date"
Cohesion: 0.18
Nodes (10): date, get_nse_price_provider_for_date(), Automatic source selection for NSE prices by date, per the confirmed…, A more important finding: NSE's own archive occasionally serves mislabeled content, ADR 0003: Historical price source, BSE pre-UDiFF history (spike step 4, resolved 2026-09-18), Consequences, Context (+2 more)

### Community 109 - "enabled"
Cohesion: 0.50
Nodes (4): enabled(), provider(), fixture, Turn the feature flag on for tests that need the provider built. get_settings()…

### Community 116 - "MarketData"
Cohesion: 0.22
Nodes (7): MarketData, date, Adjusted daily bars for one exchange (+ optional point-in-time tables).…, Distinct bar dates in [start, end] that actually appear in the data., Emits pre-scripted signals on chosen decision-date indices., Scripted, factory()

### Community 117 - "ConfigError"
Cohesion: 0.24
Nodes (7): _DatedSeries, A chronologically sorted list of ``_DatedRate``, queryable by date., ConfigError, Configuration failed to load or validate., get_corporate_actions_provider(), Construct a CorporateActionsProvider by its config name (see…, TestGetCorporateActionsProvider

### Community 118 - "get_price_provider"
Cohesion: 0.25
Nodes (5): get_price_provider(), Construct a PriceProvider by its config name (see providers.prices in…, TestGetPriceProvider, It cannot drift onto the critical path just by being named in a config list., TestFeatureFlag

### Community 119 - "generate_windows"
Cohesion: 0.33
Nodes (5): _add_months(), generate_windows(), date, Rolling windows over [start, end]. A window is kept only if its whole test span…, TestWindows

### Community 120 - "check_job_runs"
Cohesion: 0.33
Nodes (4): check_job_runs(), Degraded or failed job runs in the lookback window. Only the LATEST attempt per…, job_runs is observability, not a lock -- repeated attempts are expected, and…, TestJobRuns

### Community 121 - "parse_udiff"
Cohesion: 0.36
Nodes (4): parse_udiff(), Parse an NSE or BSE UDiFF bhavcopy CSV into canonical bars. UDiFF carries ISIN…, UDiFF carries ISIN, unlike sec_bhavdata_full -- this is why it is the ISIN-…, TestParseUdiff

### Community 122 - "0002_backtest.sql"
Cohesion: 0.46
Nodes (7): backtest_equity, backtest_metrics, backtest_runs, backtest_trades, backtest_windows, ix_backtest_runs_strategy, ix_backtest_trades_run

### Community 123 - "get_bse_price_provider_for_date"
Cohesion: 0.40
Nodes (4): get_bse_price_provider_for_date(), date, Automatic source selection for BSE prices by date, mirroring…, TestGetBsePriceProviderForDate

### Community 124 - "history_probe.py"
Cohesion: 0.40
Nodes (5): main(), probe(), date, Phase-0 history spike: how far back does sec_bhavdata_full actually go? Per…, sys

### Community 125 - "commands/backtest.py"
Cohesion: 0.50
Nodes (4): list_runs(), command, `stk backtest` -- inspect stored backtest runs. Running a strategy needs the…, show()

### Community 127 - "_bars_to_table"
Cohesion: 0.50
Nodes (3): _bars_to_table(), Table, Convert parsed CanonicalBar pydantic models into an Arrow table matching…

### Community 128 - ".parse_holidays"
Cohesion: 0.50
Nodes (3): Re-parse a persisted artifact's bytes as a JSON object. Separate from…, Holiday rows for one segment, dates parsed strictly. An absent or empty segment…, validate_json_response_bytes()

### Community 130 - "_identity_map"
Cohesion: 0.67
Nodes (3): _identity_map(), Connection, (symbol) -> (security_id, isin) for one exchange, read once per run.…

## Knowledge Gaps
- **52 isolated node(s):** `stk`, `raw_artifacts`, `trading_calendar`, `stockanalyser`, `What this is` (+47 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 684 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **39 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Current status (update this section as phases complete)` connect `Current status (update this section as phases complete)` to `assert_bars_sane`, `liquidity.py`, `RawArtifact`, `registry.py`, `compute_costs`, `_ingest_prices_for_date`, `domain/costs.py`, `ingest/corpactions.py`, `ingest.py`, `ingest_security_master`, `CLAUDE.md`, `PointInTimeView`, `ingest_corporate_actions`, `upsert_partition`, `test_backtest_engine.py`, `NotSupportedError`, `Phase 1 — data pipeline + store`, `NseCorporateActionsProvider`, `get_nse_price_provider_for_date`, `ConfigError`, `get_bse_price_provider_for_date`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **Why does `connect()` connect `connect` to `doctor.py`, `backfill_nse_prices`, `liquidity.py`, `rebuild_adjusted_bars`, `datetime`, `registry.py`, `daily.py`, `_mock`, `ingest_calendar_year`, `_ingest_prices_for_date`, `ingest/corpactions.py`, `ingest.py`, `ingest_security_master`, `ingest_calendar_from_bars`, `adjustments.py`, `test_master_ingest.py`, `ingest/calendar.py`, `ingest_indices_for_date`, `ingest_corporate_actions`, `runs.py`, `Current status (update this section as phases complete)`, `flat`, `TestDimensions`, `run_walk_forward`, `commands/backtest.py`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Why does `ConfigError` connect `ConfigError` to `ingest.py`, `NotSupportedError`, `TestDimensions`, `loader.py`, `connect`, `duck.py`, `datetime`, `registry.py`, `ingest/calendar.py`, `get_price_provider`, `NseIndicesProvider`, `config/costs.py`, `Current status (update this section as phases complete)`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `RawArtifact` (e.g. with `persist_artifact()` and `fetch_bse_csv_file()`) actually correct?**
  _`RawArtifact` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `stk`, `raw_artifacts`, `trading_calendar` to the rest of the system?**
  _52 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `doctor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.11827956989247312 - nodes in this community are weakly interconnected._
- **Should `liquidity.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06453028972783142 - nodes in this community are weakly interconnected._