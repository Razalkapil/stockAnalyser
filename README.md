# stockAnalyser

A personal, single-user Indian stock market app: nightly NSE/BSE scanning, strategy backtesting with a promotion gate, live pick tracking, and a virtual paper-trading playground.

Full requirements: [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md). Implementation notes for contributors (including agents): [`CLAUDE.md`](CLAUDE.md). Verified data-source endpoints: [`docs/data-sources.md`](docs/data-sources.md).

## Status

Phase 0 (repo/tooling) and Phase 1 (data pipeline + store) are done: live-verified daily price ingest and backfill for both NSE and BSE (2010-present), the security master (NSE + BSE, merged by ISIN), corporate actions (fetch + parse + upsert), fundamentals filing metadata, and the liquidity filter. See `CLAUDE.md`'s "Current status" section for the up-to-date breakdown, including what's deliberately deferred (XBRL line-item parsing, BSE suspension/delisting detection, the yfinance fallback). Phases 2-8 are not started — the build plan explicitly scopes execution to phases 0-1 with a check-in before moving on.

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
cp .env.example .env   # fill in secrets when phases 4+ need them; empty is fine for now
```

## Common commands

```bash
uv run stk db migrate               # apply SQLite schema migrations
uv run stk ingest daily             # ingest today's NSE + BSE prices (or --date YYYY-MM-DD)
uv run stk backfill prices --from 2010-01-01 --to 2026-09-18 --exchange NSE  # or BSE
uv run stk ingest master            # refresh securities/listings from NSE + BSE, merged by ISIN
uv run stk ingest corpactions       # fetch/parse/upsert corporate actions
uv run stk ingest liquidity         # recompute the liquidity feature set + universe_current
uv run stk ingest fundamentals RELIANCE --isin INE002A01018   # one security's filing metadata
uv run stk doctor                   # ingest health check; exits non-zero on problems

uv run pytest                       # full test suite (live-network tests excluded)
uv run pytest -m live               # also run tests that hit real NSE/BSE endpoints
uv run ruff check backend/src tests scripts
uv run mypy backend/src/stk
```

## Layout

```
backend/src/stk/   the "stk" package: config, core, providers, ingest, store, domain, cli
web/               React + Vite + TS front-end (phase 4, not yet started)
config/            committed, non-secret YAML configuration
data/              gitignored: raw exchange bytes, parquet, SQLite (data/app.db)
tests/             unit/, integration/, fixtures/ (real, trimmed exchange responses)
docs/              brief, data-source notes, ADRs, deployment notes
```

## A note on scope

This is a personal project, not a product: single user, free data sources, hosted on one Oracle Cloud Always Free VM (setup notes: [`docs/ORACLE_VM_SETUP.md`](docs/ORACLE_VM_SETUP.md)). It is not published or redistributed — see the risk register in [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) regarding NSE's data-usage policy and virtual trading.
