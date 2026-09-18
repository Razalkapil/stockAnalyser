# Graph Report - stockAnalyser  (2026-09-19)

## Corpus Check
- 130 files · ~74,301 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 22 file(s) not represented in the graph (top: (none) 11, .csv 7, .CSV 2)

## Summary
- 1652 nodes · 4010 edges · 116 communities (85 shown, 31 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 294 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c44a20a1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- doctor.py
- assert_bars_sane
- backfill_nse_prices
- liquidity.py
- validate_json_response
- time.py
- read_manifest
- Project brief for Claude Code — Indian stock suggester + virtual playground
- RawArtifact
- connect
- build_factor_rows
- duck.py
- DataNotPublished
- test_adjustments_ingest.py
- datetime
- TestFetchHistory
- ParseError
- base.py
- job_run
- ingest.py
- PriceProvider
- ingest/indices.py
- engine.py
- _mock
- _holiday_payload
- ConfigError
- _write
- test_costs.py
- daily.py
- format_inr
- 0001_init.sql
- ingest/corpactions.py
- NseFundamentalsProvider
- NotSupportedError
- NseSecBhavdataProvider
- nse/archives.py
- NseLegacyBhavcopyProvider
- ingest/master.py
- ingest/backfill.py
- ingest_calendar_from_bars
- BseLegacyBhavcopyProvider
- costs.py
- compute_liquidity_for_date
- adjustments.py
- TestParseHolidays
- main.py
- settings.py
- ingest_security_master
- _YamlSettingsSource
- ingest_calendar_year
- parse_legacy_bhavcopy
- IngestAssertionError
- get_rate_schedule
- ingest_indices_for_date
- CLAUDE.md
- _make_bars
- TestLiveEndpoint
- PathsConfig
- manifest_path
- ingest_corporate_actions
- TestUrlAndCapabilities
- code_version
- parse_sec_bhavdata_full
- ingest_fundamentals_for_security
- TestParse
- Indian stock suggester + virtual playground — build plan
- yfinance/__init__.py
- queries/__init__.py
- stk
- upsert_partition
- MasterRecord
- bse/archives.py
- NseIndicesProvider
- _decimal_or_none
- IndexBar
- get_security_master_provider
- BseSecurityMasterProvider
- conftest.py
- load_actions
- JobSkipped
- canonical_index_code
- session.py
- Oracle Cloud Always Free VM — setup notes
- TestDimensions
- ticker_for
- Data sources — verified endpoints
- stockAnalyser
- .fetch_indices
- Phase 1 — data pipeline + store
- TestStampDutyBoundary
- build_client
- JobRunHandle
- TestLiveEndpoint
- enabled
- TestLiveEndpoint
- TestCapabilities
- env

## God Nodes (most connected - your core abstractions)
1. `_mock()` - 81 edges
2. `connect()` - 74 edges
3. `RawArtifact` - 51 edges
4. `migrate()` - 45 edges
5. `CanonicalBar` - 37 edges
6. `NotSupportedError` - 36 edges
7. `ContentValidationError` - 35 edges
8. `DataNotPublished` - 34 edges
9. `ConfigError` - 31 edges
10. `job_run()` - 31 edges

## Surprising Connections (you probably didn't know these)
- `Ground rules (from the brief, do not relitigate without asking)` --references--> `corpactions()`  [INFERRED]
  CLAUDE.md → backend/src/stk/cli/commands/ingest.py
- `Cost config scaffold` --references--> `RateSchedule`  [INFERRED]
  docs/BUILD_PLAN.md → backend/src/stk/config/costs.py
- `Verification` --references--> `ContentValidationError`  [INFERRED]
  docs/BUILD_PLAN.md → backend/src/stk/core/errors.py
- `Daily EOD prices (primary source): `sec_bhavdata_full`` --references--> `NseSecBhavdataProvider`  [INFERRED]
  docs/data-sources.md → backend/src/stk/providers/nse/prices.py
- `Current status (update this section as phases complete)` --references--> `DataNotPublished`  [INFERRED]
  CLAUDE.md → backend/src/stk/core/errors.py

## Import Cycles
- None detected.

## Communities (116 total, 31 thin omitted)

### Community 0 - "doctor.py"
Cohesion: 0.06
Nodes (46): _check_endpoints(), doctor(), _previous_weekday(), command, date, `stk doctor` -- ingest health check. Thin by design: every actual check lives…, Step back to the nearest weekday. Holidays are not filtered -- a holiday simply…, Report on ingest health. Exits non-zero if anything looks wrong. (+38 more)

### Community 1 - "assert_bars_sane"
Cohesion: 0.15
Nodes (11): assert_bars_sane(), _assert_turnover_plausible(), Cheap, fast invariant checks over a batch of parsed bars. Deliberately does NOT…, Turnover should be within a generous 3x band of volume*vwap when vwap is…, _bar(), Regression tests for a real bug found via live backfill testing: NSE's own…, Even if only some rows are wrong, the whole file must be rejected., Regression test: a real live-ingest failure. Thin government securities… (+3 more)

### Community 2 - "backfill_nse_prices"
Cohesion: 0.13
Nodes (18): backfill_nse_prices(), Path, Ingest every weekday of NSE prices in [start, end] (inclusive), sequentially.…, _bse_fixture_for_date(), _bse_legacy_fixture(), _fixture_for_date(), _mock_bse_date(), _mock_bse_legacy_date() (+10 more)

### Community 3 - "liquidity.py"
Cohesion: 0.08
Nodes (29): LiquidityConfig, BaseModel, Loader for config/universe.yaml -- liquidity thresholds and the…, UniverseConfig, is_liquid(), is_tradeable_intraday(), LiquidityMetrics, LiquidityThresholds (+21 more)

### Community 4 - "validate_json_response"
Cohesion: 0.12
Nodes (16): Response, Validate a response that is expected to be a plain CSV file.…, Validate a response that is expected to be JSON., validate_csv_response(), validate_json_response(), Response, Tests for the content-type/magic-byte guard against the BSE 'silent 200'…, The exact BSE failure: 200 OK, HTML body -- must raise, not parse. (+8 more)

### Community 5 - "time.py"
Cohesion: 0.06
Nodes (33): format_ddmmyy_compact(), format_ddmmyyyy_compact(), is_market_hours(), is_weekend(), now_ist(), parse_ddmmmyyyy(), parse_ddmmyyyy_compact(), previous_calendar_day() (+25 more)

### Community 6 - "read_manifest"
Cohesion: 0.16
Nodes (10): The manifest for one partition, or None if none was written., read_manifest(), partition_path(), fixture, The _manifests sidecar is what makes a truncated or hand-edited partition…, Adding a second date to the same year partition must update both row_count and…, Re-ingesting a date with FEWER rows must shrink the recorded count, not leave…, A manifest that cannot name its own partition is unusable -- fail loudly rather… (+2 more)

### Community 7 - "Project brief for Claude Code — Indian stock suggester + virtual playground"
Cohesion: 0.14
Nodes (14): 10. Screens (designs come from Claude Design), 11. Build phases (do them in order; stop and check in with me after each), 12. How to work with me, 1. What the app does, 2. Hard constraints, 3. Stack, 4. Data layer, 5. Strategies — four horizons (+6 more)

### Community 8 - "RawArtifact"
Cohesion: 0.10
Nodes (21): ContentValidationError, A response passed HTTP status but failed content-type/magic-byte checks. This…, format_yyyymmdd(), Format a date as 'YYYYMMDD' for UDiFF filename construction., parse_udiff(), Parse an NSE or BSE UDiFF bhavcopy CSV into canonical bars. UDiFF carries ISIN…, CanonicalBar, BaseModel (+13 more)

### Community 9 - "connect"
Cohesion: 0.09
Nodes (26): connect(), _discover_migrations(), migrate(), Connection, Path, Open a connection with the app's standard pragmas applied., Explicit transaction context manager (conn is opened in autocommit mode)., Return (sequence_number, name, path) for every migrations/*.sql file, sorted. (+18 more)

### Community 10 - "build_factor_rows"
Cohesion: 0.12
Nodes (24): ActionFactor, build_factor_rows(), FactorRow, factors_for_bar(), date, Compose per-action factors into a cumulative back-adjustment timeline. For each…, The cumulative factors applying to one bar, given that symbol's timeline (any…, One price/volume-affecting action, already deduped and resolved. (+16 more)

### Community 11 - "duck.py"
Cohesion: 0.07
Nodes (37): get_logger(), Structured logging setup. JSON output in production (so the systemd journal /…, attach_dimensions(), _attach_via_arrow(), connect(), DimensionMode, DuckSession, _load_named_queries() (+29 more)

### Community 12 - "DataNotPublished"
Cohesion: 0.10
Nodes (24): DataNotPublished, ProviderUnavailable, Transport-level failure: timeout, connection refused, DNS, 5xx., The source has not yet published data for the requested date. Distinct from…, CalendarProvider, HolidayRecord, One raw holiday row. Callers MUST intersect with weekdays -- NSE's holiday-…, Source of the trading-holiday calendar. Fetch and parse are separate, exactly… (+16 more)

### Community 13 - "test_adjustments_ingest.py"
Cohesion: 0.16
Nodes (15): _adjusted(), _insert_action(), date, Path, Integration tests for the adjusted-bars rebuild. Builds bars_daily and…, Rupees traded on the day is a historical fact, and since price_factor *…, The derived step must never touch the source of truth., NSE republishing an action with a corrected field creates a SECOND… (+7 more)

### Community 14 - "datetime"
Cohesion: 0.10
Nodes (29): Normalisation of raw provider text into CanonicalBar rows. Every source format…, Persistence of raw fetched bytes, content-addressed for idempotency. Every…, BSE legacy bhavcopy price provider (2010 through 2024-07-05). Confirmed by…, NSE legacy bhavcopy price provider (2010 through ~2019-10-01). Confirmed by the…, NSE sec_bhavdata_full price provider. This is the PRIMARY historical price…, collections_abc, datetime, httpx (+21 more)

### Community 15 - "TestFetchHistory"
Cohesion: 0.29
Nodes (5): DataFrame, _frame(), Yahoo reports no rupee turnover. close*volume is derived and must never be…, An empty result means a wrong ticker, a delisted name, or a rate limit -- never…, TestFetchHistory

### Community 16 - "ParseError"
Cohesion: 0.15
Nodes (10): ParseError, A response was structurally valid but semantically un-parseable. Used by the…, parse_ind_close_all(), Parse NSE's ind_close_all_DDMMYYYY.csv into canonical index bars. Two…, 18775.3 crore = 1,87,753,000,000 rupees. The word "crore" must never survive…, NSE's file carries rows like "Nifty50 Dividend Points" that have a real close…, A row with no closing value is not a price bar at all., TestMalformedInput (+2 more)

### Community 17 - "base.py"
Cohesion: 0.08
Nodes (29): ABC, Exception hierarchy for the ingest/provider stack. The rule this hierarchy…, Post-ingest sanity assertions. Run after every parse, before a partition write…, CorporateActionsProvider, Interval, PriceBand, Provider adapter interfaces. Every external data source (NSE, BSE, yfinance,…, A daily price-band record (NSE sec_list.csv). (+21 more)

### Community 18 - "job_run"
Cohesion: 0.15
Nodes (11): job_run(), _next_attempt(), Connection, date, The next attempt number for (job_name, business_date), so that repeated…, Record one job_runs row for the duration of the ``with`` block. Three possible…, Regression case: doctor's original query flagged ANY failed row, so a transient…, TestLatestAttemptOnlyLogic (+3 more)

### Community 19 - "ingest.py"
Cohesion: 0.12
Nodes (29): adjustments(), calendar(), corpactions(), daily(), fundamentals(), indices(), liquidity(), master() (+21 more)

### Community 20 - "PriceProvider"
Cohesion: 0.22
Nodes (6): PriceProvider, date, Source of OHLCV bars for a single trading day (full-market) or, optionally, a…, Download the full-market EOD file for one date. Raises: ProviderUnavailable:…, Per-symbol history. Optional -- full-market-file providers (bhavcopy-based)…, Corporate actions since ``since`` (or all available if None).

### Community 21 - "ingest/indices.py"
Cohesion: 0.20
Nodes (11): Index (benchmark) ingest. Same shape as ingest.daily's price path -- fetch,…, Parquet path conventions. Partitioned by exchange then year:…, Canonical Arrow schema for daily bars. NSE UDiFF, BSE UDiFF and…, Atomic, idempotent parquet partition writes. This is the load-bearing…, hashlib, pyarrow, data_dirs(), fixture (+3 more)

### Community 22 - "engine.py"
Cohesion: 0.17
Nodes (9): Trading-calendar ingest: populating `trading_calendar` from NSE, and from what…, JobRun bookkeeping: a context manager that records start/success/ skip/failure…, SQLite connection factory, pragmas, and the forward-only migration runner. No…, contextlib, sqlite3, Integration tests for `stk doctor`'s health checks, run against the functions…, Tests for JobRun bookkeeping. Includes a regression test for a real bug caught…, Integration tests for the SQLite migration runner. (+1 more)

### Community 23 - "_mock"
Cohesion: 0.13
Nodes (15): ingest_nse_prices_for_date(), Ingest one day of NSE prices end-to-end: fetch, validate, persist raw, parse,…, bars_daily_partition(), 2010-01-04 is before the UDiFF cutover, so get_bse_price_provider_for_date must…, The BSE-specific failure mode: a non-trading day returns HTTP 200 with an HTML…, TestIngestBsePricesForDate, The wiring proof: on a date the calendar says did not trade, the nightly ingest…, Tri-state, not boolean: no calendar row means UNKNOWN, and unknown must be… (+7 more)

### Community 24 - "_holiday_payload"
Cohesion: 0.26
Nodes (7): _holiday_payload(), _mock_holidays(), BSE has no separate feed wired up. Using NSE's calendar is a reasonable…, All-or-nothing: a partially-known range must not quietly return its known…, TestIngestCalendarYear, run_and_count(), TestTradingDaysBetween

### Community 25 - "ConfigError"
Cohesion: 0.18
Nodes (11): _DatedRate, _DatedSeries, BaseModel, date, RateSchedule, A rate that takes effect from a given date, until superseded., A chronologically sorted list of ``_DatedRate``, queryable by date., Return the rate in effect on ``as_of_date``. If ``as_of_date`` predates the… (+3 more)

### Community 26 - "_write"
Cohesion: 0.14
Nodes (9): _bars(), date, Path, Table, exchange/year come from the directory names, not the file -- the liquidity and…, A fresh checkout has no bars_daily_adjusted. Querying it must return zero rows…, TestNamedQueries, TestViewRegistration (+1 more)

### Community 27 - "test_costs.py"
Cohesion: 0.08
Nodes (11): Tests for the dated cost-rate schedule (config/costs.yaml + RateSchedule).…, DP charge: flat, per-scrip, per-day, sell leg only -- dominates cost on small…, NSE exchange transaction charge changed 2024-10-01 and again 2026-03-01., NSE IPFT dropped from Rs 10/crore to Rs 0.01/crore on 2026-03-01., STT: delivery both legs; intraday sell-leg only., GST must apply to brokerage/exchange_txn/sebi fee/IPFT and NOT to STT or stamp…, TestDpCharge, TestExchangeTxnBoundary (+3 more)

### Community 28 - "daily.py"
Cohesion: 0.10
Nodes (26): Current calendar date in IST (not the server's local date)., today_ist(), is_trading_day(), Whether the calendar knows this date traded. Returns None for "the calendar has…, _bars_to_table(), _enrich_identity(), _identity_map(), ingest_bse_prices_for_date() (+18 more)

### Community 29 - "format_inr"
Cohesion: 0.14
Nodes (13): bps(), format_inr(), Decimal, Decimal-safe money arithmetic and Indian-style (lakh/crore) formatting. Every…, Convert any numeric input to a Decimal rounded to paise., Express ``value`` as basis points of ``basis``. Returns 0 if basis is 0., Format a rupee amount with Indian digit grouping (lakh/crore).…, to_money() (+5 more)

### Community 30 - "0001_init.sql"
Cohesion: 0.17
Nodes (20): corporate_actions, fundamentals_snapshots, ix_ca_exdate, ix_ca_parse_status, ix_ca_security_ex, ix_fund_provider, ix_fund_sec_period, ix_job_lookup (+12 more)

### Community 31 - "ingest/corpactions.py"
Cohesion: 0.06
Nodes (51): ActionType, _ClauseResult, _parse_bonus(), _parse_clause(), _parse_decimal(), _parse_dividend(), _parse_face_value_split(), _parse_rights() (+43 more)

### Community 32 - "NseFundamentalsProvider"
Cohesion: 0.08
Nodes (31): FundamentalsIngestResult, Connection, Fundamentals ingest: fetch a security's filings and upsert into…, _resolve_security_id(), _upsert_snapshot(), FilingRef, FundamentalsProvider, FundamentalsSnapshotIn (+23 more)

### Community 33 - "NotSupportedError"
Cohesion: 0.08
Nodes (21): NotSupportedError, A provider does not implement an optional capability., ProviderCapabilities, Declares what a provider can actually do, so callers can degrade gracefully…, BseUdiffProvider, date, PriceProvider backed by BSE's UDiFF daily bhavcopy., date (+13 more)

### Community 34 - "NseSecBhavdataProvider"
Cohesion: 0.14
Nodes (12): NseSecBhavdataProvider, date, PriceProvider backed by NSE's sec_bhavdata_full daily file., _csv_response(), live, Response, Defence-in-depth: even though NSE's archive host has not been observed doing…, Real network smoke test -- excluded from the default run. Run explicitly with… (+4 more)

### Community 35 - "nse/archives.py"
Cohesion: 0.18
Nodes (14): Shared HTTP client factory and response validation. This module is the single…, Validate a response that is expected to be a zip file. Checks status, then…, validate_zip_response(), _do_get(), fetch_csv_file(), fetch_zip_file(), date, Response (+6 more)

### Community 36 - "NseLegacyBhavcopyProvider"
Cohesion: 0.19
Nodes (8): NseLegacyBhavcopyProvider, PriceProvider backed by NSE's legacy per-date cm*bhav.csv.zip archive., live, TestCapabilities, TestFetchEod, TestLiveEndpoint, TestParseEod, _zip_bytes()

### Community 37 - "ingest/master.py"
Cohesion: 0.25
Nodes (7): MasterIngestResult, Connection, Security-master ingest: ISIN-keyed merge of NSE + BSE listings into…, Returns True if this upsert closed out a rename (a different symbol was…, _upsert_listing_and_detect_rename(), _upsert_security(), collections

### Community 38 - "ingest/backfill.py"
Cohesion: 0.13
Nodes (16): prices(), command, `stk backfill` -- historical price backfill., Backfill daily prices over a date range for one exchange. NSE source (legacy vs…, ProviderError, Exception, Base class for all application-raised errors., Base class for provider-adapter failures. (+8 more)

### Community 39 - "ingest_calendar_from_bars"
Cohesion: 0.18
Nodes (10): CalendarIngestResult, ingest_calendar_from_bars(), Path, Derive calendar rows from the dates actually present in bars_daily. Covers only…, date, Path, The precedence rule. NSE says 26-Jan-2026 was a holiday; the lake has no bars…, The reverse direction IS allowed -- learning NSE's real answer for a date we… (+2 more)

### Community 40 - "BseLegacyBhavcopyProvider"
Cohesion: 0.09
Nodes (16): BseLegacyBhavcopyProvider, date, PriceProvider backed by BSE's legacy per-date EQ*.CSV.ZIP archive., get_price_provider(), Construct a PriceProvider by its config name (see providers.prices in…, live, TestCapabilities, TestFetchEod (+8 more)

### Community 41 - "costs.py"
Cohesion: 0.17
Nodes (16): Dated cost-rate schedule loader. Loads config/costs.yaml -- a history of…, _deep_merge(), find_config_dir(), load_named_yaml(), load_yaml_config(), Any, Path, YAML config loading and layering. Precedence, highest wins: 1. Process env /… (+8 more)

### Community 42 - "compute_liquidity_for_date"
Cohesion: 0.25
Nodes (12): compute_liquidity_for_date(), Compute and persist one exchange's liquidity features for one date. Idempotent…, liquidity_daily_partition(), _make_universe_config(), date, Path, Integration tests for the liquidity feature/universe computation. Builds…, No security master data exists yet -- documented known limitation in… (+4 more)

### Community 43 - "adjustments.py"
Cohesion: 0.17
Nodes (16): _adjust_bar(), AdjustmentResult, _factor_table(), Decimal, Path, Table, Corporate-action back-adjustment: factor timelines and the derived…, Rebuild adjustment_factors and bars_daily_adjusted for one exchange. Network-… (+8 more)

### Community 44 - "TestParseHolidays"
Cohesion: 0.23
Nodes (5): _artifact(), CBM (corporate bond market) is the first key in NSE's payload and is…, NSE lists holidays falling on a Saturday/Sunday. The PROVIDER must not drop…, An out-of-range year (2010, 2027) returns HTTP 200 with no CM rows. Returning…, TestParseHolidays

### Community 45 - "main.py"
Cohesion: 0.18
Nodes (10): migrate_cmd(), command, `stk db` -- database management commands., Apply all pending SQLite migrations., _init(), `stk` -- the project's single CLI entry point. Subcommands are grouped by…, configure_logging(), Configure structlog + stdlib logging. Call once at process startup. (+2 more)

### Community 46 - "settings.py"
Cohesion: 0.31
Nodes (9): AppMeta, HttpConfig, HttpEndpointConfig, IngestConfig, ProvidersConfig, BaseModel, Typed application settings. Loads config/defaults.yaml + config/env/{env}.yaml…, YFinanceHttpConfig (+1 more)

### Community 47 - "ingest_security_master"
Cohesion: 0.33
Nodes (9): ingest_security_master(), Path, Fetch and merge the NSE + BSE security masters into securities/…, _bse_row(), _mock_bse(), _mock_nse(), _nse_row(), Integration tests for ingest_security_master's ISIN-keyed merge. Mocks both… (+1 more)

### Community 48 - "_YamlSettingsSource"
Cohesion: 0.32
Nodes (5): Any, pydantic-settings source that loads config/defaults.yaml + env overlay., _YamlSettingsSource, BaseSettings, PydanticBaseSettingsSource

### Community 49 - "ingest_calendar_year"
Cohesion: 0.13
Nodes (16): ingest_calendar_year(), Connection, date, Populate one calendar year for one exchange from NSE's holiday master. Writes a…, Known trading days in [start, end], or None if the calendar does not fully…, Insert or improve one calendar row, respecting source precedence., trading_days_between(), _upsert_day() (+8 more)

### Community 50 - "parse_legacy_bhavcopy"
Cohesion: 0.29
Nodes (5): parse_legacy_bhavcopy(), Parse NSE's legacy cm{DDMONYYYY}bhav.csv format (2010 through ~2019-10-01,…, The real 2010 file uses '4-JAN-2010', not '04-JAN-2010'., This format predates delivery reporting -- delivery fields must be None, not…, TestParseLegacyBhavcopy

### Community 51 - "IngestAssertionError"
Cohesion: 0.10
Nodes (23): IngestAssertionError, A post-ingest sanity check failed (row counts, OHLC invariants, ...)., assert_bars_match_requested_date(), assert_index_bars_match_requested_date(), date, Same guard as assert_bars_match_requested_date, for index bars. ADR 0003…, Assert every parsed bar's date matches the date we actually requested from the…, get_nse_price_provider_for_date() (+15 more)

### Community 52 - "get_rate_schedule"
Cohesion: 0.40
Nodes (5): get_rate_schedule(), Path, Return the process-wide RateSchedule singleton, loading config/costs.yaml on…, fixture, schedule()

### Community 53 - "ingest_indices_for_date"
Cohesion: 0.20
Nodes (9): IndicesIngestResult, ingest_indices_for_date(), date, Path, Ingest one day of NSE index closes end-to-end. Idempotent., indices_daily_partition(), ADR 0003's mislabeled-content trap, applied to the index archive: writing this…, TestIngestIndicesForDate (+1 more)

### Community 54 - "CLAUDE.md"
Cohesion: 0.29
Nodes (5): graphify, Ground rules (from the brief, do not relitigate without asking), Repo layout, What this is, Working here

### Community 55 - "_make_bars"
Cohesion: 0.24
Nodes (8): _make_bars(), date, Table, A stronger idempotency check: not just the same row count, but the same file…, Re-writing one date must not disturb other dates already in the same year…, The core property: re-running ingest for an already-ingested date must not…, TestUpsertPartition, _upsert()

### Community 56 - "TestLiveEndpoint"
Cohesion: 0.29
Nodes (4): live, Documented shape checks. Run deliberately: `pytest -m live`., The finding that justified using this endpoint for the whole backfill range…, TestLiveEndpoint

### Community 58 - "manifest_path"
Cohesion: 0.40
Nodes (4): manifest_path(), Where the row-count + sha256 sidecar for one partition lives. ``exchange`` is…, indices_daily is year-partitioned only -- the exchange= level is absent rather…, TestManifestPath

### Community 59 - "ingest_corporate_actions"
Cohesion: 0.27
Nodes (7): CorpActionIngestResult, ingest_corporate_actions(), date, Path, Fetch corporate actions, parse subjects, and upsert into corporate_actions. One…, _row(), TestIngestCorporateActions

### Community 61 - "code_version"
Cohesion: 0.40
Nodes (4): code_version(), The running code's version, for attributing written data to a commit. Both…, Short git SHA of HEAD, or "unknown" outside a git checkout. Never raises: an…, subprocess

### Community 62 - "parse_sec_bhavdata_full"
Cohesion: 0.24
Nodes (5): parse_sec_bhavdata_full(), Parse NSE's sec_bhavdata_full_{DDMMYYYY}.csv into canonical bars. This file…, The real NSE file has a leading space on every header/value after the first…, This is the critical rule: '-' means unreported, not zero., TestParseSecBhavdataFull

### Community 63 - "ingest_fundamentals_for_security"
Cohesion: 0.36
Nodes (5): ingest_fundamentals_for_security(), Path, Fetch one security's recent filings and upsert into fundamentals_snapshots. One…, _insert_security(), TestIngestFundamentalsForSecurity

### Community 65 - "Indian stock suggester + virtual playground — build plan"
Cohesion: 0.15
Nodes (13): Context, Decisions locked this session, Design system (extracted from the handoff), Guiding principles for phases 0–1, Indian stock suggester + virtual playground — build plan, Open items for later phases, Phase 0 — repo, config, VM notes, history spike, Phases 2–8 (outline only) (+5 more)

### Community 84 - "upsert_partition"
Cohesion: 0.24
Nodes (11): Path, Schema, Table, Overwrite-by-partition write. Returns the row count of the resulting file.…, Read a partition file, or return an empty table matching ``schema`` if absent., Streaming sha256 of a file on disk., Write the row-count + sha256 sidecar for a just-written partition. The sha256…, read_partition() (+3 more)

### Community 85 - "MasterRecord"
Cohesion: 0.25
Nodes (7): MasterRecord, One row of a security-master snapshot (NSE EQUITY_L.csv / BSE ListofScripData)., Full active-listing snapshot for one exchange., NseSecurityMasterProvider, SecurityMasterProvider backed by NSE's EQUITY_L.csv / sec_list.csv., TestFetchMaster, TestFetchPriceBands

### Community 86 - "bse/archives.py"
Cohesion: 0.36
Nodes (9): fetch_bse_csv_file(), fetch_bse_zip_file(), _get_and_check_shell(), date, Response, Fetch helper for www.bseindia.com CSV downloads. Verified 2026-09-18 by direct…, GET the URL and raise DataNotPublished if the response is BSE's SPA shell --…, GET and content-validate a zip file from www.bseindia.com. Used by the legacy… (+1 more)

### Community 87 - "NseIndicesProvider"
Cohesion: 0.24
Nodes (8): NseIndicesProvider, Fetches NSE's daily all-index close file., get_indices_provider(), Construct the index (benchmark) provider by name. Not behind an ABC yet: there…, live, Run deliberately: `pytest -m live`., Unlike BSE, NSE's index archive gives a real 404 rather than a 200 with an SPA…, TestLiveEndpoint

### Community 88 - "_decimal_or_none"
Cohesion: 0.25
Nodes (9): _decimal_or_none(), _int_or_none(), parse_bse_legacy_bhavcopy(), _parse_iso_date(), date, Decimal, Parse BSE's legacy EQ{DDMMYY}_CSV.ZIP bhavcopy (2010 through 2024-07-05,…, UDiFF dates are ISO 'YYYY-MM-DD' -- explicit format, never inferred. (+1 more)

### Community 89 - "IndexBar"
Cohesion: 0.25
Nodes (7): assert_index_bars_sane(), Post-parse sanity checks for index bars. Deliberately narrower than…, Table, _to_table(), IndexBar, BaseModel, One index's OHLC for one date, canonicalised.

### Community 90 - "get_security_master_provider"
Cohesion: 0.32
Nodes (5): _fetch_all_records(), Fetch every exchange's master snapshot, tolerating one exchange's fetch failing…, get_security_master_provider(), Construct a SecurityMasterProvider by its config name (see…, TestGetSecurityMasterProvider

### Community 91 - "BseSecurityMasterProvider"
Cohesion: 0.32
Nodes (5): BseSecurityMasterProvider, _decimal_or_none(), Decimal, SecurityMasterProvider backed by BSE's ListofScripData JSON API., TestFetchMaster

### Community 92 - "conftest.py"
Cohesion: 0.36
Nodes (7): _isolated_config_dir(), fixture, Path, Shared pytest fixtures., Point STK_CONFIG_DIR at the real repo config/ for every test. Tests run from…, tmp_db_path(), tmp_parquet_root()

### Community 93 - "load_actions"
Cohesion: 0.33
Nodes (7): load_actions(), _LoadedActions, BaseModel, Connection, Every symbol this security has used on this exchange. Includes historical names…, Load price-affecting corporate actions for one exchange, deduped. Returns the…, _symbols_for_security()

### Community 94 - "JobSkipped"
Cohesion: 0.38
Nodes (5): JobSkipped, Exception, Raise inside a job_run() block to record status='skipped_holiday' and exit the…, A skip decided partway through a job body (e.g. after an initial fetch attempt)…, TestJobSkipped

### Community 95 - "canonical_index_code"
Cohesion: 0.33
Nodes (5): canonical_index_code(), Stable identity for an index whose printed name changes over time. Returns None…, parametrize, The finding this mapping exists for: NSE's benchmark is printed as three…, TestCanonicalIndexCode

### Community 96 - "session.py"
Cohesion: 0.29
Nodes (6): build_session(), Throttled, browser-impersonating session for Yahoo Finance. Two defences, both…, Block until at least min_interval_ms has passed since the last call. Process-…, A curl_cffi session impersonating Chrome. Returns ``object`` rather than a…, throttle(), threading

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
Cohesion: 0.33
Nodes (5): Blocking behaviour summary, BSE, Data sources — verified endpoints, Security master, Things still to verify (do not treat as settled)

### Community 101 - "stockAnalyser"
Cohesion: 0.33
Nodes (6): A note on scope, Common commands, Layout, Setup, Status, stockAnalyser

### Community 102 - ".fetch_indices"
Cohesion: 0.67
Nodes (3): index_archive_url(), date, Fetch one date's index file, validated and ready to persist.

### Community 104 - "Phase 1 — data pipeline + store"
Cohesion: 0.50
Nodes (4): Cost config scaffold, Parquet layout, Phase 1 — data pipeline + store, SQLite schema (phase 1 tables)

### Community 106 - "build_client"
Cohesion: 0.67
Nodes (3): build_client(), Construct an httpx.Client with sane defaults for exchange fetches., Client

### Community 109 - "enabled"
Cohesion: 0.67
Nodes (3): enabled(), fixture, Turn the feature flag on for tests that need the provider built. get_settings()…

## Knowledge Gaps
- **51 isolated node(s):** `stk`, `raw_artifacts`, `trading_calendar`, `stockanalyser`, `What this is` (+46 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 596 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **31 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `connect()` connect `connect` to `doctor.py`, `backfill_nse_prices`, `liquidity.py`, `test_adjustments_ingest.py`, `ingest/indices.py`, `engine.py`, `_mock`, `_holiday_payload`, `daily.py`, `ingest/corpactions.py`, `NseFundamentalsProvider`, `ingest/master.py`, `ingest_calendar_from_bars`, `compute_liquidity_for_date`, `adjustments.py`, `ingest_security_master`, `ingest_calendar_year`, `ingest_indices_for_date`, `ingest_corporate_actions`, `ingest_fundamentals_for_security`, `TestDimensions`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `DataNotPublished` connect `DataNotPublished` to `doctor.py`, `NotSupportedError`, `NseSecBhavdataProvider`, `nse/archives.py`, `NseLegacyBhavcopyProvider`, `ingest/backfill.py`, `BseLegacyBhavcopyProvider`, `TestParseHolidays`, `TestFetchHistory`, `base.py`, `ingest.py`, `ingest/indices.py`, `ingest_indices_for_date`, `bse/archives.py`, `NseIndicesProvider`, `TestLiveEndpoint`, `daily.py`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `Current status (update this section as phases complete)` connect `ingest.py` to `NseFundamentalsProvider`, `NotSupportedError`, `liquidity.py`, `RawArtifact`, `BseSecurityMasterProvider`, `adjustments.py`, `DataNotPublished`, `ingest_security_master`, `IngestAssertionError`, `upsert_partition`, `MasterRecord`, `CLAUDE.md`, `ConfigError`, `ingest_corporate_actions`, `daily.py`, `ingest_fundamentals_for_security`, `ingest/corpactions.py`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `RawArtifact` (e.g. with `persist_artifact()` and `fetch_bse_csv_file()`) actually correct?**
  _`RawArtifact` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `stk`, `raw_artifacts`, `trading_calendar` to the rest of the system?**
  _51 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `doctor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06116700201207243 - nodes in this community are weakly interconnected._
- **Should `backfill_nse_prices` be split into smaller, more focused modules?**
  _Cohesion score 0.12535612535612536 - nodes in this community are weakly interconnected._