# Data sources — verified endpoints

Every endpoint below was verified live by direct `curl`/`httpx` request on **2026-09-18**. Exchange URLs and formats have changed multiple times historically (the legacy NSE bhavcopy path was retired 2024-07-08) and will change again — **re-verify before trusting an old copy of this document**, and prefer the `pytest -m live` smoke tests over reading this file when in doubt.

## Blocking behaviour summary

| Host | Auth needed | Notes |
|---|---|---|
| `nsearchives.nseindia.com` | Any non-default User-Agent | No cookies, no Referer. A bare `curl/x.y` UA is blocked; even an empty UA string works. |
| `www.nseindia.com/api/*` | Browser UA (cookie handshake not always required in practice, but code should still prime a cookie jar for robustness) | Some endpoints (holiday-master) worked with UA alone in testing; others (corporate-actions) are documented as needing a cookie jar from GETting the HTML page first, plus a plausible `Referer`. |
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
- This is the **primary historical price source**: it predates the UDiFF format, carries delivery data in the same file, and (pending the phase-0 history spike's confirmation) appears to go back much further than UDiFF's mid-2024 start.
- Implemented in `stk.providers.nse.prices.NseSecBhavdataProvider`.

### Daily EOD prices (ISIN-bearing companion): UDiFF

```
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip
```

- Zip file containing one CSV. 34 columns including `ISIN`, ISO dates.
- **Only available from ~2024-07-08 onward** — the legacy `/content/historical/EQUITIES/{YYYY}/{MON}/cm{DDMONYYYY}bhav.csv.zip` path this replaced now 404s (NSE circular 62424, effective 2024-07-08).
- Used as the ISIN-bearing companion for the security-master join, not as the primary price series.
- Parser: `stk.ingest.normalise.parse_udiff`.

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
https://www.nseindia.com/api/holiday-master?type=trading
```

- Returns JSON keyed by segment (`CBM` = cash/capital market). Each entry: `{tradingDate: "DD-Mon-YYYY", weekDay, description, morning_session, evening_session, Sr_no}`.
- **Includes holidays that fall on a weekend** (e.g. a Sunday-falling festival) — callers MUST intersect with weekdays; see `stk.domain.calendar.build_trading_day_set`.
- **Do not rely on `exchange_calendars` or `pandas_market_calendars`** for this: neither has an NSE calendar (only BSE/`XBOM`), and both ship hardcoded holiday lists that **run out at the end of 2026**.

### Corporate actions

```
https://www.nseindia.com/api/corporates-corporateActions?index=equities
```

- Returns `{symbol, comp, series, isin, faceVal, subject, exDate, recDate, bcStartDate, bcEndDate, ndStartDate, ndEndDate, ind, caBroadcastDate}`.
- **`subject` is unstructured free text** — e.g. `"Dividend - Rs 17.70 Per Share"`, `"Bonus 1:1"`, `"Face Value Split From Rs 10 To Rs 2"`. Parsed by `stk.ingest.corpactions.parse_subject`, which must fail loudly (`parse_status="unparsed"`) rather than silently defaulting an unrecognised subject to a no-op — see that module's docstring.

### Fundamentals (official, no XBRL parsing needed)

```
https://www.nseindia.com/api/corporates-financial-results?index=equities&period=Quarterly
```

- Quarterly results with broadcast date, consolidated/audited flags. NSE runs an old "Financial Results" system and a newer "Integrated Filing (Financial)" system in parallel (cutover around Q4 FY2024-25 / April 2025) — parsers must handle both shapes.
- Shareholding pattern: `https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern`
- **Promoter pledge** (needed by the long-term quality screen): `https://www.nseindia.com/companies-listing/corporate-filings-pledged-data`

This is why Screener.in was dropped from the design: it offers no official API, its `/terms/` page 404s (no retrievable ToS), and its robots.txt disallows `/company/source/quarter/*` — precisely the endpoint every third-party scraper uses.

## BSE

### Daily EOD prices

```
https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{YYYYMMDD}_F_0000.CSV
```

- **Uncompressed CSV**, not a zip. Same 34-column UDiFF schema as NSE (`Src=BSE`).
- **CRITICAL TRAP:** legacy BSE bhavcopy URLs return **HTTP 200 with `content-type: text/html`** and a ~14KB Angular SPA shell body — not a 404. Any code that trusts `status_code == 200` before unzipping/parsing will silently accept garbage. Every BSE (and, defensively, NSE) fetch validates content-type **and** magic bytes/header tokens — see `stk.core.http.validate_csv_response` / `validate_zip_response`.
- Use `www.bseindia.com` exactly; the apex `bseindia.com` redirects.

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
- Used for: (a) approximate fundamentals (`is_approximate=True`) where NSE's own filing history hasn't accumulated yet, (b) potential pre-2024 price backfill if the phase-0 history spike finds NSE's own archives insufficient, (c) delayed intraday candles for the phase-5 playground poller.

## Things still to verify (do not treat as settled)

1. **Exact pre-2024 history depth** of `sec_bhavdata_full` — this is the phase-0 history spike's job (see `docs/adr/0003-historical-price-source.md` once written).
2. **Cost rates in `config/costs.yaml`** — sourced from broker-published schedules (Zerodha), not primary NSE/SEBI circulars. Flagged explicitly in that file; verify before using for real-money decisions.
3. **BSE corporate actions and holiday calendar endpoints** — not yet implemented; NSE's are used as the sole source for both in phase 1, which is a reasonable approximation since NSE and BSE trading calendars are effectively identical for equities.
