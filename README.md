# stockAnalyser

A personal, single-user Indian stock market app: nightly NSE/BSE scanning, strategy backtesting with a promotion gate, live pick tracking, and a virtual paper-trading playground.

Full requirements: [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md). Implementation notes for contributors (including agents): [`CLAUDE.md`](CLAUDE.md). Verified data-source endpoints: [`docs/data-sources.md`](docs/data-sources.md).

## Status

All eight phases are built: the data pipeline for both exchanges, the backtest engine with an Indian cost model, the strategy DSL and promotion gate, pick tracking, the FastAPI + React dashboard, the paper-trading playground, the two AI jobs, and deploy artifacts with a runbook. See `CLAUDE.md`'s "Current status" for the detail and — importantly — the list of what has **not** been verified live (the AI jobs against the real API, the deploy on a real VM, the XBRL sweep). Operating it: [`docs/runbook.md`](docs/runbook.md).

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
uv run stk doctor                   # health check; exits non-zero on problems
uv run stk strategies seed          # register the ten seed strategies
uv run stk strategies promote --all # walk-forward backtest + promotion gate
uv run stk scan                     # today's picks from live strategies
uv run stk nightly                  # the whole nightly run (systemd calls this)
uv run stk api serve                # dashboard API on 127.0.0.1:8000 (web: cd web && npm run dev)
uv run stk backup run --dest ~/stk-backups   # verified backup of app.db + the lake

uv run pytest                       # full test suite (live-network tests excluded)
uv run pytest -m live               # also run tests that hit real NSE/BSE endpoints
uv run ruff check backend/src tests scripts
uv run mypy backend/src/stk
```

## Layout

```
backend/src/stk/   the "stk" package: config, core, providers, ingest, store, domain, backtest, strategies, playground, ai, api, cli
web/               React + Vite + TS dashboard (types generated from the API's OpenAPI)
deploy/            systemd units + timers, Caddyfile, backup/restore/install scripts
config/            committed, non-secret YAML configuration
data/              gitignored: raw exchange bytes, parquet, SQLite (data/app.db)
tests/             unit/, integration/, fixtures/ (real, trimmed exchange responses)
docs/              brief, data-source notes, ADRs, deployment notes
```

## A note on scope

This is a personal project, not a product: single user, free data sources, hosted on one Oracle Cloud Always Free VM (setup notes: [`docs/ORACLE_VM_SETUP.md`](docs/ORACLE_VM_SETUP.md)). It is not published or redistributed — see the risk register in [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) regarding NSE's data-usage policy and virtual trading.
