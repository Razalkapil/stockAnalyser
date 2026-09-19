# Runbook

How to install, run, watch, back up, restore and repair the app on the VM. Everything here
uses commands that exist in the repo; the deploy files are in [`deploy/`](../deploy/).

> **Status of this document:** the deploy artifacts are tested for consistency with the code
> (`tests/unit/test_deploy.py`) but have **never been run on a real VM** — none existed when they
> were written. The first install is the real test; expect to fix small things and write them
> back here.

## What runs, and when

| Unit | When (IST) | What |
|---|---|---|
| `stk-api.service` | always | FastAPI on `127.0.0.1:8000`. Caddy is the only way in. |
| `stk-poller.service` | always | Paper-trading poller. Idles outside 09:15–15:30 on trading days. Stale feed ⇒ orders wait for the EOD bar; nothing fills on stale data. |
| `stk-nightly.timer` | Mon–Fri 20:30 and 23:00 (retry) | `stk nightly` |
| `stk-weekly.timer` | Sun 10:00 | `stk weekly` |
| `stk-backup.timer` | daily 23:45 | `deploy/backup.sh` |
| `stk-doctor.timer` | daily 07:30 | `stk doctor --backup-dest …` |

**`stk nightly`** runs, each as its own subprocess and its own `job_runs` row
(`nightly.<step>`): `corpactions` → `prices` → `indices` → `liquidity` → `scan` → `track` →
`playground_eod` → `ai_evening`. If `prices` fails, everything that reads today's bars is
recorded as failed with "not run: prices failed first" (never silently skipped); `corpactions`
and `indices` still run. Re-running is always safe — every step is idempotent, which is why the
23:00 retry is just the same command.

**`stk weekly`**: `master` → `calendar` → `fundamentals_sweep` → `xbrl` → `ai_lab`. `xbrl` exits 2
(recorded `degraded`) when some downloads failed; they are retried next week.

## First install

1. Provision the VM ([`ORACLE_VM_SETUP.md`](ORACLE_VM_SETUP.md)); point a DNS name at it and open
   ports 80/443. Install `uv`, Node 20+, and Caddy.
2. `sudo git clone <repo> /srv/stockanalyser/app && cd /srv/stockanalyser/app`
3. `deploy/install.sh` — creates the `stk` user and directories, `uv sync --frozen`, migrates,
   installs and enables the units and timers. It creates `/etc/stockanalyser/env` from
   `deploy/env.example`; edit it (`GROQ_API_KEY` — or `ANTHROPIC_API_KEY` if `config/ai.yaml` says `provider: anthropic` — and `STK_OFFSITE_CMD`).
4. Build the web app: `cd web && npm ci && npm run build` (output `web/dist`, served by Caddy).
5. Put `deploy/Caddyfile` at `/etc/caddy/Caddyfile` (replace `stk.example.com`), `sudo systemctl reload caddy`.
6. Create your API token — **shown once**: `sudo -u stk env STK_APP__ENV=prod .venv/bin/stk api token create me`.
   Paste it into the sign-in screen.
7. Load data (long-running; run in `tmux`, and **check each exit code** — a wrapper that prints
   "done" regardless once hid a crash for an hour):
   ```bash
   sudo -u stk env STK_APP__ENV=prod bash -c '
     set -e
     .venv/bin/stk ingest calendar && .venv/bin/stk ingest master
     .venv/bin/stk backfill prices --exchange NSE --from 2021-01-01 --to $(date +%F)
     .venv/bin/stk ingest corpactions
     .venv/bin/stk ingest adjustments
     .venv/bin/stk ingest liquidity
     .venv/bin/stk strategies seed
     .venv/bin/stk strategies promote --all      # ~minutes per strategy; needs the price lake + benchmark
   '
   ```
   Measured locally for 2021→2026 on NSE: 330 MB parquet, 418 MB raw, 12 MB `app.db`; budget an hour or more for the backfill. `2022-08-08` is a permanent gap
   (NSE served an `.xlsx` under the `.csv` URL); the backfill refuses it and says so.
8. `stk doctor --backup-dest /srv/stockanalyser/backups` and `systemctl list-timers 'stk-*'`.

## Watching it

- **The dashboard banner** (red, top of every screen) shows stale price data *and* any
  `nightly.*` / `weekly.*` step whose latest run failed or degraded in the last 3 days. A step
  that failed and was then re-run successfully stops alerting.
- **`stk doctor`** (07:30 daily): calendar gaps, stale symbols, corrupt partitions, unparsed
  corporate actions, adjusted series behind their actions, **three consecutive AI failures**,
  **no/old backup**. Poller trouble is reported as `info`, not a problem (a stale delayed feed is
  expected some days). A non-zero exit fails the unit: `systemctl --failed`.
- `journalctl -u stk-nightly -e`, `-u stk-poller -f`, `-u stk-api -f`.
- `stk ai usage` — AI spend (an estimate; blank when the model has no configured price).
- `sqlite3 data/app.db "SELECT job_name, business_date, status, error_message FROM job_runs ORDER BY run_id DESC LIMIT 20"`

## Backups and restore

`stk backup run --dest DIR` (via `deploy/backup.sh`): a consistent `app.db` snapshot
(SQLite backup API, safe while the API runs) + the parquet lake, checksummed in a `MANIFEST.json`,
**verified after writing**, then rotated (7 daily + 4 weekly). A destination inside the data
directory is refused. `data/raw` is *not* included by default (`--include-raw`): it is large
and re-fetchable; the parquet lake is the derived copy you would otherwise re-ingest for hours.

**`app.db` is the irreplaceable part**: paper portfolios, the journal, picks and their track
record, AI briefs and proposals. Prices can be re-fetched; your history cannot.

**A backup on the same VM dies with the VM.** Set `STK_OFFSITE_CMD` (e.g. `rclone sync` to OCI
object storage, which has a free allowance). `backup.sh` warns on every run until you do.

**Restore drill — do this once before you need it:**
```bash
stk backup list --dest /srv/stockanalyser/backups
stk backup verify /srv/stockanalyser/backups/2026-09-18
deploy/restore.sh /srv/stockanalyser/backups/2026-09-18
```
`restore.sh` verifies first, stops the API/poller/timers, restores, migrates, runs the doctor
and restarts. **Nothing is deleted**: existing data is moved aside to `*.pre-restore-<timestamp>`;
remove those yourself once satisfied.

## Failure playbook

| Symptom | Meaning | Do |
|---|---|---|
| Banner: `nightly.prices failed` | Exchange not yet published, changed format, or the network is down. | `journalctl -u stk-nightly -e` / the `job_runs.error_message`. Re-run: `stk nightly` (safe any time). A `ContentValidationError` or a wrong-date file means the exchange served bad content — the pipeline refused it on purpose. Do not bypass; check `docs/data-sources.md` and probe with `stk doctor --check-endpoints`. |
| `nightly.corpactions failed` — *unparsed subject* | A corporate action the parser doesn't know. **All rows are stored first**, then it fails so a split can't be silently missed. | Add a rule to the table in `ingest/corpactions.py` (+ a test using the real subject text), then re-run. Until then prices for that symbol may be mis-adjusted — the adjusted series is marked degraded. |
| `orders_pending_eod` (info) | Delayed feed was down; orders are parked. | Nothing: the EOD pass decides them from the day's bar. |
| `ai_failing` | Last 3 evening/lab runs failed (key lapsed, model renamed, output invalid). | `stk ai models` (does the key work; is the configured model still offered), `stk ai usage`, `ai_runs.error`; `stk ai evening --dry-run` shows the prompt and its size. Everything else runs regardless. |
| `backup_missing` / `backup_stale` | The backup timer isn't running or is failing. | `systemctl status stk-backup`, run `deploy/backup.sh` by hand. |
| Data stale but no failed step | The timer did not fire (VM was off, timer not enabled). | `systemctl list-timers`; `stk nightly`. `Persistent=true` catches up after a boot. |
| Disk full | Raw bytes + lake + backups grow. | `du -sh data/*`; the parquet lake was 330 MB for 5 years of NSE, `data/raw` was 418 MB and grows fastest — prune it only if you accept re-fetching to re-parse. |
| API 401 everywhere | Token revoked/lost. | `stk api token create <name>`; tokens are stored hashed, so a lost one cannot be recovered, only replaced. |
| DB corruption | `stk doctor` / SQLite errors. | `deploy/restore.sh <latest backup>`. |

## Things never verified live

Stated so nobody assumes otherwise: the AI evening review and strategy lab (no API key was ever
available — `stk ai evening --dry-run` first, then one real run), yfinance intraday during market
hours, a full `fundamentals-sweep` + `xbrl` run across the universe, the TradingView embed for
BSE-only symbols, most cost rates in `config/costs.yaml` (only NSE's 2026-03-01 change is
verified — see the ledger in `data-sources.md`), and the deploy artifacts on an actual VM.
