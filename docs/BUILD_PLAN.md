# Indian stock suggester + virtual playground — build plan

> Snapshot of the session that scoped phase 0 and phase 1 (dated 2026-09-18, before any code existed). Kept as-is for the reasoning and research findings it records; it does **not** track day-to-day progress. For current status, see `CLAUDE.md`'s "Current status" section; for the phase-0 history spike's actual (better-than-planned) result, see `docs/adr/0003-historical-price-source.md`, which supersedes this document's spike section.

## Context

Greenfield. `/home/razal/Projects/Personal/stockAnalyser` is empty. Two inputs exist: `claude-code-prompt.md` (the project brief) and `Stock Terminal Standalone.html` (a Claude Design handoff — a bundled artifact containing the full UI spec for all five screens).

We are building a **single-user** web app that scans NSE+BSE after market close, suggests stocks across four horizons using strategies that must pass a rigorous backtest gate, tracks each pick's live return, and lets Razal paper-trade against ~15-min-delayed quotes. AI (Claude API) is used sparingly — once daily to review picks, weekly to propose strategies.

The brief is complete and decided. This plan turns it into an executable sequence, **corrects three factual assumptions in it** using endpoints verified by live `curl` on 2026-09-18, and pins phase 0 + phase 1 in enough detail to start.

**Per the brief: we execute phase 0 and phase 1 only. The folder structure and schemas below are what need your explicit OK before large code lands.**

---

## Decisions locked this session

| Question | Decision |
|---|---|
| Front-end framework (brief marked OPEN) | **React + Vite + TypeScript**, static build served by Caddy; TanStack Query for server state |
| Fundamentals source | **NSE official JSON** (authoritative, forward-capture) + **yfinance** (approximate history), two providers behind one interface |
| Deployment timing | **No VM yet** — dev locally through phase 7, write Oracle VM notes in phase 0, deploy in phase 8 |
| Price history target | **2010-onward (15+ years)**, with a time-boxed spike to source pre-Jul-2024 data |
| Python tooling | **uv** workspace (not currently installed — phase 0 installs it) |
| Phase 1 surface | **CLI only.** No FastAPI app until phase 4, matching the brief's sequencing |
| DataFrame library | **pandas only.** DuckDB does the heavy lifting; add polars only if profiling demands it |

---

## Research findings that change the brief

**1. The NSE bhavcopy URL everyone has in their head is dead.** The legacy `/content/historical/EQUITIES/{YYYY}/{MON}/cm{DDMONYYYY}bhav.csv.zip` path 404s — retired by NSE circular 62424, effective 08-Jul-2024. Replacement:

```
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip
```

34 columns, ISO dates, carries **ISIN** (the old format did not). Critically, **it only exists from Jul-2024**, so it cannot be the deep-history source. The older `sec_bhavdata_full_{DDMMYYYY}.csv` predates it, appears continuous, and carries **OHLCV + delivery quantity/percentage in one request** — but is symbol-keyed with no ISIN.

→ **Consequence:** `sec_bhavdata_full` is the primary daily source (delivery % is required by the short-term seed strategies anyway); UDiFF is the ISIN-bearing companion. Joined on symbol+date.

**2. BSE fails silently, not loudly.** Legacy BSE bhavcopy URLs return **HTTP 200 with `content-type: text/html`** and 14KB of Angular SPA shell — not a 404. Code checking `status_code == 200` then unzipping breaks confusingly: exactly the failure mode the brief says to avoid. Working URL is an **uncompressed** CSV:

```
https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{YYYYMMDD}_F_0000.CSV
```

**3. Fundamentals need neither XBRL parsing nor scraping Screener.** NSE publishes quarterly results, shareholding pattern and **promoter pledge** as structured JSON under `www.nseindia.com/api/corporates-*`. Official, free, no ToS ambiguity, and the filing broadcast date is a genuine point-in-time knowledge date — which makes the brief's reporting-lag rule *exact* going forward rather than an assumption. Screener.in is dropped (its `/terms/` 404s and robots.txt disallows `/company/source/quarter/*`, precisely the endpoint every scraper library uses).

**Blocking behaviour is narrower than folklore:** `nsearchives.nseindia.com` static files need only a **non-default User-Agent** (no cookies, no Referer). `www.nseindia.com/api/*` needs a **cookie handshake** (GET the HTML page with a browser UA + cookie jar, then call with a `Referer`). `api.bseindia.com` needs `Referer: https://www.bseindia.com/`.

---

## Guiding principles for phases 0–1

1. **Raw bytes are sacred.** Every HTTP response that produces data is persisted verbatim under `data/raw/` before parsing. Re-parsing never needs the network — parser bugs become cheap to fix and fixtures become free.
2. **Two storage tiers, no overlap.** Parquet = immutable-ish time series. SQLite = mutable app state + small reference dimensions. A row never lives in both.
3. **Loud over lossy.** Unparsed corporate action, unexpected content-type, missing trading day → non-zero exit and a recorded degraded status. Nothing silently skipped.
4. **Phase 1 ships a substrate, not features.** Deliverable is `stk backfill`, `stk ingest daily`, `stk doctor`, and a tested DuckDB query layer.

---

## Repo structure

```
stockAnalyser/
├── pyproject.toml           # uv workspace root; shared ruff/mypy/pytest config
├── uv.lock                  # committed
├── .python-version          # 3.12
├── .env.example             # documented env vars, no secrets
├── Makefile                 # make dev / test / lint / ingest
│
├── backend/pyproject.toml   # package "stk"
├── backend/src/stk/
│   ├── config/              # settings.py (pydantic-settings), costs.py, loader.py
│   ├── core/                # time.py (IST), money.py (Decimal, lakh/crore), logging.py,
│   │                        #   errors.py, http.py  <- content-type + magic-byte guard
│   ├── providers/           # ALL external adapters behind ABCs
│   │   ├── base.py          # the five ABCs + DTOs + ProviderCapabilities
│   │   ├── registry.py      # name -> adapter, constructed from config
│   │   ├── nse/             # session.py (cookie priming), archives.py (UA-only),
│   │   │                    #   prices.py, master.py, calendar.py, corpactions.py, filings.py
│   │   ├── bse/             # prices.py (content-type guard), master.py
│   │   ├── yfinance/        # prices.py, fundamentals.py (is_approximate=True)
│   │   └── broker/          # PHASE-8 placeholder: Kite/Upstox drops in here
│   ├── ingest/              # daily.py, backfill.py, raw_store.py, normalise.py,
│   │                        #   merge.py (ISIN dedup), corpactions.py (free-text parser),
│   │                        #   adjustments.py, liquidity.py, jobs.py
│   ├── store/
│   │   ├── parquet/         # layout.py, schema.py (pyarrow), writer.py (atomic rewrite)
│   │   ├── duck.py          # DuckDB connection factory + view registration
│   │   ├── queries/         # named SQL: prices.sql, screen.sql, coverage.sql
│   │   └── db/              # engine.py (WAL pragmas), migrations/*.sql, models.py, repos/
│   ├── domain/              # PURE functions, heavily tested: costs.py, calendar.py, universe.py
│   └── cli/                 # typer app `stk`: ingest, backfill, doctor, db, spike
│
├── web/                     # PHASE 4: React + Vite + TS. Empty placeholder now.
├── config/                  # committed, non-secret
│   ├── defaults.yaml        # base config
│   ├── env/{local,prod}.yaml
│   ├── costs.yaml           # DATED rate schedule (STT, stamp, txn, GST, DP)
│   ├── universe.yaml        # liquidity thresholds, excluded series/groups
│   └── horizons.yaml        # the four horizons' holding windows
├── data/                    # gitignored: raw/, parquet/, app.db, cache/
├── tests/                   # unit/, integration/, fixtures/
├── docs/                    # PROJECT_BRIEF.md, adr/, data-sources.md, runbook.md,
│                            #   ORACLE_VM_SETUP.md
├── scripts/spikes/          # history_probe.py — never imported by stk
└── deploy/                  # phase 8: systemd units, timers, Caddy config
```

A **uv workspace** with `backend/` as a member (not a flat root package) so phase 5+ can add a second Python member (e.g. `backtest-worker`) without restructuring. Pin `requires-python = ">=3.12,<3.13"` tight so the ARM VM resolves identically; commit `uv.lock`.

---

## Phase 0 — repo, config, VM notes, history spike

1. `uv` install; workspace + `backend` member; ruff + mypy (strict on `domain/`, `ingest/`) + pytest; `Makefile`; pre-commit.
2. `config/` files with `pydantic-settings` layering: **process env / `.env`** (secrets only) > **`config/env/{APP_ENV}.yaml`** > **`config/defaults.yaml`**. Env prefix `STK_`, nesting delimiter `__`. Loaded into frozen pydantic models so a typo fails at startup, not at 02:00.
   - **Rule: anything a non-programmer would tune lives in committed YAML. Anything secret lives in `.env`.** Cost rates, liquidity thresholds and horizon windows are configuration data, not secrets.
3. Copy the brief to `docs/PROJECT_BRIEF.md`; write `CLAUDE.md` referencing it; write `docs/data-sources.md` with the verified endpoints above.
4. Write `docs/ORACLE_VM_SETUP.md` — signup tips (expect several attempts), ARM A1 shape, ingress rules, swap, Caddy. **You attempt signup in parallel; we do not block on it.**
5. **Run the history spike (§ below) before writing any ingest code** — its answer determines the primary historical source.

### The pre-Jul-2024 history spike

**Time box: one working day. Hard stop.** `scripts/spikes/history_probe.py`, result written as `docs/adr/0003-historical-price-source.md`. Probe dates: `2010-01-04, 2012-06-15, 2014-11-20, 2016-03-10, 2018-08-22, 2020-03-23` (covid circuit-breaker day), `2021-07-01, 2023-02-15, 2024-06-14, 2024-07-10`.

Attempt in order, each with explicit pass/fail:

1. **`sec_bhavdata_full` direct from nsearchives** (90 min). Success = ≥9/10 dates return valid CSV with `SYMBOL` header and >1,000 rows → **this is the primary source, stop here.** Partial → record the true earliest date, set `ingest.sec_bhavdata_available_from`, continue.
2. **GitHub mirror `chartiny/nse-sec-bhavdata-full`** (60 min). Verify earliest date, byte-identity vs NSE on 3 overlapping dates, update cadence, schema constancy.
3. **Legacy NSE `cm{DDMMMYYYY}bhav.csv.zip`** (45 min). Research says it 404s; verify whether universally or only for recent dates. Has OHLCV but **no delivery data** — strictly a fallback.
4. **BSE pre-UDiFF `EQ_ISINCODE_{DDMMYY}.zip`** (45 min).
5. **yfinance `.NS`** as last resort (45 min). Compare closes against steps 1–3 on 5 overlapping dates; success = ≤0.5% deviation. Record its deficiencies explicitly: no delivery, no rupee turnover, **survivorship bias** (delisted names absent), rate limits.

Remaining 45 min writes the ADR: primary source per date range, fallback, exact earliest reliable date per exchange, whether delivery exists across the range, and the real value for `ingest.backfill_start`. **If nothing reaches 2010, do not fight it** — set the start to the earliest verified date. 2015-onward is still 10 years, enough for everything in phases 2–5.

---

## Phase 1 — data pipeline + store

### Parquet layout

**Partition by `exchange` then `year`. Not month. Sort each file by `(symbol, date)`.**

The numbers: ~2,000 liquid NSE equities × ~250 days = ~500k rows/year; 16 years ≈ 8M rows ≈ **150–200 MB for the entire dataset**. A screen query (last 60 days, all symbols) prunes to 1–2 year partitions. A stock view (all history, one symbol) touches 16 files, but because each is sorted by symbol, row-group min/max statistics let DuckDB skip nearly every row group. Month partitioning would make ~190 tiny files per exchange — 190 file handles and footers for the single-symbol query, with no benefit to the screen query. Year partitioning also means a corporate-action-driven adjustment rebuild rewrites at most 16 files. `row_group_size = 100_000`, statistics on `symbol` and `date`.

```
data/parquet/
├── bars_daily/exchange=NSE/year=2010/data.parquet   # canonical UNADJUSTED
├── bars_daily_adjusted/...                          # DERIVED, rebuilt on CA change
├── adjustment_factors/exchange=NSE/data.parquet
├── indices_daily/year=.../data.parquet
├── features/{indicators_daily,liquidity_daily}/...  # phase 2+
└── _manifests/                                      # row counts + sha256, for doctor
```

**Canonical bar schema** — NSE UDiFF, BSE UDiFF and `sec_bhavdata_full` all normalise into exactly this:

`date` date32 · `exchange` dict · `symbol` · `security_id` int32 (nullable, FK to SQLite) · `isin` nullable · `series` dict · `instrument_type` dict · `open/high/low/close/prev_close/last` double · `vwap` nullable · `volume` int64 · `turnover` double (**rupees always**) · `trades` nullable · `delivery_qty` nullable · `delivery_pct` nullable · `settle_price` nullable · `source` dict · `ingested_at` timestamp

Rules baked into `normalise.py` and unit-tested:
- `-` → **null, never 0** for delivery fields (0 delivery is a real and different value).
- `TURNOVER_LACS × 100_000` at the boundary; the word "lacs" never survives into the canonical layer.
- Explicit format strings for dates (UDiFF ISO, sec_bhavdata `DD-Mon-YYYY`) — never `dateutil` inference.
- `skipinitialspace=True` on every NSE plain CSV, plus a defensive `.strip()` on every header.

**Unadjusted is the single source of truth.** `bars_daily` is never rewritten by a corporate action. `adjustment_factors` derives from SQLite `corporate_actions`; `bars_daily_adjusted` is a materialised rebuild (seconds) whenever a new ex-date lands. **Rule: any number shown to a user for "what did I pay" is unadjusted; any number fed to a signal or chart is adjusted.**

**DuckDB access:** one disposable `data/duck.db` holding only views over `read_parquet(..., hive_partitioning := true)`, with SQLite dimensions joined via `sqlite_scanner` attached READ_ONLY. Keeps one copy of the securities master. Every adjusted-price consumer goes through `store/queries/prices.sql` — never opens a parquet path directly.

### SQLite schema (phase 1 tables)

WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`. Migrations are **plain forward-only numbered `.sql` files** with a ~40-line runner tracking `schema_migrations`. **No Alembic** — the eventual Postgres swap is easier with hand-written SQL, and the schema is small.

```sql
securities(security_id PK, isin UNIQUE NOT NULL, canonical_symbol, company_name,
           primary_exchange CHECK(NSE|BSE), face_value,
           status CHECK(ACTIVE|SUSPENDED|DELISTED), first_seen_on, last_seen_on, updated_at)
  -- one row per real-world company, keyed by ISIN

listings(listing_id PK, security_id FK, exchange, symbol, exchange_token, series,
         listing_date, lot_size, price_band_pct, is_tradeable_intraday, status, source,
         UNIQUE(exchange, symbol, series))
  -- one row per (security, exchange); where symbol collisions live

symbol_history(id PK, security_id FK, exchange, symbol, valid_from, valid_to,
               UNIQUE(exchange, symbol, valid_from))
  -- renames, so historical bars keyed by an old symbol still resolve

corporate_actions(ca_id PK, security_id FK nullable, isin, symbol, exchange,
                  ex_date, record_date, bc_start_date, bc_end_date,
                  subject_raw NOT NULL,          -- the untouched free text
                  action_type,                   -- DIVIDEND|BONUS|SPLIT|RIGHTS|BUYBACK|...
                  dividend_per_share, ratio_numerator, ratio_denominator,
                  face_value_from, face_value_to, price_factor, volume_factor,
                  parse_status CHECK(parsed|ambiguous|unparsed), parser_version,
                  source, source_hash, captured_at, UNIQUE(source, source_hash))

fundamentals_snapshots(snapshot_id PK, security_id FK,
                  provider,                      -- nse_filings | yfinance
                  statement_type, period_type CHECK(Q|H|FY|TTM), period_end,
                  fiscal_year, fiscal_quarter, consolidated, audited,
                  filing_system,                 -- financial_results | integrated_filing
                  broadcast_at,                  -- when NSE published it = PIT truth
                  captured_at,                   -- when WE fetched it
                  is_approximate, is_restated, currency, unit_multiplier,
                  data_json NOT NULL, source_url, source_hash, parser_version,
                  UNIQUE(provider, security_id, statement_type, period_type,
                         period_end, consolidated, source_hash))
  -- NEVER updated in place; a new capture is a new row

job_runs(run_id PK, job_name, business_date,
         status CHECK(running|success|degraded|failed|skipped_holiday),
         started_at, finished_at, rows_in, rows_written, rows_rejected, attempt,
         error_type, error_message, traceback, metrics_json,
         code_version)                           -- git sha, so a reparse is attributable

raw_artifacts(artifact_id PK, source, business_date, url, path, sha256, bytes,
              content_type, http_status, fetched_at,
              validation CHECK(ok|wrong_content_type|magic_mismatch|empty),
              UNIQUE(source, business_date, sha256))
  -- the idempotency backbone

trading_calendar(cal_date PK, exchange, segment, is_trading_day,
                 holiday_description, source, captured_at)
```

Indices: `securities(canonical_symbol)`, `securities(status)`, `listings(security_id)`, `symbol_history(exchange, symbol, valid_from)`, `corporate_actions(security_id, ex_date)`, `corporate_actions(parse_status)`, `fundamentals_snapshots(security_id, period_end DESC)`, `job_runs(job_name, business_date, status)`.

**Why `data_json` on fundamentals rather than wide columns:** the two providers disagree on line items, and NSE's old and new filing systems disagree with each other. A JSON blob plus a typed accessor lets phase 3 evolve the canonical line-item set without a migration per field. Add a narrow `fundamentals_metrics(security_id, period_end, metric, value)` in phase 3 once the metric set stabilises.

**Later-phase tables, named only:** `strategies`, `strategy_versions`, `picks`, `pick_outcomes`, `backtest_runs`, `backtest_trades`, `backtest_metrics`, `portfolios`, `orders`, `positions`, `trades`, `cash_ledger`, `ai_runs`, `ai_outputs`, `api_tokens`.

### Provider adapter interfaces (`providers/base.py`)

Five ABCs, DTOs as pydantic models (the boundary is where garbage gets rejected):

- **`PriceProvider`** — `capabilities`, `fetch_eod(date, exchange) -> RawArtifact`, `parse_eod(artifact) -> Iterator[CanonicalBar]`, optional `fetch_history(...)`. Raises `ProviderUnavailable` / `DataNotPublished` / `ContentValidationError`.
- **`SecurityMasterProvider`** — `fetch_master()`, optional `fetch_price_bands()`.
- **`CalendarProvider`** — `fetch_holidays(year, segment)`, `trading_days(start, end, exchange)`. Docstring must state: **callers intersect with weekdays**, NSE lists holidays falling on Sat/Sun.
- **`CorporateActionsProvider`** — `fetch_actions(since)` returns subjects **UNPARSED**. Parsing is the ingest layer's job so every provider shares one parser and one test suite.
- **`FundamentalsProvider`** — `is_approximate`, `fetch_filings_index(since, period)`, `fetch_statements(...)`.

`ProviderCapabilities` declares `exchanges`, `earliest_date`, `supports_delivery`, `supports_intraday`, `is_approximate`, `is_realtime` so callers degrade gracefully.

**Broker swap (phase 8):** `providers/broker/kite.py` implements `PriceProvider` with `is_realtime=True`; `config/env/prod.yaml` flips `providers.prices.nse: kite`; `registry.py` constructs it. **Nothing in `ingest/`, `domain/` or `cli/` changes.** The constraint that makes this work: ingest never imports a concrete provider module, it takes the ABC via DI. Enforce with an import-linter rule in CI.

### Ingest pipeline

`stk ingest daily [--date] [--force]` — systemd timer at ~20:30 IST (same unit ships to the VM):

```
1. resolve business_date (today IST, or last trading day if invoked on a holiday)
2. calendar check -> not a trading day: status=skipped_holiday, exit 0
3. refresh_master -> EQUITY_L.csv, sec_list.csv, BSE ListofScripData (weekly or if stale)
4. per exchange: fetch_eod -> validate -> persist raw -> parse -> resolve security_id
                 -> atomic partition rewrite
5. corporate actions -> parse subjects -> upsert   (unparsed => degraded)
6. if new ex-dates -> recompute adjustment_factors -> rebuild bars_daily_adjusted
7. compute liquidity_daily features
8. post-ingest assertions; set JobRun status
```

Each step is its own `JobRun` row via a context manager, so a corporate-actions failure does not lose the successful price ingest.

**Idempotency — three independent mechanisms:**
1. **Raw: content-addressed.** `UNIQUE(source, business_date, sha256)`. Re-downloading is a no-op; a *different* sha256 for the same date is a loud warning (NSE does republish corrected bhavcopies — you want to know).
2. **Parquet: overwrite-by-partition, never append.** Read the year partition, drop rows for `(exchange, business_date)`, concat, sort by `(symbol, date)`, write `.tmp`, `os.replace()`. **This is the key decision** — append-mode parquet is not idempotent and creates duplicate bars that are near-impossible to detect later.
3. **SQLite: natural-key upserts** on the `source_hash` uniques.

`job_runs` is **observability, not a lock.** Do not gate re-runs on "already succeeded" — that makes reparsing after a parser fix painful. `--force` only bypasses the reuse-existing-raw fast path.

**Loud failure:**
- Every fetch validates `status == 200` **AND** content-type **AND** magic bytes (`PK\x03\x04` for zip, first token `TradDt`/`SYMBOL` for CSV, `{`/`[` for JSON). Failure raises `ContentValidationError` carrying the URL and first 200 bytes of body. **This is the single guard against the BSE Angular-shell trap.**
- Post-ingest assertions, all fatal: row count within 30% of trailing 20-day median; no duplicate `(exchange, symbol, series, date)`; `high >= max(open, close, low)`; `close > 0`; `delivery_qty <= volume` where both non-null; turnover within 3× of `volume × vwap`.
- Unparsed corporate action → stored with `parse_status='unparsed'`, job `degraded`. **`ingest.fail_on_unparsed_corp_action: true`** makes it hard-fail — keep it true; a missed 1:1 bonus silently doubles an apparent price crash. If benign AGM-type subjects prove noisy, add an allowlist rather than flipping the flag.
- **`stk doctor`** is the health command: diffs `trading_calendar` against dates present in parquet, lists degraded/missing job runs for 90 days, lists `parse_status != 'parsed'`, flags securities with no bar in 10 trading days, reports partition row counts vs `_manifests`.

**`stk backfill prices --from --to --exchange`** uses the **same** normalise/write code path — non-negotiable, the backfill must not have its own parser. Differences: sequential iteration over `trading_calendar`, 1–2 req/sec throttle, resumable (skips dates already `validation='ok'`), buffers a full year before writing one partition, and on per-date failure records and **continues**, printing a failed-date summary and exiting non-zero. Source selection is automatic on `ingest.udiff_available_from`.

**ISIN dedup / NSE-preferred merge** (runs before prices): key both masters on **ISIN** — the only reliable cross-exchange identity, since symbols and punctuated company names both differ. Upsert `securities` by ISIN, `primary_exchange = NSE` where an NSE listing exists. Upsert one `listings` row per exchange; on symbol change, close the old `symbol_history` row and open a new one. Absent from a snapshot → `SUSPENDED` after 1, `DELISTED` after 20 consecutive. **Never hard-delete** (survivorship bias).

**Both exchanges' bars are stored.** The one-series-per-company resolution happens at *query* time via `securities.primary_exchange`, not at ingest. Storing only the NSE leg would destroy BSE-only names, for a saving of ~150 MB.

Edge cases to handle explicitly: same ISIN different symbol per exchange (normal); **same symbol different ISIN across exchanges** (real — BSE scrip_ids collide with NSE symbols); blank ISIN in the BSE master (skip + log, never guess); one ISIN with both EQ and BE series (two `listings` rows).

**Liquidity filter** computes in `ingest/liquidity.py` from `bars_daily` via DuckDB → `features/liquidity_daily/` parquet (per-symbol-per-day, millions of rows, fully rebuildable). Plus a tiny SQLite `universe_current(security_id, as_of_date, is_liquid, reason)` (~2k rows, truncate-and-replace nightly) so the API and pick engine can join eligibility against app-state tables without opening DuckDB. Thresholds live in `config/universe.yaml`; the rule is a pure function `domain/universe.is_liquid(metrics, thresholds) -> (bool, reason)` returning a human-readable rejection reason.

### Cost config scaffold

`config/costs.yaml` holds every rate as a **dated list** resolved by effective-from date, so a 2010–2026 backtest applies historically-correct rates. Phase 1 only **loads and validates** it into a `RateSchedule` with an `as_of(date)` resolver; `compute_costs()` is phase 2. Known transitions to encode: stamp duty 2020-07-01; exchange txn 2024-10-01 and 2026-03-01; NSE IPFT 2026-03-01 (₹10/crore → ₹0.01/crore). GST applies to brokerage + txn + SEBI fee + IPFT, **not** to STT or stamp duty. DP charge is flat per-scrip-per-day on the **sell leg only** and sits outside the per-order pipeline.

---

## Design system (extracted from the handoff)

The handoff is a compiled artifact using a template DSL (`sc-for`, `sc-if`, a `DCLogic` class with `renderVals()`). It maps near-1:1 onto React components with `useState`. Extract into `web/src/lib/theme.ts` as CSS custom properties:

```
bg.page   #0a0e13   text.primary   #e6ebf0   accent        #4c8dff
bg.panel  #11161d   text.secondary #c7d0d9   accent.hover  #7bacff
bg.inset  #161c25   text.muted     #8b96a3   positive      #26a969
bg.sunken #0e1319   text.faint     #5b6573   negative      #e5484d
bg.active #1b2330   border #232b36  border.subtle #2a3340   warning #d99a1b
border.row #1a2029                                          violet  #9d7cf5
```

Status chips are `rgba(<semantic>, 0.15)` background with the solid colour as text. **IBM Plex Sans** (400/500/600/700) for UI, **IBM Plex Mono** (400/500/600) for every number, symbol, price and date — enforce this split in the component API, not at each call site.

**The handoff pins the API response shapes** that phase 4 must serve:

- **Pick** — `symbol, company, exch, sector, horizon, strategy, score, ref, stop, target, window, btCagr, liveReturn, hitRate, reason, conflict?`
- **Strategy** — `id, name, horizon, status(live|candidate|decaying|retired), btCagr, winRate, maxDD, sharpe, trades, liveReturn?, hitRate?, avgHold, approx, rules[], equityCurve, niftyCurve, walkForward[{label,result}], tradeList[]`
- **Proposal** — `type(new|demote), title, rules[], rationale, btCagr, btWinRate, btMaxDD`
- **Brief** — `date, pending, overview, notablePicks[], conflicts[], positionNotes[]`
- **Portfolio** — `id, name, startCapital, cash, invested, currentValue, realisedPnl, unrealisedPnl, charges, returnPct, niftyReturnPct, xirr, maxDD, winRate` + `positions[] orders[] trades[]`

**The design already encodes the brief's safety rules** — build them as first-class API fields, not UI afterthoughts: the `approx` badge ↔ `is_approximate`; the amber "~15 min delayed" chip and per-trade "delayed feed" marker ↔ fill provenance stored on every trade; the red stale-data banner ↔ job-failure visibility; the order note *"Delayed feed down — will fall back to EOD fill"* ↔ the poller's refuse-to-fill-on-stale-data rule.

---

## Phases 2–8 (outline only)

**2 — Backtest engine.** Dated cost config, tiered slippage with a participation cap, circuit-lock detection, T+1 open fills, walk-forward harness, metrics, stored runs. The tests that matter: **prove no look-ahead** (assert every decision reads only data with `available_at <= decision_date`), and prove costs against hand-worked examples.

**3 — Strategy DSL + seed strategies.** JSON schema, validating interpreter (reject unknown indicators/fields), twelve seed strategies across four horizons, all through the promotion gate. **Never execute AI-generated code** — the DSL is data.

**4 — API + dashboard.** FastAPI endpoints matching the contracts above, React app from the handoff, pick tracking. **Chart spike first:** embed `NSE:RELIANCE` and `BSE:500325` in a static HTML file and look — research could not confirm the free TradingView widget renders Indian symbols, and it's a 5-minute test that beats more searching. Fallback is Lightweight Charts **5.2.1** (Apache 2.0, ~35 kB, multi-pane, `createSeriesMarkers` — note v5 removed `setMarkers`), which we may want anyway for backtest entry/exit markers.

**5 — Virtual playground.** Portfolios, order types, fill engine (candle high/low **touched** the price, not last-price match), 9:15–15:30 IST poller for only symbols with open orders/positions, corporate actions, journal, performance.

**6 — AI evening review.** Structured JSON, schema-validated, fence-stripped, one retry, never blocks the pipeline. Token/cost logging.

**7 — AI weekly strategy lab.** Proposals as DSL JSON → validation → automatic backtest → promotion gate → candidate awaiting UI approval. Demotion requires confirmation.

**8 — Deploy & harden.** Oracle ARM VM, systemd services, cron, Caddy + HTTPS, Parquet + SQLite backups, logging, job-failure visibility.

---

## Verification

**Test stack:** pytest + `respx` (httpx-native mocking) + `hypothesis`. **No vcr.py** — cassette YAML for binary zips is unreadable, cassettes go stale silently, and you cannot hand-craft the adversarial cases that matter.

**Fixtures:** checked-in, trimmed (~50 rows), **real bytes**, headers preserved byte-for-byte including leading spaces. Add a `.gitattributes` `-text` rule over `tests/fixtures/` so whitespace and CRLF survive.

The three tests that carry the most risk:

1. **Content validation / the BSE silent-200.** Serve the 14KB Angular shell with `status_code=200, content_type="text/html"`; assert `ContentValidationError`, that the message carries URL + body excerpt, and that **nothing** lands in `raw_artifacts` with `validation='ok'`. Then: correct CSV with wrong content-type → **accepted** (magic bytes pass; exchanges do serve inconsistent types); HTML body with `content-type: text/csv` → rejected; 200 with empty body → rejected. Mirror for the NSE zip path with a non-`PK` body. **Highest-value test in phase 1.**
2. **Corporate-action subject parser.** Table-driven over 200+ real subject strings harvested from a year of the live API. Must cover `"Dividend - Rs 17.70 Per Share"`, `"Dividend Rs.2.50 Per Share"` (no spaces), `"Bonus 1:1"`, `"Bonus Issue 3:5"`, `"Face Value Split From Rs.10/- To Rs.1/-"`, `"Rights 1:4 @ Premium Rs 50"`, and `"Dividend - Rs 5 Per Share and Bonus 1:1"` (compound → **two** actions). Critical negative: an unrecognised subject produces `parse_status='unparsed'` and degrades — **never `action_type='OTHER'` with `price_factor=1.0` silently**, because that exact default is how a 1:1 bonus becomes a phantom 50% crash in every chart and backtest. Hypothesis property: for any BONUS/SPLIT, `price_factor × volume_factor ≈ 1.0`.
3. **Cost calculation.** Golden values against hand-computed examples, notably a ₹5,000 delivery sell where the DP charge dominates (assert ≈31 bps). Boundary test across 2026-03-01 (different NSE txn rate *and* different IPFT). Assert GST does **not** touch STT or stamp duty — a one-line bug with a persistent small bias.

Also: normalisation round-trip (parse UDiFF and `sec_bhavdata_full` for the same symbol/date, assert OHLC/volume agree and turnover agrees after the lakhs conversion — catches units mistakes); `-` → `None` not `0`; idempotency (run `ingest daily` three times, assert identical row counts and parquet sha256); calendar (a Saturday-falling holiday must not appear as a trading day); ISIN merge (NSE+BSE pair, BSE-only, blank ISIN, and a rename across two snapshots); `stk doctor` exits non-zero on a deliberately missing trading day.

**Out of scope for automated tests:** live network calls. A separate `pytest -m live` marker holds a handful of real-endpoint smoke tests, excluded from the default run, plus a weekly `stk doctor --check-endpoints`. Endpoint drift is frequent enough that this is worth more than any unit test.

**Coverage target:** 90%+ on `ingest/`, `domain/` and `providers/*/` parse functions. No target elsewhere.

**End-to-end acceptance for phase 1:**
```
uv run stk db migrate
uv run stk ingest daily --date 2026-09-17     # exits 0, writes one partition
uv run stk ingest daily --date 2026-09-17     # idempotent: identical sha256
uv run stk backfill prices --from 2024-07-08 --to 2024-12-31 --exchange NSE
uv run stk doctor                             # no gaps, no unparsed CAs, exits 0
uv run pytest                                 # green
```

---

## Risk register

| Risk | Handling |
|---|---|
| **Cost rates are wrong.** NSE txn charge and IPFT both changed 2026-03-01; research sourced most rates from Zerodha, not primary circulars. | Brief says verify before relying. Phase 2 opens by confirming each rate against an NSE/SEBI circular. Dated lists mean a fix is a config edit, not a code change. |
| **Pre-Jul-2024 history may not be reachable.** | Time-boxed spike in phase 0. If it fails, fall back to ~10y and **say so** rather than quietly backtesting on thin data. |
| **yfinance is the most fragile dependency.** v1.7.0, rate-limited, unofficial Yahoo API with crumb auth. | Strictly off the critical path — feature-flagged, backfill and intraday only. Bhavcopy is authoritative, free, unlimited, unauthenticated. Use a `curl_cffi` chrome-impersonated session. |
| **Holiday-calendar libraries expire 2026-12-31.** `exchange_calendars`/`pandas_market_calendars` ship BSE-only hardcoded lists ending this year. | Use the NSE holiday API cached to disk; library is offline fallback only. |
| **Third-party history mirror.** `chartiny` is a stranger with commit access to your price history. | If used: one-shot snapshot into `data/raw/`, per-file sha256 in `raw_artifacts`, **never called at runtime**. |
| **NSE data policy vs virtual trading.** NSE's Data Sharing & Usage Policy bars market data use for "virtual trading, an activity of similar nature" — the stated reason TradingView blocks NSE symbols in its own paper trading. | Weak concern for a personal, unpublished, single-user app, but a real reason **not to publish this app or redistribute its data**. Worth knowing before phase 5. |

## Open items for later phases

1. **Which broker's fee schedule is the default** — needed before phase 2 costs mean anything; changes small-order economics more than anything except the DP charge. Config ships with a discount-broker (Zerodha-shaped) placeholder.
2. **Does the free TradingView widget render NSE/BSE symbols** — 5-minute empirical test at the top of phase 4.
3. **Benign corporate-action allowlist** — only if AGM-type subjects prove noisy in practice.

## Amendments

Decisions that changed after this plan was written. Newest last. The plan above is otherwise a snapshot; `CLAUDE.md`'s status section tracks progress.

- **2026-09-19 — Phase 2/3 sequencing and scope.** Phase 2 (engine) shipped as planned. Phase 3 deviates in three deliberate ways:
  1. **Indicators are computed on the fly**, not stored as a `features/indicators_daily/` parquet dataset. They are past-only by construction and proven so by a truncation-invariance test; persisting them is an optimisation to add if a full-history run proves too slow, not a correctness need.
  2. **Fundamental metrics are derived, not stored.** There is no `fundamentals_metrics` table: ROCE / D-E / CAGR / TTM-EPS are computed from `fundamentals_line_items` by `stk.domain.fundamentals`, so a formula change can never leave a stale cached value.
  3. **Ten seed strategies, not twelve.** The brief's list has ten distinct strategies (3 short-term, 3 swing, 3 momentum, 1 long-term); "twelve" in this plan was a miscount.
- **2026-09-19 — Strategy statuses gain `rejected`** (failed the promotion gate) alongside `live | candidate | decaying | retired`; the UI can render it as retired. A gate that cannot decide (`insufficient_evidence`) leaves a strategy `candidate`, never `rejected`.
- **2026-09-19 — Intraday poller uses its own provider switch** (`providers.intraday`), independent of `enable_yfinance_fallback`, so enabling intraday candles for the playground cannot put yfinance on the EOD price path. (Phase 5.)
- **2026-09-19 — Backtests are NSE-only in v1.** BSE's legacy feed keys on scrip codes rather than tickers until 2024-07-08, so a cross-exchange symbol identity does not exist for most of the history. BSE bars stay in the lake.
- **2026-09-19 — Design reference moved** to `docs/design/Stock Terminal Design.html` (was `web/Stock Terminal Standalone.html`), so `web/` can hold the Vite app.
- **2026-09-19 — Phase 8 orchestration.** `stk nightly` / `stk weekly` run each step as its own `stk` subprocess (isolation from crashes and hangs; each step is exactly the command you would type to reproduce it), recorded as `nightly.<step>` / `weekly.<step>` in `job_runs`. There is no separate `features` step (indicators are computed on the fly, see above) and no `stk-lab` timer: the AI lab is the last step of `stk weekly` because it should read the freshly ingested fundamentals. `/api/status` gains `jobAlerts` (the newest attempt of a scheduled step failed/degraded in the last 3 days); the API never reads a log.
- **2026-09-19 — Backups are a first-class command** (`stk backup run|verify|list|restore`) rather than a shell script around `sqlite3 .backup`: the shell script is a thin wrapper (`deploy/backup.sh`) so the logic — verification, rotation that only touches date-named directories with a manifest, a restore that never deletes — is unit-tested. `data/raw` is excluded by default.
- **2026-09-19 — Deploy is artifacts + a runbook only.** No VM existed; `deploy/` and `docs/runbook.md` are consistency-tested against the code but unrun. `providers/broker/kite.py` is a documented stub that raises on construction.
- **2026-09-19 — LLM provider is config; Groq is the default for now.** `config/ai.yaml` `provider: groq | anthropic` selects a client behind the same `LlmClient` protocol (`stk.ai.client.make_client`); `GroqClient` talks to Groq's OpenAI-compatible endpoint over plain httpx (no SDK), with JSON mode and our own pydantic validation + one retry. Groq's `json_validate_failed` error is turned into a reply so that retry can show the model its own bad output. `max_input_chars` refuses an over-budget prompt locally (Groq's free tier has low per-minute token limits) and records it as a failed run. The brief's "Sonnet-class model" is now the *Anthropic* provider's default; the Groq default is `openai/gpt-oss-120b` (chosen from `stk ai models`; the first guess was not available to the key).
- **2026-09-19 — Funds are excluded from the stock universe.** Not in the original plan: found by the first live scan, which recommended gold ETFs. `instrument_class` (migration 0009) is filled from UDiFF ISINs (`INF…` = fund); the panel loader excludes funds; `stk scan`/`promote` refuse to run without it. Earlier promotion results were invalid and re-run.
