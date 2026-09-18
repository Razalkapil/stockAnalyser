# ADR 0003: Historical price source

**Status:** Decided (NSE). BSE pre-UDiFF coverage not yet investigated.

## Context

The build plan targets 15+ years of price history (2010-onward) for meaningful walk-forward backtesting. NSE's current UDiFF bhavcopy format only exists from 2024-07-08 onward. This ADR records the phase-0 history spike's findings on what covers the rest.

## Decision

Two NSE sources combine to give continuous, confirmed coverage from **2010-01-04** (earliest tested) to present, with automatic source selection by date in `stk.providers.registry.get_nse_price_provider_for_date`:

| Date range | Source | Provider | Has delivery? | Has ISIN? |
|---|---|---|---|---|
| 2010-01-04 .. 2019-09-29 | Legacy `cm{DDMMMYYYY}bhav.csv.zip` | `NseLegacyBhavcopyProvider` | No | No |
| 2019-09-30 onward | `sec_bhavdata_full` | `NseSecBhavdataProvider` | Yes | No |
| 2024-07-08 onward | UDiFF (companion, for ISIN join only) | *(not yet a registered PriceProvider)* | Yes | Yes |

**Confirmed by direct probing on 2026-09-18:**

- `sec_bhavdata_full`'s exact cutover was found by binary/daily search: **2019-09-27 is the last invalid (404) date, 2019-09-30 is the first valid date** (2019-09-28/29 are a weekend). No gap: the legacy format is *also* still available through at least 2019-10-01, confirmed by direct probe, so the two sources overlap rather than leaving a hole.
- The legacy `cm*bhav.csv.zip` path (often assumed dead — it is NOT the same path that actually 404s; that dead path is a different, differently-organized URL some tutorials reference) was confirmed live for 2010-01-04, 2012-06-15, 2014-11-20, 2016-03-10, and 2019-06-03. A single probe date, 2018-08-22, returned 404 — checked and confirmed to be a **market holiday** (Ganesh Chaturthi), not a coverage gap: 2018-08-20, 21, 23, 24 all returned 200.
- The legacy format's real schema, from an actual fetched file: `SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,` (trailing comma/empty column in NSE's own header). `TIMESTAMP` is `D-MON-YYYY` with the day **not** zero-padded (e.g. `4-JAN-2010`) — Python's `%d` format code parses this correctly without special-casing.

## A more important finding: NSE's own archive occasionally serves mislabeled content

During real backfill testing (not a hypothetical concern), two specific historical dates in the `sec_bhavdata_full` archive were found to serve **content dated differently from what the URL/filename promises**:

- Requesting `sec_bhavdata_full_30092019.csv` (i.e., for 2019-09-30) returns a file whose rows are all dated `27-Jun-2019`.
- Requesting `sec_bhavdata_full_02102019.csv` (i.e., for 2019-10-02) returns a file whose rows are all dated `01-Oct-2019` — a duplicate of the *previous* trading day's file.

This is a data-quality bug on NSE's side, not a URL-construction or parsing bug in this codebase (confirmed via direct `curl` against both URLs, independent of any of our code). It is reproducible, not a one-off transient glitch (re-checked twice).

**Consequence for the ingest design:** the requested `business_date` can never be trusted to match the fetched content's actual date. `stk.ingest.assertions.assert_bars_match_requested_date` was added specifically to guard against this — every ingest, whether `stk ingest daily` or `stk backfill prices`, now verifies the parsed bars' dates match what was requested and **fails loudly** (raises `IngestAssertionError`, recorded in `job_runs` as `failed`) rather than silently writing the content under the wrong partition date key. Verified against the real mislabeled dates: both `2019-09-30` and `2019-10-02` now fail cleanly with a clear error message, while every neighbouring correct date ingests normally, and the resulting parquet partition contains no corrupted or duplicate rows.

**Open question this raises:** how many other historical dates across 2010-2026 have this same mislabeling bug? Unknown — a full backfill will surface them one at a time (each shows up as a `failed` job_run, visible via `stk doctor`), and each one is a case of "NSE served bad data for this specific date, retry later or accept a permanent gap for it." This is a small, bounded, and now-detectable problem, not a systemic one — the two known cases are isolated dates surrounded by correct data on both sides.

## Consequences

- `config/defaults.yaml`'s `ingest.backfill_start: "2010-01-01"` is now a **confirmed-reachable** value, not merely provisional. (The very first trading day of 2010 was 2010-01-04, a Monday.)
- `stk backfill prices --from --to --exchange NSE` is implemented (`stk.ingest.backfill`), reuses `ingest_nse_prices_for_date` for every date (no separate backfill parser), and is safe to re-run after a partial failure.
- BSE's pre-UDiFF coverage has **not** been investigated (the spike's step 4). Per the build plan's guidance ("if step 4 fails, accept BSE history starting 2024-07-08 and note it as a limitation — NSE covers >95% of the liquidity you care about"), this is deferred rather than blocking. `--exchange BSE` is not yet implemented in `stk backfill`.
- The third-party GitHub mirror (`chartiny/nse-sec-bhavdata-full`) was **not needed** — NSE's own archive reaches far enough back on its own. The plan's risk register entry about not trusting that mirror at runtime is now moot for NSE; revisit only if BSE's pre-UDiFF gap needs filling later.
