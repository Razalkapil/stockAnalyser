# ADR 0003: Historical price source

**Status:** Decided (NSE and BSE both).

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

## BSE pre-UDiFF history (spike step 4, resolved 2026-09-18)

The spike's step 4 was originally deferred (see the build plan) on the assumption that BSE's pre-UDiFF history would need its own investigation and might not be reachable. It has now been investigated by direct probe, with a clean result:

**BSE's legacy per-date bhavcopy is still live at its original URL, on the same current download host, back to at least 2010-01-04:**

```
https://www.bseindia.com/download/BhavCopy/Equity/EQ{DDMMYY}_CSV.ZIP
```

- Confirmed live (HTTP 200, real zip, `application/x-zip-compressed`) for 2010-01-04, 2012-06-15, 2014-11-20, 2016-03-10, 2018-08-20/21/23/24, 2020-03-23, 2021-07-01, 2023-02-15, 2024-06-14, and every date from 2024-07-01 through 2024-07-05.
- Confirmed to stop being served (SPA shell, not the real file) from **2024-07-08 onward** — the exact date BSE's UDiFF format starts. No gap, no overlap: the legacy format's last working date (2024-07-05, a Friday) and UDiFF's first date (2024-07-08, the following Monday) are adjacent trading days.
- Confirmed to exhibit BSE's own SPA-shell trap on this URL family too: 2018-08-22 (Ganesh Chaturthi, a real BSE holiday) and a nonsense far-future date (`311299`) both return the identical HTTP 200 + `text/html` shell as the UDiFF endpoint's own trap (see `docs/data-sources.md`'s BSE section) — the same coarse "any 200-with-text/html is DataNotPublished" heuristic applies unchanged.
- Schema, from an actual fetched file (`EQ040110.CSV`): `SC_CODE,SC_NAME,SC_GROUP,SC_TYPE,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,NO_TRADES,NO_OF_SHRS,NET_TURNOV,TDCLOINDI` (CRLF line endings). No ISIN, no delivery data, and critically **no symbol at all** — BSE identifies securities purely by a numeric scrip code in this format. `symbol` is set to the scrip code as a string; resolving it to a real symbol/ISIN via the security master is deferred to the ingest merge step, same division of responsibility as every other bhavcopy parser in this codebase.
- No probe further back than 2010-01-04 was attempted, matching the scope of the original NSE-side spike (2010-onward was the brief's target, already met).

**Consequence:** BSE now has the same two-source, automatically-date-selected shape as NSE (see `stk.providers.registry.get_bse_price_provider_for_date`, mirroring `get_nse_price_provider_for_date`):

| Date range | Source | Provider | Has delivery? | Has ISIN/symbol? |
|---|---|---|---|---|
| 2010-01-04 .. 2024-07-05 | Legacy `EQ{DDMMYY}_CSV.ZIP` | `BseLegacyBhavcopyProvider` | No | No (scrip code only) |
| 2024-07-08 onward | UDiFF | `BseUdiffProvider` | No | Yes |

`stk backfill prices --exchange BSE` now reaches back to 2010-01-04, the same as NSE. `BseUdiffProvider.fetch_eod` still raises `NotSupportedError` if constructed directly and called on a pre-cutover date (it alone genuinely cannot serve one), but nothing in the ingest/backfill orchestrators does that anymore — both go through `get_bse_price_provider_for_date` for automatic selection, same as the NSE side.

## Consequences

- `config/defaults.yaml`'s `ingest.backfill_start: "2010-01-01"` is now a **confirmed-reachable** value for both exchanges, not merely provisional. (The very first trading day of 2010 was 2010-01-04, a Monday.)
- `stk backfill prices --from --to --exchange NSE|BSE` is implemented (`stk.ingest.backfill`), reuses the corresponding `ingest_*_prices_for_date` function for every date (no separate backfill parser), and is safe to re-run after a partial failure.
- The third-party GitHub mirror (`chartiny/nse-sec-bhavdata-full`) was **not needed** — both exchanges' own archives reach far enough back on their own. The plan's risk register entry about not trusting that mirror at runtime is now fully moot.
