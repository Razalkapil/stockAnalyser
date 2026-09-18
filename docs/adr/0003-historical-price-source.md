# ADR 0003: Historical price source

**Status:** Partially decided. The forward/recent-history source is confirmed and implemented. The pre-2024 deep-history spike (target: 2010-onward, per the build plan) has **not yet been run** — this ADR will be updated with its findings before the backfill command is implemented.

## Context

The build plan targets 15+ years of price history (2010-onward) for meaningful walk-forward backtesting. NSE's current UDiFF bhavcopy format only exists from 2024-07-08 onward (the legacy pre-2024 format was retired by NSE circular 62424). A separate older format, `sec_bhavdata_full`, predates UDiFF and was confirmed live during phase-1 implementation.

## Decision (confirmed so far)

`sec_bhavdata_full` is the **primary** NSE daily price source, for these reasons:

1. Confirmed live and working via `stk.providers.nse.prices.NseSecBhavdataProvider`, tested against real fetches on 2026-09-18 (see `tests/unit/test_nse_prices_provider.py::TestLiveEndpoint`, run with `pytest -m live`).
2. Carries **delivery quantity and percentage** in the same file — required by the short-term seed strategies (Section 5 of the brief) and otherwise only available from a second source.
3. No leading-space header issues once parsed correctly (`skipinitialspace=True`), and the format has been stable across the dates tested.

UDiFF (`BhavCopy_NSE_CM_..._F_0000.csv.zip`) is kept as a **companion source**, used for its ISIN column in the security-master join — `sec_bhavdata_full` is symbol-keyed only.

## Open question: how far back does `sec_bhavdata_full` actually go?

**Not yet answered.** The build plan's phase-0 history spike (a time-boxed, one-day investigation) was scoped to answer this with a concrete probe across ten dates spanning 2010–2024, in this order:

1. `sec_bhavdata_full` direct from `nsearchives.nseindia.com` for each probe date.
2. The GitHub mirror `chartiny/nse-sec-bhavdata-full`, if (1) doesn't reach far enough — used only as a one-shot snapshot into `data/raw/` with recorded sha256 hashes, never called at runtime.
3. The legacy NSE `cm{DDMMMYYYY}bhav.csv.zip` path, as a prices-only (no delivery) fallback.
4. BSE's pre-UDiFF `EQ_ISINCODE_{DDMMYY}.zip`.
5. yfinance `.NS` history as a last resort, cross-checked against whichever of (1)-(4) worked for overlapping dates.

**This spike has not been executed yet.** `config/defaults.yaml`'s `ingest.backfill_start: "2010-01-01"` is therefore a **provisional target, not a confirmed value** — the backfill command (`stk backfill prices`) should not be implemented or run against real history until this ADR is updated with the spike's findings and a real `ingest.backfill_start` is set.

## Consequences

- Phase 1's `stk ingest daily` command (forward-looking, one date at a time) works today and is fully tested, including against live data.
- The `stk backfill prices --from --to` command referenced in the build plan's phase-1 scope is **not yet implemented** — it depends on this ADR's open question being resolved first, per the plan's own sequencing ("run the spike before writing the ingest pipeline's backfill path").
- When the spike runs, update this ADR's status to "Decided", fill in the actual earliest reliable date per exchange, and update `config/defaults.yaml`'s `ingest.backfill_start` accordingly.
