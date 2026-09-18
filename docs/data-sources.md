# Data sources — verified endpoints

Every endpoint below was verified live by direct `curl`/`httpx` request on **2026-09-18**. Exchange URLs and formats have changed multiple times historically (the legacy NSE bhavcopy path was retired 2024-07-08) and will change again — **re-verify before trusting an old copy of this document**, and prefer the `pytest -m live` smoke tests over reading this file when in doubt.

## Blocking behaviour summary

| Host | Auth needed | Notes |
|---|---|---|
| `nsearchives.nseindia.com` | Any non-default User-Agent | No cookies, no Referer. A bare `curl/x.y` UA is blocked; even an empty UA string works. |
| `www.nseindia.com/api/*` | Browser UA + `Referer` | Verified 2026-09-18 for `corporates-corporateActions` and `corporates-financial-results`: **no cookie handshake needed in practice** — a plain browser UA (with or without a `Referer`) got a 200 on a cold request, no priming GET, no cookie jar. Earlier notes in this file assumed a cookie jar was required; that assumption is now corrected. `Referer` is still sent defensively since other endpoints on this host may be stricter, but nothing in this codebase depends on cookies for this host. |
| `www.bseindia.com` | Any UA | Use this exact host — the apex `bseindia.com` redirects. |
| `api.bseindia.com` | `Referer: https://www.bseindia.com/` | |

## NSE

### Daily EOD prices (primary source): `sec_bhavdata_full`

```
https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv
```

- Plain CSV. **Every header/value after the first column has a leading space** — parse with `csv.DictReader(..., skipinitialspace=True)` and still `.strip()` defensively.
- Columns: `SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER`.
- `DATE1` is `DD-Mon-YYYY`. `TURNOVER_LACS` is in **lakhs** — multiply by 100,000 to get rupees; this conversion must happen at the parser boundary and never leak past it.
- `DELIV_QTY`/`DELIV_PER` are `-` when not applicable (e.g. debt instruments) — this must parse to `None`, never `0`.
- Confirmed live from **2019-09-30** onward (exact cutover found by daily-granularity probe; 2019-09-27 is the last invalid/404 date). This is the preferred source whenever it's available, since it carries delivery data; the legacy format below covers everything before it.
- Implemented in `stk.providers.nse.prices.NseSecBhavdataProvider`.

### Daily EOD prices (deep history, 2010-2019): legacy `cm*bhav.csv.zip`

```
https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cm{DDMONYYYY}bhav.csv.zip
```

- Confirmed live back to **2010-01-04** by direct probe (phase-0 history spike, see `docs/adr/0003-historical-price-source.md`). This is a *different, still-live* URL from the one commonly cited as "the old NSE bhavcopy path that 404s now" — that dead path is a differently-organized legacy format from an earlier NSE site reorganisation.
- Schema: `SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,` (trailing empty column). No delivery data, no ISIN. `TIMESTAMP` is `D-MON-YYYY`, day not zero-padded.
- Confirmed to overlap with `sec_bhavdata_full`'s start (both cover 2019-09-30..2019-10-01) — no coverage gap between the two sources.
- Implemented in `stk.providers.nse.legacy_prices.NseLegacyBhavcopyProvider`. Source selection between this and `sec_bhavdata_full` is automatic by date via `stk.providers.registry.get_nse_price_provider_for_date`.

**⚠️ Confirmed data-quality bug in NSE's own archive:** at least two historical dates (`2019-09-30`, `2019-10-02`) serve content whose internal date does not match the requested date/filename (see ADR-0003 for full detail — this was found via real backfill testing, not speculation). Every ingest validates the fetched content's date against the requested date (`stk.ingest.assertions.assert_bars_match_requested_date`) and refuses to write on a mismatch, rather than silently corrupting the partition under the wrong date key. Expect more such dates to surface as backfill coverage expands; each shows up as a `failed` job_run visible via `stk doctor`.

### Daily EOD prices (ISIN-bearing companion): UDiFF

```
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip
```

Implemented by `stk.providers.nse.udiff.NseUdiffProvider` (registered as `nse_udiff`). **Verified live 2026-09-19** for both its first date and a recent one — needs only a non-default User-Agent, like the rest of the `nsearchives` host.

- Zip file containing one CSV. 34 columns including `ISIN`, ISO dates. Confirmed header begins `TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,...`.
- **Only available from 2024-07-08 onward** (confirmed: that exact date returns a real zip) — the legacy `/content/historical/EQUITIES/{YYYY}/{MON}/cm{DDMONYYYY}bhav.csv.zip` path this replaced now 404s (NSE circular 62424, effective 2024-07-08).
- **Deliberately NOT the primary price source, and `get_nse_price_provider_for_date` never selects it.** UDiFF carries ISIN but has **no delivery quantity or delivery percentage**, which `sec_bhavdata_full` does have and which the short-term seed strategies need. Swapping it in would silently null out a legitimately-nullable column for every bar from 2024-07 onward — a change no schema check would catch. A unit test asserts the automatic selection never returns it.
- Parser: `stk.ingest.normalise.parse_udiff` (shared with BSE UDiFF).

**On resolving `security_id`/`isin` for bars generally:** `bars_daily` stores whatever the *source* reported, which is null for every `sec_bhavdata_full` row. Identity is resolved at QUERY time by `store/queries/prices.sql`'s `bars_with_resolved_identity`, which joins `symbol_history`/`listings`/`securities` keyed by the symbol as of each bar's own date. That is self-healing as the master improves and gets renames right; a `security_id` backfilled into 32 historical partitions would instead be frozen at whatever the master knew on rewrite day. As a cheap complement, `ingest.daily` fills identity on *freshly parsed* bars only, from a single in-memory map — never overwriting a value the source itself reported.

### Security master

```
https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
```

- Columns (leading spaces again): `SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE`.

### Price bands (for circuit-lock detection)

```
https://nsearchives.nseindia.com/content/equities/sec_list.csv
```

Columns: `Symbol, Series, Security Name, Band, Remarks`.

### Trading holiday calendar

```
https://www.nseindia.com/api/holiday-master?type=trading&year=YYYY
```

Implemented by `stk.providers.nse.calendar.NseHolidayMasterProvider`; ingested by `stk ingest calendar`. Needs a browser UA (a `Referer` is sent defensively; no cookie handshake was required in practice). Re-verified live **2026-09-19**, which corrected three things believed true before:

- **The segment key is `CM`, not `CBM`.** `CBM` is the *corporate bond* market and happens to be the first key in the JSON object, which makes it an easy and wrong default — an earlier version of this document asserted `CBM` was the cash market. They are genuinely different calendars: for 2024, `CBM` carries five holidays `CM` does not (19-Feb, 01-Apr, 09-Apr, 23-May, 16-Sep) and misses one `CM` does have (02-Mar). Using `CBM` for equities would have silently skipped five real trading days a year and fetched one non-trading day.
- **`year=` works, and history reaches back to 2011.** The build plan assumed only the current year was available, which would have left 2011–2025 with no authoritative calendar. Confirmed: every year 2011–2026 returns a populated `CM` list. 2010 (the earliest date the price archives reach, per ADR 0003) is **not** available — that year's calendar can only be derived from ingested bars.
- **A `financial_year=` parameter is silently IGNORED** — it returns the current year rather than erroring, so a caller believes it asked a question it did not.

**Silent-200 trap, same class as BSE's SPA shell but on a different host:** an out-of-range year returns **HTTP 200 with valid JSON and no `CM` rows** (2010 returns `{}`; 2027 returns a payload whose `CM` list is empty). Treating that as "no holidays that year" would fabricate a calendar in which every weekday traded, and `stk doctor` would then report ~250 missing ingests for it. `parse_holidays` raises `DataNotPublished` on an empty segment list for exactly this reason.

- Each entry: `{tradingDate: "DD-Mon-YYYY", weekDay, description, morning_session, evening_session, Sr_no}`. `Sr_no` is present for the current year and absent for historical years — do not depend on it.
- **Includes holidays that fall on a weekend** (e.g. a Sunday-falling festival) — callers MUST intersect with weekdays; see `stk.domain.calendar.build_trading_day_set`. The provider deliberately keeps them in its raw records so that rule lives in exactly one place.
- **Do not rely on `exchange_calendars` or `pandas_market_calendars`** for this: neither has an NSE calendar (only BSE/`XBOM`), and both ship hardcoded holiday lists that **run out at the end of 2026**.

### Index closes (benchmark) — `ind_close_all`

```
https://nsearchives.nseindia.com/content/indices/ind_close_all_{DDMMYYYY}.csv
```

Implemented by `stk.providers.nse.indices.NseIndicesProvider`; ingested by `stk ingest indices`. Needs only a non-default User-Agent, like the rest of the `nsearchives` host. **Verified live 2026-09-19.** `archives.nseindia.com` serves the identical file if the primary host ever moves.

Header (confirmed against a real fetched file): `Index Name, Index Date, Open Index Value, High Index Value, Low Index Value, Closing Index Value, Points Change, Change(%), Volume, Turnover (Rs. Cr.), P/E, P/B, Div Yield`. Dates are `DD-MM-YYYY` — note this differs from every other NSE file in this document. `-` is the null marker, converted to null and never to 0.

Three findings from the probe:

- **Coverage starts 2012-02-21.** Every weekday probed before it 404s (2010-01-04, and all of 2010–2011 sampled quarterly). The price archives reach 2010-01-04, so **the benchmark series is roughly two years shorter than the price series** — a backtest starting in 2010 has prices but no benchmark for its first two years. This is a real constraint on Phase 2's benchmark-relative metrics; `stk doctor` should surface it rather than anyone discovering it inside a backtest result.
- **The benchmark has been renamed twice**, so keying a series on the printed name silently splits it into three disconnected fragments: `S&P CNX Nifty` (through early 2013) → `CNX Nifty` (mid-2013 through 2015) → `Nifty 50` (2016 onward). `stk.ingest.normalise.INDEX_CODE_BY_NAME` maps all three to the canonical `NIFTY_50`, and `store/queries/prices.sql`'s `benchmark_series` query filters on that code, never the name.
- **Non-trading dates 404 honestly** — unlike BSE, there is no silent-200 SPA shell here, and unlike the `sec_bhavdata_full` archive no mislabeled-content case was observed. Weekends, a real holiday (2026-01-26) and a nonsense date (`31129999`) all returned a clean 404 with `text/html`. The requested-date assertion is applied anyway (`assert_index_bars_match_requested_date`), because ADR 0003 showed that assumption failing on a sibling archive.

`Turnover (Rs. Cr.)` is multiplied by 10,000,000 at the parser boundary — the canonical layer only ever holds rupees, same discipline as the `TURNOVER_LACS` rule for `sec_bhavdata_full`.

**BSE/SENSEX index data is a known gap.** This file covers NSE indices only, and no free BSE index archive has been confirmed. Nifty 50 is what the UI contract's `niftyCurve`/`niftyReturnPct` need, so this is not currently blocking.

### Corporate actions

```
https://www.nseindia.com/api/corporates-corporateActions?index=equities
```

- Returns `{symbol, comp, series, isin, faceVal, subject, exDate, recDate, bcStartDate, bcEndDate, ndStartDate, ndEndDate, ind, caBroadcastDate}`.
- Supports `from_date`/`to_date` query params (format `DD-MM-YYYY`) for a date range — confirmed live 2026-09-18 (1736 rows returned for a ~9-month range). Without them, the endpoint returns its own rolling window (observed: roughly the trailing/upcoming few weeks).
- **`subject` is unstructured free text** — e.g. `"Dividend - Rs 17.70 Per Share"`, `"Bonus 1:1"`, `"Face Value Split From Rs 10 To Rs 2"`. Parsed by `stk.ingest.corpactions.parse_subject`, which must fail loudly (`parse_status="unparsed"`) rather than silently defaulting an unrecognised subject to a no-op — see that module's docstring.
- Implemented in `stk.providers.nse.corpactions.NseCorporateActionsProvider`. Ingest (fetch + parse + upsert into `corporate_actions`, keyed on `(source, source_hash)` for idempotency): `stk.ingest.corpactions.ingest_corporate_actions`, CLI `stk ingest corpactions`.

### Fundamentals (official, no XBRL parsing needed)

```
https://www.nseindia.com/api/corporates-financial-results?index=equities&period=Quarterly
```

- Quarterly results with broadcast date, consolidated/audited flags. Also accepts `symbol=` for a single security and `period=Annual` (both confirmed live 2026-09-18 with distinct, plausible row counts). `period=Half-Yearly`/`Half Yearly`/`Yearly` gave ambiguous/inconsistent counts during probing and were **not** confirmed — `stk.providers.nse.fundamentals.NseFundamentalsProvider` raises `NotSupportedError` for `Period.HALF_YEARLY`/`TTM` rather than guess at an unverified query string.
- **Correction to an earlier research assumption:** the build plan's original note ("official, no XBRL parsing needed") assumed `resultDetailedDataLink` would carry pre-parsed structured line items. Live probing found this field **empty on every sampled row** (a broad equities scan and a single-symbol query both). The only structured data actually available without XBRL parsing is **filing metadata** — broadcast date, audited/consolidated flags, period, and a link to the underlying XBRL document (`xbrl` field) — not income/balance/cashflow figures themselves. `NseFundamentalsProvider` is implemented against this reality: `fetch_filings_index`/`fetch_statements` return this metadata (`statement_type="meta"` in `fundamentals_snapshots`, honestly labelled rather than pretending it's parsed financials), with the XBRL link preserved in `data`/`source_url` for a future parsing pass. Full line-item XBRL parsing remains unimplemented and is a substantial separate scope (a real per-`indAs`/`format` XML schema), not attempted partially.
- NSE runs an old "Financial Results" system and a newer "Integrated Filing (Financial)" system in parallel (cutover around Q4 FY2024-25 / April 2025) — no separate live endpoint for the newer system was found during this pass; only `corporates-financial-results` was confirmed reachable.
- Shareholding pattern: `https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern`
- **Promoter pledge** (needed by the long-term quality screen): `https://www.nseindia.com/companies-listing/corporate-filings-pledged-data`

This is why Screener.in was dropped from the design: it offers no official API, its `/terms/` page 404s (no retrievable ToS), and its robots.txt disallows `/company/source/quarter/*` — precisely the endpoint every third-party scraper uses.

## BSE

### Daily EOD prices

```
https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{YYYYMMDD}_F_0000.CSV
```

- **Uncompressed CSV**, not a zip. Same 34-column UDiFF schema as NSE (`Src=BSE`).
- **CRITICAL TRAP, confirmed live on 2026-09-18 on the CURRENT working URL (not just a retired legacy one):** any date with no data — weekend, holiday, or a date before this format existed — returns **HTTP 200 with `content-type: text/html`** and the exact same ~14KB Angular SPA shell body, not a 404. Confirmed identical for a real weekend date and for a nonsense far-future date (`20991231`); there is no way to distinguish "ask again later" from "this will never exist" from content alone. Any code that trusts `status_code == 200` before parsing will silently accept garbage. Handling: `stk.providers.bse.archives.fetch_bse_csv_file` treats **any 200 response with `content-type: text/html`** as `DataNotPublished` (recorded as `skipped_holiday`, not a failure); a non-html response that still fails the CSV header-token check is a genuine `ContentValidationError`. Every fetch also validates magic bytes/header tokens generally — see `stk.core.http.validate_csv_response` / `validate_zip_response`.
- Use `www.bseindia.com` exactly; the apex `bseindia.com` redirects.
- Confirmed live from **2024-07-08** onward (BSE's UDiFF cutover, same industry-wide date as NSE's).
- Implemented in `stk.providers.bse.prices.BseUdiffProvider`.

### Daily EOD prices (deep history, 2010 – 2024-07-05): legacy `EQ*.CSV.ZIP`

```
https://www.bseindia.com/download/BhavCopy/Equity/EQ{DDMMYY}_CSV.ZIP
```

- Confirmed live back to **2010-01-04** by direct probe (spike step 4, previously deferred — now resolved, see `docs/adr/0003-historical-price-source.md`). Confirmed to stop being served (the SPA shell instead) from 2024-07-08 onward, with no gap against UDiFF's start.
- **Uncompressed-inside-a-zip CSV.** Columns: `SC_CODE,SC_NAME,SC_GROUP,SC_TYPE,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,NO_TRADES,NO_OF_SHRS,NET_TURNOV,TDCLOINDI` (CRLF line endings). No ISIN, no delivery data, and **no symbol** — BSE identifies securities purely by a numeric `SC_CODE` scrip code in this format; resolving it to a symbol/ISIN happens later via the security master join, not in this parser.
- Exhibits the exact same SPA-shell trap as the UDiFF endpoint (confirmed for both a real holiday, 2018-08-22, and a nonsense future date) — handled by `stk.providers.bse.archives.fetch_bse_zip_file` with the same any-200-with-text/html heuristic.
- Implemented in `stk.providers.bse.legacy_prices.BseLegacyBhavcopyProvider`. Source selection between this and UDiFF is automatic by date via `stk.providers.registry.get_bse_price_provider_for_date` — mirrors the NSE side exactly. Ingest: `stk.ingest.daily.ingest_bse_prices_for_date`; backfill: `stk backfill prices --exchange BSE` (now reaches 2010-01-04, same as NSE).

### Security master

```
https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active
```

- Needs `Referer: https://www.bseindia.com/`.
- Fields: `SCRIP_CD, Scrip_Name, Status, GROUP, FACE_VALUE, ISIN_NUMBER, INDUSTRY, scrip_id, Segment, NSURL, Issuer_Name, Mktcap`. `INDUSTRY` is null throughout in practice — don't rely on it. `Mktcap` is in crore.

## yfinance (fallback / backfill only, never the critical path)

- Version 1.7.0+ (the library went 1.x — old 0.2.x-era advice online is stale).
- Rate-limited by Yahoo with no published limit; the practical mitigation is a `curl_cffi` session with `impersonate="chrome"`.
- Intraday history windows: 1m bars ≈ last 7 days (≈30 days total history available); 5m/15m/30m ≈ last 60 days; 1h ≈ last 730 days.
- Used for: (a) approximate fundamentals (`is_approximate=True`) where NSE's own filing history hasn't accumulated yet, (b) filling a hole the official archives cannot cover, (c) delayed intraday candles for the phase-5 playground poller.

Implemented as `stk.providers.yfinance.prices.YFinancePriceProvider` (live-smoke-verified 2026-09-19), but **disabled by default**. `providers.registry` raises `ConfigError` unless `providers.enable_yfinance_fallback: true`, so merely being named in a config list is not enough to reach it — it cannot drift onto the critical path by accident.

What it declares it cannot do, rather than leaving a caller to discover it:

- **No `fetch_eod`.** There is no whole-market file; Yahoo is per-symbol. Calling it raises `NotSupportedError` rather than returning a partial market.
- **`is_approximate=True`.** Restated, split-adjusted prices with no point-in-time knowledge date, so a backtest built on them cannot honestly claim "this is what you would have seen on the day".
- **No delivery data and no rupee turnover.** `turnover` is a *derived* `close × volume`, not the exchange's traded value, and must never be compared against a bhavcopy turnover as an equal.
- **Survivorship bias.** Delisted names are simply absent, which quietly flatters any backtest built on a universe derived from it.
- **An empty result raises `DataNotPublished`**, never returns `[]`: an empty frame means a wrong ticker mapping, a delisted name, or a rate limit — none of which mean "this symbol did not trade".

Ticker mapping: `SYMBOL.NS` (NSE), `SCRIPCODE.BO` (BSE — a numeric scrip code, matching how BSE's legacy bhavcopy identifies securities). The throttle interval comes from `http.yfinance.min_interval_ms` and is enforced process-wide, since the rate limit is Yahoo's, not any one call site's.

The phase-0 history spike found NSE's and BSE's own archives sufficient back to 2010-01-04 (ADR 0003), so item (b) is no longer needed for price backfill.

## Things still to verify (do not treat as settled)

1. ~~Exact pre-2024 history depth of `sec_bhavdata_full`~~ — resolved, see `docs/adr/0003-historical-price-source.md`: NSE prices are confirmed live back to 2010-01-04 via two combined sources.
2. **Cost rates in `config/costs.yaml`** — *partially* verified; see the ledger below. Anything not marked verified there is still from broker-published schedules (Zerodha). Verify before using for real-money decisions.
3. **BSE corporate actions and holiday calendar endpoints** — not yet implemented; NSE's are used as the sole source for both, which is a reasonable approximation since NSE and BSE trading calendars are effectively identical for equities. The approximation is now visible in the data rather than only in this document: `stk ingest calendar --exchange BSE` writes `source='nse_holiday_master(nse_proxy)'` on every row it creates.
4. ~~BSE pre-UDiFF price history depth~~ — resolved, see `docs/adr/0003-historical-price-source.md`: BSE prices are confirmed live back to 2010-01-04 via the legacy `EQ*.CSV.ZIP` archive, same as NSE.

## Transaction charges — verification ledger

Rates live in `config/costs.yaml`; this table records which are checked against a **primary** document (read directly, not via a broker or news summary). The "unverified" warning in that file stays until the last row is closed.

| Rate | Status | Source |
|---|---|---|
| NSE cash-market transaction charge: Rs 297/crore each side up to 28 Feb 2026 | **verified** | NSE circular NSE/FA/73061 (27 Feb 2026), "Existing outflow" column — `https://nsearchives.nseindia.com/content/circulars/FA73061.pdf` (needs a browser User-Agent) |
| NSE cash-market transaction charge: Rs **306.99**/crore each side from 1 Mar 2026 (= 0.000030699) | **verified** — and *corrected*: config previously held Rs 307, double-counting the separate IPFT line by Rs 0.01/crore | same circular |
| NSE IPFT: Rs 10/crore → Rs 0.01/crore on 1 Mar 2026 | **verified** | same circular |
| Total NSE cash outflow (txn + IPFT) unchanged at Rs 307/crore across 1 Mar 2026 | **verified** (the circular's stated intent; pinned in `test_costs_compute.py`, which also caught a transcription slip while this table was being written) | same circular |
| NSE txn charge uniform from 1 Oct 2024 | unverified — the circular above references NSE/FA/64323 (27 Sep 2024) and SEBI/HO/MRD/TPD-1/P/CIR/2024/92; neither read yet | — |
| BSE transaction charge (0.00375%), STT, stamp duty, SEBI turnover fee, GST, DP charge, brokerage | unverified | broker schedules |
| Pre-2020-07-01 stamp duty (varied by state) | not modelled — post-2020 rate used as an approximation | — |
