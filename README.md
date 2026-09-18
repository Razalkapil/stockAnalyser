# stockAnalyser

A personal, single-user Indian stock market app: nightly NSE/BSE scanning, strategy backtesting with a promotion gate, live pick tracking, and a virtual paper-trading playground.

Full requirements: [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md). Implementation notes for contributors (including agents): [`CLAUDE.md`](CLAUDE.md). Verified data-source endpoints: [`docs/data-sources.md`](docs/data-sources.md).

## Status

Phase 0 (repo/tooling) and the phase-1 substrate (config, storage, parsers, one live-verified NSE ingest path) are done. See `CLAUDE.md`'s "Current status" section for the up-to-date phase breakdown.

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
cp .env.example .env   # fill in secrets when phases 4+ need them; empty is fine for now
```

## Common commands

```bash
uv run stk db migrate               # apply SQLite schema migrations
uv run stk ingest daily             # ingest today's NSE prices (or --date YYYY-MM-DD)
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
