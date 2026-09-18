# Project brief for Claude Code — Indian stock suggester + virtual playground

You are helping me (Razal, a front-end engineer with 6 years of experience) build a **personal** web app for the Indian stock market. Read this whole brief before writing any code. Every decision below has already been agreed; where something is marked **OPEN**, ask me before choosing.

---

## 1. What the app does

1. Scans **NSE + BSE** stocks every evening after market close.
2. Suggests stocks in **four horizons** — short-term, swing, momentum, long-term — using technical + fundamental analysis.
3. Only lets a strategy produce live picks if it has passed a **rigorous backtest gate**.
4. Uses **AI (Claude API) sparingly**: once or twice a day to review/explain picks, and weekly to propose new strategies.
5. Shows charts (TradingView, ~15-min delay is acceptable).
6. Tracks every pick's **live return %** after it is issued (forward testing).
7. Includes a **virtual playground**: paper-trade with virtual money, filled near-live from ~15-min-delayed quotes.

## 2. Hard constraints

- **Single user (me only).** No sign-up, no multi-tenancy. Simple single-user auth (password or token) is enough because it will be on the internet.
- **Free data sources only** for now. Paid data may come later, so every data source sits behind a **provider adapter interface** — swapping to a paid broker/vendor API must mean writing one new adapter, nothing else.
- **Free hosting**: one **Oracle Cloud Always Free ARM VM** runs everything.
- **Dashboard only** — no Telegram/email alerts.
- **AI calls are rare**: evening review (1×/day, optionally a 2nd) + weekly strategy lab. Never call the AI per request, per stock, or in loops.
- Timezone everywhere: **IST (Asia/Kolkata)**. Currency: **INR** with Indian number grouping (lakh/crore) in the UI.

## 3. Stack

- **Backend / analysis:** Python, **FastAPI**.
- **Market data store:** **Parquet files queried with DuckDB** (prices, indicators, fundamentals snapshots). Do not put years of daily price history in a relational DB.
- **App state** (portfolios, orders, positions, picks, strategies, backtest results, AI outputs): **SQLite in WAL mode** by default (single user, one box). Keep the data-access layer clean so moving to Postgres later is easy.
- **Front-end:** **OPEN** — ask me which framework. UI designs will come from Claude Design; implement from that handoff.
- **Charts:** first try the TradingView embeddable widget for NSE/BSE symbols. Free widgets sometimes refuse Indian symbols ("only available on TradingView") due to licensing — **test this in phase 4 before building around it**. Fallback: TradingView's open-source **Lightweight Charts** fed with our own data, which also lets us draw backtest entry/exit markers and paper-trade fills on the chart.
- **Scheduling on the VM:** cron (or systemd timers) for batch jobs; a **systemd service** for the intraday poller; a reverse proxy (Caddy or nginx) with HTTPS.
- **Secrets** (Claude API key, app password) in environment variables / `.env`, never committed.

## 4. Data layer

**Sources (free):**
- NSE and BSE **bhavcopy** files — daily end-of-day OHLCV, delivery data; long history available.
- **yfinance** (`.NS` / `.BO` tickers) — gap filling, corporate-action adjustments, and **delayed intraday candles** for the playground poller. It is unofficial and rate-limited: batch requests, cache, back off on errors.
- **Fundamentals:** Screener.in exports or scraped quarterly results (build as an adapter; expect fragility).
- Index data for benchmarks (Nifty 500 at minimum).

**Rules:**
- **Deduplicate by ISIN.** A company listed on both exchanges is one security; prefer NSE prices when available (usually more liquid).
- **Liquidity filter before any screen:** minimum average daily traded value and minimum trading-day count over a recent window. Thresholds live in config. This mostly removes illiquid BSE-only and circuit-bound names.
- **Adjust for splits and bonuses**; keep a corporate-actions table (also used by the playground for splits/bonus/dividends).
- **Keep delisted stocks** in history to avoid survivorship bias in backtests.
- **Snapshot fundamentals every quarter from day one** and store them with the date we *captured* them. For older history (where we only have today's restated numbers), apply a **reporting-lag rule**: treat quarterly results as known only 45–60 days after quarter end (configurable). Long-term backtests must be labelled as approximate until our own snapshot history builds up.
- Nightly ingest runs after both exchanges publish bhavcopy (evening IST); make it idempotent and re-runnable for any date range, with a backfill command.

## 5. Strategies — four horizons

Horizon definitions (holding windows are config):
- **Short-term:** 1–10 trading days.
- **Swing:** 2–6 weeks.
- **Momentum:** 1–3 months.
- **Long-term:** 1 year+.

Seed strategies (starting set; all expressed in the strategy DSL below):
- **Short-term:** volume breakout with high delivery %; gap-and-hold; oversold bounce near support.
- **Swing:** pullback to 20/50 EMA inside an uptrend; breakout from tight consolidation; RSI reset in an uptrend.
- **Momentum:** relative strength vs Nifty 500; proximity to 52-week high; 12-minus-1-month return.
- **Long-term:** quality + growth + valuation — ROCE, debt/equity, sales & profit CAGR, promoter holding and pledge %, P/E vs the stock's own history.

**Strategy DSL:** strategies are **structured JSON rules** (universe filters, entry conditions, exit rules: stop, target, time-based exit, ranking/score), interpreted by our engine. **Never execute AI-generated code.** Validate every strategy against a JSON schema; reject unknown indicators/fields. Indicators and fundamental ratios are computed once in the pipeline and stored, so strategies are just rules over stored features.

Every pick carries: symbol/ISIN, horizon, strategy id, signal date, reference price, stop, target, holding window, score.

## 6. Backtest engine (rigorous)

- **Indian transaction costs:** STT, exchange transaction charges, SEBI turnover fee, stamp duty, GST, brokerage — differentiated for delivery vs intraday. **Put all rates in a config file and verify current rates before relying on them; do not hardcode from memory.**
- **Slippage** tiered by liquidity bucket (small/illiquid names penalised more).
- **Realistic fills:** signals generated on day T's close fill at **T+1 open**; a stock locked at upper circuit cannot be bought, lower circuit cannot be sold.
- **No look-ahead:** only data available as of each decision date (see fundamentals lag rule).
- **Walk-forward testing:** tune on one window, test on the next unseen window, roll forward across the history.
- **Metrics:** CAGR, total return, win rate, avg win/loss, profit factor, max drawdown, Sharpe, exposure, trade count, benchmark comparison (Nifty 500), per-window results.
- **Promotion gate:** a strategy goes live only if it beats its benchmark **after costs** in most out-of-sample windows and stays within a max-drawdown limit (thresholds in config). The same gate applies to seed and AI-proposed strategies — no exceptions.
- Store every run (strategy version, params, windows, metrics, equity curve, trade list) so results are reproducible and viewable in the UI.

## 7. Pick tracking (live forward test)

- Every pick issued by a live strategy is logged with its reference price, stop, target and holding window.
- Marked to market daily; closes on stop, target, or end of holding window.
- Per strategy, show **live return %, hit rate, average holding time** next to its backtest numbers.
- A large gap between live and backtest performance flags the strategy as **decaying**; the weekly strategy lab sees this and can recommend demotion (demotion itself requires my confirmation in the UI).
- Strategies do **not** get their own virtual portfolios — just per-pick return tracking.

## 8. Virtual playground (paper trading)

- **Portfolios:** multiple, each with its own starting virtual capital.
- **Order types:** market, limit, stop-loss, target — open orders persist until triggered or cancelled (GTT-like).
- **Near-live fills:** an intraday poller runs **9:15–15:30 IST on trading days** (use an exchange holiday calendar). Every few minutes it fetches **delayed 1- or 5-minute candles** for **only** the symbols with open orders or positions. An order fills if the candle's high/low **touched** its price (not just if the last price matched). Apply slippage + full charges (same cost model as backtests).
- **Mark every fill as "based on delayed data".** If the feed fails or data is stale, **do not fill at a stale price** — orders wait and fall back to end-of-day fill logic.
- **Positions & P&L:** holdings, avg cost, realised/unrealised P&L, total charges paid, trade history.
- **Corporate actions:** splits/bonuses adjust holdings; dividends credited as cash.
- **Journal:** a free-text note on each trade (why I entered/exited).
- **Performance:** returns vs Nifty 500, XIRR, max drawdown, win rate.
- **"Paper trade this"** button on every pick, pre-filling entry, stop and target from the strategy.

## 9. AI layer (Claude API)

- Model name is config (default to a current Sonnet-class model); API key from env.
- **Evening review** (after the nightly pipeline): ranks and explains the day's picks per horizon, flags conflicts (e.g. strong momentum but deteriorating fundamentals), comments on my open playground positions, and writes a short **market brief**. Stored in DB, shown in the UI.
- **Weekly strategy lab:** receives current strategies, their backtest vs live performance, and decaying flags; proposes new strategies **as DSL JSON** and optional demotions. Proposals are schema-validated, then automatically backtested; only those that pass the promotion gate become candidates, which I approve in the UI.
- Request structured JSON output, strip code fences, validate, and handle failures gracefully (log + retry once; never block the pipeline).
- Log every call (tokens, cost estimate) to keep usage visible.

## 10. Screens (designs come from Claude Design)

- **Today:** picks grouped by horizon, each with strategy track record, AI reasoning, "Paper trade this".
- **Stock view:** chart, fundamentals, which strategies flagged it, any open paper positions/orders.
- **Strategy lab:** strategies (live / candidate / retired), backtest results, equity curves, live vs backtest, AI proposals to approve.
- **Market brief:** the evening AI summary.
- **Playground:** portfolios, positions, orders, order ticket, trade history + journal, performance.
- Global: market open/closed status, data freshness, "delayed ~15 min" indicator.

## 11. Build phases (do them in order; stop and check in with me after each)

0. **Repo & VM setup:** project structure, config system, `.env` handling, lint/format, tests, README. Give me step-by-step Oracle Always Free VM setup notes early (signup can take several attempts).
1. **Data pipeline + store:** NSE and BSE bhavcopy downloaders, ISIN mapping/dedup, liquidity filter, corporate-action adjustments, fundamentals adapter + quarterly snapshots, Parquet/DuckDB layout, backfill command.
2. **Backtest engine:** cost model, slippage, circuit rules, T+1 fills, walk-forward, metrics, stored runs. Write tests that prove there is no look-ahead.
3. **Seed strategies + DSL:** schema, interpreter, the four horizons' seed strategies, run them through the gate.
4. **API + dashboard with pick tracking:** FastAPI endpoints, front-end from the Claude Design handoff, TradingView widget test (fallback to Lightweight Charts if needed).
5. **Virtual playground:** portfolios, orders, fill engine, intraday poller service, corporate actions, journal, performance.
6. **AI evening review.**
7. **AI weekly strategy lab.**
8. **Deployment & hardening on the Oracle VM:** systemd services, cron, HTTPS, backups of Parquet + SQLite, logging, job-failure visibility in the UI.

## 12. How to work with me

- Start with **phase 0 and phase 1 only**. Propose the folder structure and data schemas first; wait for my OK before writing large amounts of code.
- Ask before choosing anything marked **OPEN** or anything that changes a decision above.
- Prefer boring, reliable code over clever code. Small modules, typed Python, docstrings, tests for anything financial (costs, fills, P&L, look-ahead).
- When a free source breaks or changes format, fail loudly with a clear error rather than silently producing wrong data.
- Keep this brief in the repo (e.g. `docs/PROJECT_BRIEF.md`) and reference it from `CLAUDE.md`; update it when we change a decision.

---

## Amendments (see docs/adr/ and docs/BUILD_PLAN.md for full detail)

This brief is kept as originally agreed. Decisions made or corrected during actual implementation are tracked separately rather than edited in above, so the history of *why* something changed stays visible:

- **Front-end (was OPEN):** React + Vite + TypeScript. See `docs/BUILD_PLAN.md`.
- **Fundamentals source:** NSE official JSON (`/api/corporates-*`) is the authoritative provider, not Screener.in — see `docs/data-sources.md`. yfinance remains as an approximate fallback.
- **NSE/BSE bhavcopy URLs:** the classic URLs referenced by "bhavcopy downloaders" folklore are dead (NSE retired the legacy path 2024-07-08). See `docs/data-sources.md` for the current, verified endpoints.
