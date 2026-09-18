# Graph Report - stockAnalyser  (2026-09-19)

## Corpus Check
- 151 files · ~85,944 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 22 file(s) not represented in the graph (top: (none) 11, .csv 7, .CSV 2)

## Summary
- 2023 nodes · 4968 edges · 120 communities (88 shown, 32 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 393 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `50c1a2d5`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- doctor.py
- assert_bars_sane
- _fixture_for_date
- liquidity.py
- _resp
- is_weekend
- upsert_partition
- Project brief for Claude Code — Indian stock suggester + virtual playground
- RawArtifact
- connect
- build_factor_rows
- connect
- ProviderUnavailable
- rebuild_adjusted_bars
- httpx
- TestFetchHistory
- parse_ind_close_all
- MasterRecord
- job_run
- compute_metrics
- compute_costs
- datetime
- pathlib
- _mock
- ingest_calendar_year
- RateSchedule
- _write
- test_costs.py
- base.py
- format_inr
- 0001_init.sql
- parse_subject
- ingest.py
- BseUdiffProvider
- NseSecBhavdataProvider
- NseFundamentalsProvider
- NseLegacyBhavcopyProvider
- ingest/corpactions.py
- .test_a_pre_udiff_date_uses_the_legacy_source_not_a_failure
- compute_liquidity_for_date
- BseLegacyBhavcopyProvider
- ConfigError
- Table
- domain/costs.py
- test_backtest_engine.py
- main.py
- ingest/backfill.py
- ingest_security_master
- config/costs.py
- raw_store.py
- parse_legacy_bhavcopy
- NSE
- get_rate_schedule
- ingest_indices_for_date
- CLAUDE.md
- PointInTimeView
- TestLiveEndpoint
- test_nse_calendar_provider.py
- setup.py
- ingest_corporate_actions
- TestUrlAndCapabilities
- runs.py
- parse_sec_bhavdata_full
- ingest_fundamentals_for_security
- TestParse
- Indian stock suggester + virtual playground — build plan
- yfinance/__init__.py
- queries/__init__.py
- stk
- .fetch_filings_index
- circuit_lock
- PriceBand
- NseIndicesProvider
- CanonicalBar
- IngestAssertionError
- slippage.py
- _Run
- prices
- _upsert_action
- backtest/engine.py
- canonical_index_code
- NotSupportedError
- Oracle Cloud Always Free VM — setup notes
- Connection
- ticker_for
- stockAnalyser
- run_walk_forward
- Phase 1 — data pipeline + store
- nse/corpactions.py
- given
- assert_bars_match_requested_date
- TestLiveEndpoint
- enabled
- TestLiveEndpoint
- TestCapabilities
- CorporateActionsProvider
- get_price_provider
- 0002_backtest.sql
- history_probe.py
- backtest/__init__.py

## God Nodes (most connected - your core abstractions)
1. `_mock()` - 81 edges
2. `connect()` - 74 edges
3. `RawArtifact` - 51 edges
4. `migrate()` - 48 edges
5. `CanonicalBar` - 37 edges
6. `NotSupportedError` - 36 edges
7. `ContentValidationError` - 35 edges
8. `DataNotPublished` - 34 edges
9. `job_run()` - 31 edges
10. `upsert_partition()` - 29 edges

## Surprising Connections (you probably didn't know these)
- `Ground rules (from the brief, do not relitigate without asking)` --references--> `corpactions()`  [INFERRED]
  CLAUDE.md → backend/src/stk/cli/commands/ingest.py
- `Daily EOD prices (primary source): `sec_bhavdata_full`` --references--> `NseSecBhavdataProvider`  [INFERRED]
  docs/data-sources.md → backend/src/stk/providers/nse/prices.py
- `Verification` --references--> `ContentValidationError`  [INFERRED]
  docs/BUILD_PLAN.md → backend/src/stk/core/errors.py
- `Current status (update this section as phases complete)` --references--> `Strategy`  [INFERRED]
  CLAUDE.md → backend/src/stk/backtest/engine.py
- `Current status (update this section as phases complete)` --references--> `LookAheadError`  [INFERRED]
  CLAUDE.md → backend/src/stk/backtest/view.py

## Import Cycles
- None detected.

## Communities (120 total, 32 thin omitted)

### Community 0 - "doctor.py"
Cohesion: 0.05
Nodes (53): _check_endpoints(), doctor(), _previous_weekday(), command, date, `stk doctor` -- ingest health check. Thin by design: every actual check lives…, Step back to the nearest weekday. Holidays are not filtered -- a holiday simply…, Report on ingest health. Exits non-zero if anything looks wrong. (+45 more)

### Community 1 - "assert_bars_sane"
Cohesion: 0.23
Nodes (7): assert_bars_sane(), Cheap, fast invariant checks over a batch of parsed bars. Deliberately does NOT…, _bar(), Tests for post-ingest sanity assertions. Includes a regression test for a real…, Regression test: a real live-ingest failure. Thin government securities…, The floor must not swallow real bugs once absolute values are large enough to…, TestAssertBarsSane

### Community 2 - "_fixture_for_date"
Cohesion: 0.30
Nodes (6): _fixture_for_date(), _mock_date(), 2026-09-19/20 is a Sat/Sun -- must not even attempt a request., The core resilience property: one bad date must not abort the whole range --…, Real fixture content, with every DATE1 value rewritten to `d`., TestBackfillNsePrices

### Community 3 - "liquidity.py"
Cohesion: 0.08
Nodes (29): LiquidityConfig, BaseModel, Loader for config/universe.yaml -- liquidity thresholds and the…, UniverseConfig, is_liquid(), is_tradeable_intraday(), LiquidityMetrics, LiquidityThresholds (+21 more)

### Community 4 - "_resp"
Cohesion: 0.12
Nodes (11): Response, Tests for the content-type/magic-byte guard against the BSE 'silent 200'…, The exact BSE failure: 200 OK, HTML body -- must raise, not parse., The trap must not be swallowed anywhere -- calling code should never see a…, Exchanges do serve real CSVs with inconsistent content-type headers (e.g.…, A misleading content-type header must not override the actual body check., Mirror of the BSE CSV trap for the NSE/BSE zip download path., _resp() (+3 more)

### Community 5 - "is_weekend"
Cohesion: 0.08
Nodes (18): is_weekend(), True for Saturday/Sunday. NSE's holiday-master API includes holidays that fall…, build_trading_day_set(), last_trading_day_on_or_before(), date, All weekday dates in [start, end] that are not in holiday_dates., Walk backward from target (inclusive) to find the nearest trading day. Bounded…, date (+10 more)

### Community 6 - "upsert_partition"
Cohesion: 0.07
Nodes (35): Path, Schema, Table, Overwrite-by-partition write. Returns the row count of the resulting file.…, Read a partition file, or return an empty table matching ``schema`` if absent., Streaming sha256 of a file on disk., Write the row-count + sha256 sidecar for a just-written partition. The sha256…, The manifest for one partition, or None if none was written. (+27 more)

### Community 7 - "Project brief for Claude Code — Indian stock suggester + virtual playground"
Cohesion: 0.14
Nodes (14): 10. Screens (designs come from Claude Design), 11. Build phases (do them in order; stop and check in with me after each), 12. How to work with me, 1. What the app does, 2. Hard constraints, 3. Stack, 4. Data layer, 5. Strategies — four horizons (+6 more)

### Community 8 - "RawArtifact"
Cohesion: 0.09
Nodes (35): build_client(), Response, Shared HTTP client factory and response validation. This module is the single…, Construct an httpx.Client with sane defaults for exchange fetches., Validate a response that is expected to be a zip file. Checks status, then…, Validate a response that is expected to be a plain CSV file.…, validate_csv_response(), validate_zip_response() (+27 more)

### Community 9 - "connect"
Cohesion: 0.08
Nodes (30): connect(), _discover_migrations(), migrate(), Connection, Path, Open a connection with the app's standard pragmas applied., Explicit transaction context manager (conn is opened in autocommit mode)., Return (sequence_number, name, path) for every migrations/*.sql file, sorted. (+22 more)

### Community 10 - "build_factor_rows"
Cohesion: 0.09
Nodes (33): ActionFactor, build_factor_rows(), _factor_table(), FactorRow, factors_for_bar(), load_actions(), _LoadedActions, BaseModel (+25 more)

### Community 11 - "connect"
Cohesion: 0.06
Nodes (46): load_benchmark(), load_market_data(), prepare_bars(), DataFrame, date, Path, Add prev_close and adv_turnover (both past-only) to a raw adjusted-bars frame., Adjusted bars for [start - warmup, end], prepared for the engine. (+38 more)

### Community 12 - "ProviderUnavailable"
Cohesion: 0.07
Nodes (36): ParseError, ProviderUnavailable, Exception, Base class for all application-raised errors., Transport-level failure: timeout, connection refused, DNS, 5xx., A response was structurally valid but semantically un-parseable. Used by the…, StkError, Validate a response that is expected to be JSON. (+28 more)

### Community 13 - "rebuild_adjusted_bars"
Cohesion: 0.12
Nodes (24): AdjustmentResult, Path, Rebuild adjustment_factors and bars_daily_adjusted for one exchange. Network-…, rebuild_adjusted_bars wrapped in a job_run scope. Kept separate so the rebuild…, rebuild_adjusted_bars(), rebuild_adjusted_bars_job(), adjustment_factors_path(), bars_daily_adjusted_partition() (+16 more)

### Community 14 - "httpx"
Cohesion: 0.14
Nodes (13): httpx, json, respx, Integration tests for ingest_corporate_actions: fetch -> parse -> upsert., Tests for BseLegacyBhavcopyProvider, mocked via respx. Mirrors…, Tests for BseSecurityMasterProvider, mocked via respx., Tests for BseUdiffProvider, mocked via respx (no live network in the default…, Tests for NseCorporateActionsProvider, mocked via respx. (+5 more)

### Community 15 - "TestFetchHistory"
Cohesion: 0.29
Nodes (5): _frame(), DataFrame, Yahoo reports no rupee turnover. close*volume is derived and must never be…, An empty result means a wrong ticker, a delisted name, or a rate limit -- never…, TestFetchHistory

### Community 16 - "parse_ind_close_all"
Cohesion: 0.17
Nodes (8): parse_ind_close_all(), Parse NSE's ind_close_all_DDMMYYYY.csv into canonical index bars. Two…, 18775.3 crore = 1,87,753,000,000 rupees. The word "crore" must never survive…, NSE's file carries rows like "Nifty50 Dividend Points" that have a real close…, A row with no closing value is not a price bar at all., TestMalformedInput, TestNullHandling, TestParseRealFixture

### Community 17 - "MasterRecord"
Cohesion: 0.11
Nodes (19): _fetch_all_records(), Connection, Returns True if this upsert closed out a rename (a different symbol was…, Fetch every exchange's master snapshot, tolerating one exchange's fetch failing…, _upsert_listing_and_detect_rename(), _upsert_security(), MasterRecord, One row of a security-master snapshot (NSE EQUITY_L.csv / BSE ListofScripData). (+11 more)

### Community 18 - "job_run"
Cohesion: 0.07
Nodes (27): code_version(), The running code's version, for attributing written data to a commit. Both…, Short git SHA of HEAD, or "unknown" outside a git checkout. Never raises: an…, job_run(), JobRunHandle, JobSkipped, _next_attempt(), Connection (+19 more)

### Community 19 - "compute_metrics"
Cohesion: 0.08
Nodes (23): cagr(), compute_metrics(), max_drawdown(), date, Backtest performance metrics -- pure. Statistics, not money: inputs are…, One closed round trip, net of all costs., Worst peak-to-trough decline as a NEGATIVE fraction (0.0 if never below a peak)., Annualised Sharpe from daily equity. 0.0 when there is no variance to divide by. (+15 more)

### Community 20 - "compute_costs"
Cohesion: 0.14
Nodes (15): compute_costs(), Itemised charges for one order leg of ``turnover`` rupees. Excludes the DP…, given, date, Decimal, rates(), compute_costs against hand-worked examples. A wrong rate or a mis-scoped GST…, Changing STT or stamp duty must not change GST -- the one-line bug the config… (+7 more)

### Community 21 - "datetime"
Cohesion: 0.11
Nodes (26): _adjust_bar(), Decimal, Corporate-action back-adjustment: factor timelines and the derived…, Index (benchmark) ingest. Same shape as ingest.daily's price path -- fetch,…, manifest_path(), Parquet path conventions. Partitioned by exchange then year:…, Where the row-count + sha256 sidecar for one partition lives. ``exchange`` is…, Canonical Arrow schema for daily bars. NSE UDiFF, BSE UDiFF and… (+18 more)

### Community 22 - "pathlib"
Cohesion: 0.12
Nodes (15): Trading-calendar ingest: populating `trading_calendar` from NSE, and from what…, Fundamentals ingest: fetch a security's filings and upsert into…, Security-master ingest: ISIN-keyed merge of NSE + BSE listings into…, SQLite connection factory, pragmas, and the forward-only migration runner. No…, DuckDB connection factory, view registration, and named-SQL access. This is the…, collections, duckdb, importlib (+7 more)

### Community 23 - "_mock"
Cohesion: 0.12
Nodes (14): ingest_nse_prices_for_date(), Ingest one day of NSE prices end-to-end: fetch, validate, persist raw, parse,…, 2010-01-04 is before the UDiFF cutover, so get_bse_price_provider_for_date must…, The BSE-specific failure mode: a non-trading day returns HTTP 200 with an HTML…, TestIngestBsePricesForDate, The wiring proof: on a date the calendar says did not trade, the nightly ingest…, Tri-state, not boolean: no calendar row means UNKNOWN, and unknown must be…, TestDailyIngestHonoursTheCalendar (+6 more)

### Community 24 - "ingest_calendar_year"
Cohesion: 0.10
Nodes (26): CalendarIngestResult, ingest_calendar_from_bars(), ingest_calendar_year(), Connection, date, Path, Populate one calendar year for one exchange from NSE's holiday master. Writes a…, Derive calendar rows from the dates actually present in bars_daily. Covers only… (+18 more)

### Community 25 - "RateSchedule"
Cohesion: 0.20
Nodes (10): _DatedRate, _DatedSeries, BaseModel, date, RateSchedule, Every rate in force for ``exchange`` on ``as_of_date``, as pure domain data., A rate that takes effect from a given date, until superseded., A chronologically sorted list of ``_DatedRate``, queryable by date. (+2 more)

### Community 26 - "_write"
Cohesion: 0.09
Nodes (12): _bars(), date, fixture, Path, Table, The load-bearing case for query-time identity resolution: a bar written under a…, exchange/year come from the directory names, not the file -- the liquidity and…, A fresh checkout has no bars_daily_adjusted. Querying it must return zero rows… (+4 more)

### Community 27 - "test_costs.py"
Cohesion: 0.07
Nodes (15): fixture, Tests for the dated cost-rate schedule (config/costs.yaml + RateSchedule).…, DP charge: flat, per-scrip, per-day, sell leg only -- dominates cost on small…, NSE exchange transaction charge changed 2024-10-01 and again 2026-03-01., NSE IPFT dropped from Rs 10/crore to Rs 0.01/crore on 2026-03-01., Stamp duty became uniform nationwide on 2020-07-01., STT: delivery both legs; intraday sell-leg only., GST must apply to brokerage/exchange_txn/sebi fee/IPFT and NOT to STT or stamp… (+7 more)

### Community 28 - "base.py"
Cohesion: 0.07
Nodes (44): ABC, Exception hierarchy for the ingest/provider stack. The rule this hierarchy…, format_ddmmyy_compact(), format_ddmmyyyy_compact(), format_yyyymmdd(), parse_ddmmmyyyy(), parse_ddmmyyyy_compact(), previous_calendar_day() (+36 more)

### Community 29 - "format_inr"
Cohesion: 0.14
Nodes (13): bps(), format_inr(), Decimal, Decimal-safe money arithmetic and Indian-style (lakh/crore) formatting. Every…, Convert any numeric input to a Decimal rounded to paise., Express ``value`` as basis points of ``basis``. Returns 0 if basis is 0., Format a rupee amount with Indian digit grouping (lakh/crore).…, to_money() (+5 more)

### Community 30 - "0001_init.sql"
Cohesion: 0.17
Nodes (20): corporate_actions, fundamentals_snapshots, ix_ca_exdate, ix_ca_parse_status, ix_ca_security_ex, ix_fund_provider, ix_fund_sec_period, ix_job_lookup (+12 more)

### Community 31 - "parse_subject"
Cohesion: 0.17
Nodes (18): ActionType, parse_subject(), StrEnum, Parse a free-text corporate-action subject into typed actions. Handles compound…, hypothesis, given, parametrize, Table-driven tests for the free-text corporate-action subject parser. The… (+10 more)

### Community 32 - "ingest.py"
Cohesion: 0.07
Nodes (46): adjustments(), calendar(), corpactions(), daily(), fundamentals(), indices(), liquidity(), master() (+38 more)

### Community 33 - "BseUdiffProvider"
Cohesion: 0.20
Nodes (9): BseUdiffProvider, PriceProvider backed by BSE's UDiFF daily bhavcopy., _csv_response(), Response, The confirmed-live BSE trap: a weekend, holiday, or invalid date returns HTTP…, Not text/html, but also doesn't look like the expected CSV -- must still be…, TestCapabilities, TestFetchEod (+1 more)

### Community 34 - "NseSecBhavdataProvider"
Cohesion: 0.14
Nodes (11): NseSecBhavdataProvider, PriceProvider backed by NSE's sec_bhavdata_full daily file., _csv_response(), live, Response, Defence-in-depth: even though NSE's archive host has not been observed doing…, Real network smoke test -- excluded from the default run. Run explicitly with…, TestCapabilities (+3 more)

### Community 35 - "NseFundamentalsProvider"
Cohesion: 0.15
Nodes (15): Connection, _resolve_security_id(), _upsert_snapshot(), FundamentalsSnapshotIn, Period, StrEnum, A normalised fundamentals statement, ready for insertion into…, Normalised statements ready for fundamentals_snapshots insertion. (+7 more)

### Community 36 - "NseLegacyBhavcopyProvider"
Cohesion: 0.18
Nodes (8): NseLegacyBhavcopyProvider, PriceProvider backed by NSE's legacy per-date cm*bhav.csv.zip archive., live, TestCapabilities, TestFetchEod, TestLiveEndpoint, TestParseEod, _zip_bytes()

### Community 37 - "ingest/corpactions.py"
Cohesion: 0.23
Nodes (17): _ClauseResult, _parse_bonus(), _parse_clause(), _parse_decimal(), _parse_dividend(), _parse_face_value_split(), _parse_rights(), ParsedAction (+9 more)

### Community 38 - ".test_a_pre_udiff_date_uses_the_legacy_source_not_a_failure"
Cohesion: 0.21
Nodes (9): _bse_fixture_for_date(), _bse_legacy_fixture(), _mock_bse_date(), _mock_bse_legacy_date(), date, BSE shares _backfill_prices with NSE (see test cases above for the generic…, 2020-01-01 is between BSE's two confirmed sources' boundary (2010-01-04 legacy…, Real BSE UDiFF fixture content, with every TradDt/BizDt value rewritten to `d`. (+1 more)

### Community 39 - "compute_liquidity_for_date"
Cohesion: 0.27
Nodes (11): compute_liquidity_for_date(), Compute and persist one exchange's liquidity features for one date. Idempotent…, liquidity_daily_partition(), _make_universe_config(), date, Path, No security master data exists yet -- documented known limitation in…, n consecutive weekdays ending at (and including) end. (+3 more)

### Community 40 - "BseLegacyBhavcopyProvider"
Cohesion: 0.13
Nodes (10): ProviderCapabilities, Declares what a provider can actually do, so callers can degrade gracefully…, BseLegacyBhavcopyProvider, PriceProvider backed by BSE's legacy per-date EQ*.CSV.ZIP archive., live, TestCapabilities, TestFetchEod, TestLiveEndpoint (+2 more)

### Community 41 - "ConfigError"
Cohesion: 0.07
Nodes (36): _deep_merge(), find_config_dir(), load_named_yaml(), load_yaml_config(), Any, Path, YAML config loading and layering. Precedence, highest wins: 1. Process env /…, Recursively merge ``overlay`` onto ``base``. ``overlay`` wins on conflicts. (+28 more)

### Community 43 - "domain/costs.py"
Cohesion: 0.19
Nodes (14): command, quote(), `stk costs` -- inspect the transaction-cost model., Itemise the charges on one order leg, using the rates in force on a date. Rates…, CostBreakdown, dp_charge(), Product, Decimal (+6 more)

### Community 44 - "test_backtest_engine.py"
Cohesion: 0.12
Nodes (23): Bar, buy(), config(), days_of(), flat(), make_data(), poison_after(), date (+15 more)

### Community 45 - "main.py"
Cohesion: 0.15
Nodes (12): migrate_cmd(), command, `stk db` -- database management commands., Apply all pending SQLite migrations., _init(), `stk` -- the project's single CLI entry point. Subcommands are grouped by…, configure_logging(), Configure structlog + stdlib logging. Call once at process startup. (+4 more)

### Community 46 - "ingest/backfill.py"
Cohesion: 0.25
Nodes (11): `stk backfill` -- historical price backfill., backfill_bse_prices(), backfill_nse_prices(), _backfill_prices(), BackfillSummary, date, Path, Historical price backfill. Reuses the same per-exchange ingest function… (+3 more)

### Community 47 - "ingest_security_master"
Cohesion: 0.27
Nodes (10): ingest_security_master(), MasterIngestResult, Path, Fetch and merge the NSE + BSE security masters into securities/…, _bse_row(), _mock_bse(), _mock_nse(), _nse_row() (+2 more)

### Community 48 - "config/costs.py"
Cohesion: 0.19
Nodes (11): _dec(), Decimal, product(), Dated cost-rate schedule loader. Loads config/costs.yaml -- a history of…, Decimal from a YAML number without inheriting float noise (0.1 ->…, BrokerageRule, CostRates, ProductRates (+3 more)

### Community 49 - "raw_store.py"
Cohesion: 0.31
Nodes (8): _guess_suffix(), persist_artifact(), Connection, date, Path, Persistence of raw fetched bytes, content-addressed for idempotency. Every…, Write the artifact's bytes to disk and record it in raw_artifacts. Returns the…, _raw_path()

### Community 50 - "parse_legacy_bhavcopy"
Cohesion: 0.29
Nodes (5): parse_legacy_bhavcopy(), Parse NSE's legacy cm{DDMONYYYY}bhav.csv format (2010 through ~2019-10-01,…, The real 2010 file uses '4-JAN-2010', not '04-JAN-2010'., This format predates delivery reporting -- delivery fields must be None, not…, TestParseLegacyBhavcopy

### Community 51 - "NSE"
Cohesion: 0.18
Nodes (10): Blocking behaviour summary, Corporate actions, Daily EOD prices (primary source): `sec_bhavdata_full`, Data sources — verified endpoints, Fundamentals (official, no XBRL parsing needed), NSE, Price bands (for circuit-lock detection), Security master (+2 more)

### Community 52 - "get_rate_schedule"
Cohesion: 0.22
Nodes (8): make_rates_fn(), RatesFn, Rates in force on each fill's own date, memoised per (exchange, date)., get_rate_schedule(), Path, Return the process-wide RateSchedule singleton, loading config/costs.yaml on…, fixture, schedule()

### Community 53 - "ingest_indices_for_date"
Cohesion: 0.16
Nodes (11): IndicesIngestResult, ingest_indices_for_date(), date, Path, Table, Ingest one day of NSE index closes end-to-end. Idempotent., _to_table(), indices_daily_partition() (+3 more)

### Community 54 - "CLAUDE.md"
Cohesion: 0.29
Nodes (5): graphify, Ground rules (from the brief, do not relitigate without asking), Repo layout, What this is, Working here

### Community 55 - "PointInTimeView"
Cohesion: 0.12
Nodes (18): AssertionError, An intent to buy at the next open., Signal, Strategy, LookAheadError, PointInTimeView, DataFrame, Every bar dated <= ``decision_date`` (all symbols). (+10 more)

### Community 56 - "TestLiveEndpoint"
Cohesion: 0.29
Nodes (4): live, Documented shape checks. Run deliberately: `pytest -m live`., The finding that justified using this endpoint for the whole backfill range…, TestLiveEndpoint

### Community 57 - "test_nse_calendar_provider.py"
Cohesion: 0.25
Nodes (5): Trading-calendar domain logic built from raw holiday data. Combines a…, Tests for trading-calendar domain logic (weekday-holiday intersection)., provider(), fixture, Unit tests for the NSE holiday-master provider. The two behaviours that carry…

### Community 58 - "setup.py"
Cohesion: 0.17
Nodes (15): EngineConfig, build_engine_config(), Turn config files into the engine's inputs., BacktestConfig, load_backtest_config(), BaseModel, Path, Typed loader for config/backtest.yaml. (+7 more)

### Community 59 - "ingest_corporate_actions"
Cohesion: 0.27
Nodes (7): CorpActionIngestResult, ingest_corporate_actions(), date, Path, Fetch corporate actions, parse subjects, and upsert into corporate_actions. One…, _row(), TestIngestCorporateActions

### Community 61 - "runs.py"
Cohesion: 0.19
Nodes (21): BacktestResult, _begin(), _finish(), _insert_trades(), load_run_summary(), _metric_rows(), Any, date (+13 more)

### Community 62 - "parse_sec_bhavdata_full"
Cohesion: 0.24
Nodes (5): parse_sec_bhavdata_full(), Parse NSE's sec_bhavdata_full_{DDMMYYYY}.csv into canonical bars. This file…, The real NSE file has a leading space on every header/value after the first…, This is the critical rule: '-' means unreported, not zero., TestParseSecBhavdataFull

### Community 63 - "ingest_fundamentals_for_security"
Cohesion: 0.27
Nodes (6): FundamentalsIngestResult, ingest_fundamentals_for_security(), Path, Fetch one security's recent filings and upsert into fundamentals_snapshots. One…, _insert_security(), TestIngestFundamentalsForSecurity

### Community 65 - "Indian stock suggester + virtual playground — build plan"
Cohesion: 0.15
Nodes (13): Context, Decisions locked this session, Design system (extracted from the handoff), Guiding principles for phases 0–1, Indian stock suggester + virtual playground — build plan, Open items for later phases, Phase 0 — repo, config, VM notes, history spike, Phases 2–8 (outline only) (+5 more)

### Community 84 - ".fetch_filings_index"
Cohesion: 0.40
Nodes (3): date, Download the full-market EOD file for one date. Raises: ProviderUnavailable:…, What filings exist -- cheap, used to decide what to fetch.

### Community 85 - "circuit_lock"
Cohesion: 0.17
Nodes (14): BarPrices, can_buy(), can_sell(), circuit_lock(), Lock, Decimal, StrEnum, Fill-price rules -- pure. Two rules matter and both are easy to get subtly… (+6 more)

### Community 86 - "PriceBand"
Cohesion: 0.40
Nodes (3): PriceBand, A daily price-band record (NSE sec_list.csv)., Daily price-band list, used for circuit-lock detection. Optional.

### Community 87 - "NseIndicesProvider"
Cohesion: 0.16
Nodes (12): index_archive_url(), NseIndicesProvider, date, Fetches NSE's daily all-index close file., Fetch one date's index file, validated and ready to persist., get_indices_provider(), Construct the index (benchmark) provider by name. Not behind an ABC yet: there…, Index closes (benchmark) — `ind_close_all` (+4 more)

### Community 88 - "CanonicalBar"
Cohesion: 0.09
Nodes (22): ContentValidationError, A response passed HTTP status but failed content-type/magic-byte checks. This…, _decimal_or_none(), _int_or_none(), parse_bse_legacy_bhavcopy(), _parse_iso_date(), parse_udiff(), date (+14 more)

### Community 89 - "IngestAssertionError"
Cohesion: 0.20
Nodes (13): IngestAssertionError, A post-ingest sanity check failed (row counts, OHLC invariants, ...)., assert_index_bars_match_requested_date(), assert_index_bars_sane(), _assert_turnover_plausible(), date, Post-ingest sanity assertions. Run after every parse, before a partition write…, Post-parse sanity checks for index bars. Deliberately narrower than… (+5 more)

### Community 90 - "slippage.py"
Cohesion: 0.15
Nodes (11): apply_slippage(), cap_quantity(), Decimal, Tiered slippage and the participation cap -- pure. Slippage is a function of…, Basis points of slippage for a name with the given trailing ADV turnover.…, Adverse slippage: buys fill higher, sells fill lower., Largest fillable quantity given a bar's volume and a participation cap (0..1]., slippage_bps() (+3 more)

### Community 91 - "_Run"
Cohesion: 0.29
Nodes (9): _d(), _Position, Any, date, Decimal, Mutable state and steps of one backtest run., Which exit (if any) this bar triggers, and at what pre-slippage price., _Run (+1 more)

### Community 92 - "prices"
Cohesion: 0.50
Nodes (3): prices(), command, Backfill daily prices over a date range for one exchange. NSE source (legacy vs…

### Community 93 - "_upsert_action"
Cohesion: 0.67
Nodes (4): Connection, Parse raw.subject_raw and upsert one corporate_actions row keyed on (source,…, _resolve_security_id(), _upsert_action()

### Community 94 - "backtest/engine.py"
Cohesion: 0.11
Nodes (20): Load market data for a backtest, and prepare it point-in-time. Everything a…, _align_benchmark(), DataFrame, RatesFn, Daily event-loop backtester. Sequence for each trading date d (the order is the…, Benchmark closes aligned to ``dates`` (forward-filled), or (None, True) if…, run_backtest(), Trade (+12 more)

### Community 95 - "canonical_index_code"
Cohesion: 0.33
Nodes (5): canonical_index_code(), Stable identity for an index whose printed name changes over time. Returns None…, parametrize, The finding this mapping exists for: NSE's benchmark is printed as three…, TestCanonicalIndexCode

### Community 96 - "NotSupportedError"
Cohesion: 0.09
Nodes (22): DataNotPublished, NotSupportedError, ProviderError, Base class for provider-adapter failures., The source has not yet published data for the requested date. Distinct from…, A provider does not implement an optional capability., Interval, Per-symbol history. Optional -- full-market-file providers (bhavcopy-based)… (+14 more)

### Community 97 - "Oracle Cloud Always Free VM — setup notes"
Cohesion: 0.29
Nodes (7): Known friction points during signup, Oracle Cloud Always Free VM — setup notes, Provisioning the instance (once signup succeeds), Swap (important on ARM Always Free), Verifying capacity/ARM compatibility for Python deps now (optional, can do anytime), What phase 8 will set up on this box, What you're aiming for

### Community 99 - "ticker_for"
Cohesion: 0.47
Nodes (3): Yahoo ticker for an Indian listing., ticker_for(), TestTickerMapping

### Community 101 - "stockAnalyser"
Cohesion: 0.33
Nodes (6): A note on scope, Common commands, Layout, Setup, Status, stockAnalyser

### Community 102 - "run_walk_forward"
Cohesion: 0.21
Nodes (11): _outcome(), DataFrame, RatesFn, run_walk_forward(), Window, Params, StrategyFactory, TestStorage (+3 more)

### Community 104 - "Phase 1 — data pipeline + store"
Cohesion: 0.50
Nodes (4): Cost config scaffold, Parquet layout, Phase 1 — data pipeline + store, SQLite schema (phase 1 tables)

### Community 105 - "nse/corpactions.py"
Cohesion: 0.21
Nodes (10): A corporate-action row with the subject text UNPARSED. Parsing free-text…, RawCorporateAction, NseCorporateActionsProvider, _parse_ddmmmyyyy_or_none(), date, NSE corporate-actions provider. Verified live 2026-09-18: unlike the vague…, Stable hash of the fields that define this action's identity and content --…, CorporateActionsProvider backed by NSE's corporates-corporateActions API. (+2 more)

### Community 107 - "assert_bars_match_requested_date"
Cohesion: 0.15
Nodes (11): assert_bars_match_requested_date(), Assert every parsed bar's date matches the date we actually requested from the…, A more important finding: NSE's own archive occasionally serves mislabeled content, ADR 0003: Historical price source, Consequences, Context, Decision, Daily EOD prices (deep history, 2010-2019): legacy `cm*bhav.csv.zip` (+3 more)

### Community 109 - "enabled"
Cohesion: 0.50
Nodes (4): enabled(), provider(), fixture, Turn the feature flag on for tests that need the provider built. get_settings()…

### Community 117 - "CorporateActionsProvider"
Cohesion: 0.28
Nodes (6): CorporateActionsProvider, Source of corporate-action announcements, subjects unparsed., Corporate actions since ``since`` (or all available if None)., get_corporate_actions_provider(), Construct a CorporateActionsProvider by its config name (see…, TestGetCorporateActionsProvider

### Community 118 - "get_price_provider"
Cohesion: 0.09
Nodes (17): get_bse_price_provider_for_date(), get_nse_price_provider_for_date(), get_price_provider(), date, Automatic source selection for BSE prices by date, mirroring…, Construct a PriceProvider by its config name (see providers.prices in…, Automatic source selection for NSE prices by date, per the confirmed…, BSE (+9 more)

### Community 122 - "0002_backtest.sql"
Cohesion: 0.46
Nodes (7): backtest_equity, backtest_metrics, backtest_runs, backtest_trades, backtest_windows, ix_backtest_runs_strategy, ix_backtest_trades_run

### Community 124 - "history_probe.py"
Cohesion: 0.20
Nodes (9): get_logger(), Structured logging setup. JSON output in production (so the systemd journal /…, BoundLogger, main(), probe(), date, Phase-0 history spike: how far back does sec_bhavdata_full actually go? Per…, structlog (+1 more)

## Knowledge Gaps
- **52 isolated node(s):** `What this is`, `Repo layout`, `Working here`, `graphify`, `Blocking behaviour summary` (+47 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 695 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **32 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Current status (update this section as phases complete)` connect `ingest.py` to `liquidity.py`, `upsert_partition`, `rebuild_adjusted_bars`, `MasterRecord`, `compute_costs`, `parse_subject`, `NseFundamentalsProvider`, `ConfigError`, `domain/costs.py`, `ingest_security_master`, `CLAUDE.md`, `PointInTimeView`, `ingest_corporate_actions`, `ingest_fundamentals_for_security`, `CanonicalBar`, `NotSupportedError`, `nse/corpactions.py`, `assert_bars_match_requested_date`, `get_price_provider`?**
  _High betweenness centrality (0.092) - this node is a cross-community bridge._
- **Why does `connect()` connect `connect` to `doctor.py`, `ingest.py`, `_fixture_for_date`, `liquidity.py`, `ingest/corpactions.py`, `compute_liquidity_for_date`, `rebuild_adjusted_bars`, `ingest_security_master`, `_mock`, `datetime`, `pathlib`, `ingest_indices_for_date`, `ingest_calendar_year`, `_write`, `ingest_corporate_actions`, `ingest_fundamentals_for_security`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Why does `DataNotPublished` connect `NotSupportedError` to `doctor.py`, `ingest.py`, `BseUdiffProvider`, `NseSecBhavdataProvider`, `NseLegacyBhavcopyProvider`, `is_weekend`, `RawArtifact`, `BseLegacyBhavcopyProvider`, `ProviderUnavailable`, `TestFetchHistory`, `ingest_indices_for_date`, `datetime`, `NseIndicesProvider`, `TestLiveEndpoint`, `base.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `RawArtifact` (e.g. with `persist_artifact()` and `fetch_bse_csv_file()`) actually correct?**
  _`RawArtifact` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `migrate()` (e.g. with `.test_empty_walk_forward_rejected()` and `.test_single_run_round_trips()`) actually correct?**
  _`migrate()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `What this is`, `Repo layout`, `Working here` to the rest of the system?**
  _52 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `doctor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.053946053946053944 - nodes in this community are weakly interconnected._