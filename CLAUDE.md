# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repository.

## What this is

A personal, single-user Indian stock market app: nightly NSE/BSE scanning, strategy backtesting with a promotion gate, live pick tracking, and a virtual paper-trading playground. Full requirements: **`docs/PROJECT_BRIEF.md`** — read it before making any decision that isn't purely mechanical. The implementation plan (folder structure, schemas, phase sequencing, and the research corrections to the brief) is in `docs/adr/` and `docs/BUILD_PLAN.md`; verified external endpoints are in `docs/data-sources.md`.

## Ground rules (from the brief, do not relitigate without asking)

- **Single user.** No multi-tenancy, no sign-up flow.
- **Free data sources**, always behind a provider adapter (`stk.providers.base`). Never let ingest/domain/API code import a concrete provider class directly — go through `stk.providers.registry`.
- **IST everywhere, INR with lakh/crore formatting.** Use `stk.core.time` and `stk.core.money`, not ad-hoc datetime/float handling.
- **Never execute AI-generated code.** Strategies are DSL JSON, validated against a schema and interpreted.
- **Fail loudly.** A missing/malformed corporate action, an unexpected content-type, a missing trading day — these raise or exit non-zero. Never silently default to a "safe-looking" no-op; see `stk.ingest.corpactions`'s module docstring for the concrete failure mode this prevents (a missed bonus/split silently corrupting a price series).
- **Raw bytes are sacred.** Every fetched response is persisted under `data/raw/` before parsing (`stk.ingest.raw_store`), content-addressed by sha256, so re-parsing never needs the network.
- **Parquet writes are overwrite-by-partition, never append** (`stk.store.parquet.writer`). This is the idempotency mechanism for the whole ingest pipeline — do not add an append path.
- **`job_runs` is observability, not a lock.** Re-running any ingest job for the same date must always be safe; it never checks "did this already succeed" before running again.

## Repo layout

```
backend/src/stk/
  config/     settings.py (pydantic-settings, layered YAML+env), costs.py (dated rate schedule)
  core/       time.py (IST), money.py (Decimal/lakh-crore), http.py (content validation), errors.py
  providers/  base.py (5 ABCs), registry.py, nse/, bse/, yfinance/, broker/ (phase-8 placeholder)
  ingest/     daily.py, backfill.py (orchestrators), normalise.py, corpactions.py, assertions.py, jobs.py
  store/      parquet/ (schema, writer), db/ (SQLite migrations + engine), duck.py
  domain/     universe.py, calendar.py -- PURE functions, no I/O
  cli/        typer app `stk`: db, ingest, backfill, doctor
config/       defaults.yaml, env/{local,prod}.yaml, costs.yaml, universe.yaml, horizons.yaml
tests/        unit/, integration/, fixtures/ (real, trimmed exchange responses)
docs/         PROJECT_BRIEF.md, data-sources.md, adr/, runbook.md (phase 8), ORACLE_VM_SETUP.md
```

## Working here

- **Package manager: `uv`.** `uv sync --all-groups`, `uv run pytest`, `uv run stk ...`. The workspace root `pyproject.toml` has `backend` as a member.
- **Tests:** `uv run pytest` (live-network tests excluded by default via the `live` marker; run `uv run pytest -m live` deliberately when verifying an endpoint is still reachable in its documented shape). Fixtures in `tests/fixtures/` are **real, trimmed exchange responses**, not synthetic data — prefer extending these over hand-writing new synthetic fixtures when testing a parser.
- **Lint/type-check:** `uv run ruff check backend/src tests scripts` and `uv run mypy backend/src/stk`. Both must be clean before considering a change done. `domain/` and `ingest/` are mypy-strict (`disallow_untyped_defs`).
- **Config:** anything a human would tune (cost rates, liquidity thresholds, horizon windows) lives in committed YAML under `config/`. Anything secret lives in `.env` (see `.env.example`), never committed.
- **Cost rates in `config/costs.yaml` are explicitly flagged as unverified against primary NSE/SEBI circulars** — sourced from broker-published schedules. Do not remove that warning without actually verifying against a primary source.
- When a data-source URL or format needs re-checking, update `docs/data-sources.md` in the same change — it is meant to be the living, re-verified record, not a one-time research dump.

## Current status (update this section as phases complete)

- **Phase 0 (repo/config/tooling):** done.
- **Phase 1 (data pipeline + store):** substrate complete and tested — config system, canonical schemas, SQLite migrations, the atomic parquet writer, the corporate-action parser, live-verified daily ingest for **both exchanges** (`stk ingest daily` now runs NSE and BSE, `stk doctor`), and live-verified backfill for both (`stk backfill prices --exchange NSE|BSE`), both now reaching **2010-01-04**. Both exchanges have automatic source selection across two confirmed price archives each (see `docs/adr/0003-historical-price-source.md`): NSE via `get_nse_price_provider_for_date`, BSE via `get_bse_price_provider_for_date` (the previously-deferred spike step 4 is now resolved — BSE's legacy `EQ*.CSV.ZIP` archive is confirmed live back to 2010-01-04, with a clean handoff to UDiFF at 2024-07-08, no gap). The NSE spike also surfaced a real NSE data-quality bug (some historical dates serve mislabeled content) — guarded against by `assert_bars_match_requested_date`. BSE's "silent 200" trap (an HTML SPA shell instead of a 404 for any non-trading/invalid date) is confirmed live on both its UDiFF and legacy URL families — handled uniformly by treating any 200-with-`text/html` response as `DataNotPublished`. **Not yet done:** corporate-actions/fundamentals/security-master live providers, and the liquidity filter.
- **Phases 2-8:** not started.
