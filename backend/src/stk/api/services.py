"""Build API responses from the SQLite ledger and the parquet lake.

Kept out of the route functions so each can be tested without HTTP. Nothing here calls the
network, an LLM, or writes anything (the two write paths -- approve/retire -- live in
``routes`` and go through ``strategies.repo.set_status`` so every change is audited).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from stk.api import schemas as s
from stk.config.backtest import BacktestConfig
from stk.core.time import MARKET_CLOSE, MARKET_OPEN, is_market_hours, now_ist
from stk.domain.dsl.evaluate import explain
from stk.ingest.calendar import is_trading_day
from stk.ingest.fundamentals_metrics import load_metric_frame
from stk.store import duck
from stk.strategies.proposals import list_proposals
from stk.strategies.repo import StrategyRow, get_strategy, list_strategies, load_spec
from stk.strategies.stats import BacktestStats, LiveStats, backtest_stats, live_stats

EXCHANGE = "NSE"
INGEST_JOB = "ingest_nse_prices"
#: A day's bhavcopy is not expected before this IST hour (config: ingest.eod_publish_time_ist).
EOD_READY_HOUR = 18
BRIEF_DAYS_SHOWN = 14


# --- status --------------------------------------------------------------------------------


def latest_bar_date(parquet_root: Path) -> date | None:
    with duck.connect(parquet_root) as session:
        row = session.con.execute(
            "SELECT max(date) FROM bars_daily WHERE exchange = ?", [EXCHANGE]
        ).fetchone()
    return row[0] if row and row[0] else None


def expected_data_date(conn: sqlite3.Connection, now: datetime) -> date:
    """The most recent trading day whose bhavcopy should already be out.

    Unknown calendar days count as trading days on weekdays -- the same tri-state rule the
    ingest uses (unknown is never treated as a holiday).
    """
    d = now.date()
    if now.hour < EOD_READY_HOUR:
        d -= timedelta(days=1)
    for _ in range(14):
        known = is_trading_day(conn, d, EXCHANGE)
        if known is True or (known is None and d.weekday() < 5):
            return d
        d -= timedelta(days=1)
    return d


def build_status(conn: sqlite3.Connection, parquet_root: Path) -> s.Status:
    now = now_ist()
    today_known = is_trading_day(conn, now.date(), EXCHANGE)
    trading_today = today_known is True or (today_known is None and now.weekday() < 5)
    open_now = trading_today and is_market_hours(now)
    if open_now:
        label = "Market open"
    elif not trading_today:
        label = "Market closed (holiday or weekend)"
    elif now.time() < MARKET_OPEN:
        label = "Market opens 09:15 IST"
    elif now.time() > MARKET_CLOSE:
        label = "Market closed"
    else:
        label = "Market closed"

    as_of = latest_bar_date(parquet_root)
    return s.Status(
        now_ist=now.isoformat(timespec="seconds"),
        market_open=open_now,
        market_label=label,
        data_as_of=as_of.isoformat() if as_of else None,
        # There is no intraday feed until the playground poller exists; quotes are end-of-day.
        delayed_feed=s.DelayedFeed(lag_minutes=15, stale=False) if open_now else None,
        stale_warning=_stale_warning(conn, as_of, expected_data_date(conn, now)),
    )


def _stale_warning(
    conn: sqlite3.Connection, as_of: date | None, expected: date
) -> s.StaleWarning | None:
    """Warn when the data is behind where the calendar says it should be.

    Judged on the DATA, not on job rows alone: if the timer never fired there is no failed
    job_runs row at all, and a status page that only reads failures would say all is well.
    """
    if as_of is not None and as_of >= expected:
        return None
    failed = conn.execute(
        """SELECT business_date, error_message, started_at FROM job_runs
           WHERE job_name=? AND status IN ('failed','degraded') AND business_date >= ?
           ORDER BY started_at DESC LIMIT 1""",
        (INGEST_JOB, expected.isoformat()),
    ).fetchone()
    behind = f"latest data is {as_of.isoformat()}" if as_of else "no price data yet"
    detail = f" Last error: {failed['error_message']}" if failed and failed["error_message"] else ""
    return s.StaleWarning(
        job=INGEST_JOB,
        since=failed["started_at"] if failed else None,
        message=f"Price data should be through {expected.isoformat()}, but {behind}.{detail}",
    )


# --- strategies ----------------------------------------------------------------------------


def _summary(row: StrategyRow, bt: BacktestStats, live: LiveStats) -> s.StrategySummary:
    return s.StrategySummary(
        id=row.slug, name=row.name, horizon=row.horizon, status=row.status,
        status_reason=row.status_reason, origin=row.origin,
        bt_cagr=bt.cagr, win_rate=bt.win_rate, max_dd=bt.max_drawdown, sharpe=bt.sharpe,
        trades=bt.trades, live_return=live.live_return, hit_rate=live.hit_rate,
        live_closed=live.closed,
        avg_hold=live.avg_hold_days if live.avg_hold_days is not None else bt.avg_hold_days,
        approx=bt.is_approximate or bt.run_id is None, gate_verdict=bt.gate_verdict,
    )


def list_strategy_summaries(conn: sqlite3.Connection) -> list[s.StrategySummary]:
    out = []
    for row in list_strategies(conn):
        out.append(_summary(row, backtest_stats(conn, row.slug), live_stats(conn, row.strategy_id)))
    return out


def _trade_list(conn: sqlite3.Connection, row: StrategyRow, bt: BacktestStats
                ) -> tuple[list[s.TradeRow], str]:
    live = conn.execute(
        """SELECT p.symbol, o.exit_date AS d, o.net_return AS r FROM pick_outcomes o
           JOIN picks p ON p.pick_id = o.pick_id
           WHERE p.strategy_id=? AND o.exit_reason != 'void' AND o.exit_date IS NOT NULL
           ORDER BY o.exit_date DESC LIMIT 12""", (row.strategy_id,)).fetchall()
    if live:
        return [s.TradeRow(symbol=r["symbol"], date=r["d"], ret=r["r"]) for r in live], "live"
    if bt.run_id is None:
        return [], "none"
    bt_rows = conn.execute(
        """SELECT symbol, exit_date AS d, return_pct AS r FROM backtest_trades
           WHERE run_id=? ORDER BY exit_date DESC LIMIT 12""", (bt.run_id,)).fetchall()
    return [s.TradeRow(symbol=r["symbol"], date=r["d"], ret=r["r"]) for r in bt_rows], "backtest"


def strategy_detail(conn: sqlite3.Connection, slug: str) -> s.StrategyDetail | None:
    row = get_strategy(conn, slug)
    if row is None:
        return None
    bt, live = backtest_stats(conn, slug), live_stats(conn, row.strategy_id)
    spec = load_spec(conn, row.latest_version_id)
    trades, source = _trade_list(conn, row, bt)
    return s.StrategyDetail(
        **_summary(row, bt, live).model_dump(),
        notes=spec.notes,
        rules=explain(spec),
        approx_reasons=bt.approx_reasons
        + ([] if bt.run_id is not None else ["not yet backtested"]),
        curve_dates=bt.curve_dates,
        equity_curve=bt.equity_curve,
        nifty_curve=bt.benchmark_curve,
        walk_forward=[
            s.WalkForwardWindow(label=w["label"], result=w["result"], test_start=w["test_start"],
                                test_end=w["test_end"], strat_return=w["strat_return"],
                                bench_return=w["bench_return"])
            for w in bt.windows
        ],
        trade_list=trades, trade_list_source=source,
    )


# --- proposals -----------------------------------------------------------------------------


def proposal_list(conn: sqlite3.Connection) -> list[s.ProposalOut]:
    out: list[s.ProposalOut] = []
    for p in list_proposals(conn):
        bt = backtest_stats(conn, p.strategy_slug) if p.strategy_slug else None
        rules: list[str] = []
        if p.strategy_slug:
            row = get_strategy(conn, p.strategy_slug)
            if row is not None:
                rules = explain(load_spec(conn, row.latest_version_id))
        out.append(s.ProposalOut(
            id=p.proposal_id, type=p.type, title=p.title, rationale=p.rationale, status=p.status,
            status_note=p.status_note, date=p.business_date, target_strategy=p.target_slug,
            strategy_id=p.strategy_slug, rules=rules, validation_errors=p.validation_errors,
            gate_verdict=p.gate_verdict, bt_cagr=bt.cagr if bt else None,
            bt_win_rate=bt.win_rate if bt else None, bt_max_dd=bt.max_drawdown if bt else None,
            approx=(bt.is_approximate or bt.run_id is None) if bt else False,
            approx_reasons=bt.approx_reasons if bt else []))
    return out


# --- picks ---------------------------------------------------------------------------------


def latest_pick_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(signal_date) AS d FROM picks").fetchone()
    return row["d"] if row and row["d"] else None


def _company_names(conn: sqlite3.Connection, symbols: set[str]) -> dict[str, str]:
    if not symbols:
        return {}
    marks = ",".join("?" * len(symbols))
    rows = conn.execute(
        f"""SELECT l.symbol, s.company_name FROM listings l
            JOIN securities s ON s.security_id = l.security_id
            WHERE l.exchange = ? AND l.symbol IN ({marks})""",
        (EXCHANGE, *sorted(symbols)),
    ).fetchall()
    return {r["symbol"]: r["company_name"] for r in rows}


def list_picks(conn: sqlite3.Connection, on: str | None, horizon: str | None) -> list[s.Pick]:
    day = on or latest_pick_date(conn)
    if day is None:
        return []
    sql = ["""SELECT p.*, st.slug, st.name AS strategy_name,
                     (SELECT net_return FROM pick_marks m WHERE m.pick_id = p.pick_id
                      ORDER BY m.date DESC LIMIT 1) AS last_return
              FROM picks p JOIN strategies st ON st.strategy_id = p.strategy_id
              WHERE p.signal_date = ?"""]
    args: list[object] = [day]
    if horizon:
        sql.append("AND p.horizon = ?")
        args.append(horizon)
    sql.append("ORDER BY p.horizon, p.score DESC")
    rows = conn.execute(" ".join(sql), args).fetchall()

    names = _company_names(conn, {r["symbol"] for r in rows})
    bt_cache: dict[str, tuple[BacktestStats, LiveStats]] = {}
    picks: list[s.Pick] = []
    for r in rows:
        if r["slug"] not in bt_cache:
            bt_cache[r["slug"]] = (backtest_stats(conn, r["slug"]),
                                   live_stats(conn, r["strategy_id"]))
        bt, live = bt_cache[r["slug"]]
        picks.append(s.Pick(
            id=r["pick_id"], symbol=r["symbol"], company=names.get(r["symbol"], r["symbol"]),
            exch=r["exchange"], sector=None, horizon=r["horizon"], strategy=r["strategy_name"],
            strategy_id=r["slug"], score=r["score"], ref=r["ref_price"], stop=r["stop_price"],
            target=r["target_price"], window=f"up to {r['hold_days']} trading days",
            hold_days=r["hold_days"], signal_date=r["signal_date"], status=r["status"],
            pick_return=r["last_return"], bt_cagr=bt.cagr, bt_win_rate=bt.win_rate,
            live_return=live.live_return, hit_rate=live.hit_rate,
            approx=bt.is_approximate or bt.run_id is None,
            reason=r["ai_reason"] or r["reason"], conflict=r["conflict"],
        ))
    return picks


# --- stocks --------------------------------------------------------------------------------


def search_stocks(conn: sqlite3.Connection, q: str, limit: int = 15) -> list[s.StockHit]:
    q = q.strip()
    if len(q) < 1:
        return []
    like_prefix, like_any = f"{q.upper()}%", f"%{q}%"
    rows = conn.execute(
        """SELECT canonical_symbol AS symbol, company_name AS company,
                  primary_exchange AS exch, isin
           FROM securities
           WHERE status = 'ACTIVE' AND (canonical_symbol LIKE ? OR company_name LIKE ?)
           ORDER BY (canonical_symbol = ?) DESC, (canonical_symbol LIKE ?) DESC, canonical_symbol
           LIMIT ?""",
        (like_prefix, like_any, q.upper(), like_prefix, limit),
    ).fetchall()
    return [s.StockHit(**dict(r)) for r in rows]


def _fundamentals_for(conn: sqlite3.Connection, symbol: str, lag_days: int
                      ) -> s.Fundamentals | None:
    frame = load_metric_frame(conn, lag_days)
    if frame.empty:
        return None
    mine = frame[frame["symbol"] == symbol].sort_values("available_on")
    if mine.empty:
        return None
    last = mine.iloc[-1]

    def num(key: str) -> float | None:
        return None if pd.isna(last[key]) else float(last[key])

    return s.Fundamentals(
        as_of=pd.Timestamp(last["available_on"]).date().isoformat(),
        roce=num("roce"), de_ratio=num("de_ratio"), sales_cagr3=num("sales_cagr3"),
        profit_cagr3=num("profit_cagr3"), eps_ttm=num("eps_ttm"), approx=True,
        note="Parsed from NSE XBRL filings. Shallow history, so multi-year figures are often "
             "missing; a blank means not computable, not zero.",
    )


def stock_detail(conn: sqlite3.Connection, parquet_root: Path, cfg: BacktestConfig,
                 symbol: str) -> s.StockDetail | None:
    sec = conn.execute(
        """SELECT canonical_symbol, company_name, primary_exchange, isin FROM securities
           WHERE canonical_symbol = ? ORDER BY (status='ACTIVE') DESC LIMIT 1""",
        (symbol.upper(),)).fetchone()
    if sec is None:
        return None
    sym = sec["canonical_symbol"]

    end = latest_bar_date(parquet_root)
    last_close = change = None
    last_date: str | None = None
    if end is not None:
        with duck.connect(parquet_root) as session:
            rows = session.con.execute(
                """SELECT date, close FROM bars_daily
                   WHERE exchange=? AND symbol=? AND series IN (SELECT unnest(?::VARCHAR[]))
                   ORDER BY date DESC LIMIT 2""",
                [EXCHANGE, sym, cfg.tradeable_series]).fetchall()
        if rows:
            last_close, last_date = float(rows[0][1]), rows[0][0].isoformat()
            if len(rows) > 1 and rows[1][1]:
                change = (rows[0][1] / rows[1][1] - 1.0) * 100.0

    flagged = conn.execute(
        """SELECT st.name, st.slug, p.horizon, p.signal_date, p.status FROM picks p
           JOIN strategies st ON st.strategy_id = p.strategy_id
           WHERE p.symbol = ? ORDER BY p.signal_date DESC LIMIT 10""", (sym,)).fetchall()
    return s.StockDetail(
        symbol=sym, company=sec["company_name"], exch=sec["primary_exchange"], isin=sec["isin"],
        tv_symbol=f"{sec['primary_exchange']}:{sym}", last_close=last_close, change_pct=change,
        last_date=last_date, fundamentals=_fundamentals_for(conn, sym, cfg.fundamentals_lag_days),
        flagged_by=[s.FlaggedBy(strategy=r["name"], strategy_id=r["slug"], horizon=r["horizon"],
                                signal_date=r["signal_date"], status=r["status"])
                    for r in flagged],
    )


def stock_bars(parquet_root: Path, cfg: BacktestConfig, symbol: str, start: date, end: date
               ) -> list[s.Bar]:
    with duck.connect(parquet_root) as session:
        frame = session.sql(
            "panel_for_symbols",
            [cfg.tradeable_series, [symbol.upper()], EXCHANGE, start.isoformat(), end.isoformat()],
        ).df()
    return [
        s.Bar(time=pd.Timestamp(r.date).date().isoformat(), open=float(r.open),
              high=float(r.high), low=float(r.low), close=float(r.close), volume=int(r.volume))
        for r in frame.sort_values("date").itertuples()
    ]


# --- briefs --------------------------------------------------------------------------------
# Written by the evening AI review (stk.ai) and read here. The API never calls the model: it only
# serves what is stored, and a day with no brief is honestly "pending".


def _brief_dates(conn: sqlite3.Connection) -> set[str]:
    return {r["business_date"] for r in conn.execute(
        "SELECT DISTINCT business_date FROM ai_outputs WHERE kind='brief'")}


def list_briefs(conn: sqlite3.Connection) -> list[s.BriefListItem]:
    have = _brief_dates(conn)
    today = now_ist().date()
    days = [today - timedelta(days=i) for i in range(BRIEF_DAYS_SHOWN)]
    return [
        s.BriefListItem(date=d.isoformat(), pending=d.isoformat() not in have)
        for d in days
        if d.isoformat() in have
        or (is_trading_day(conn, d, EXCHANGE) is not False and d.weekday() < 5)
    ]


def get_brief(conn: sqlite3.Connection, day: str) -> s.Brief:
    row = conn.execute(
        "SELECT payload_json, created_at FROM ai_outputs WHERE kind='brief' AND business_date=? "
        "ORDER BY output_id DESC LIMIT 1", (day,)).fetchone()
    if row is None:
        return s.Brief(date=day, pending=True, generated_at=None, overview="", notable_picks=[],
                       conflicts=[], position_notes=[])
    p = json.loads(row["payload_json"])
    return s.Brief(
        date=day, pending=False, generated_at=row["created_at"], overview=p["overview"],
        notable_picks=[{"symbol": n["symbol"], "note": n["note"]} for n in p["notable_picks"]],
        conflicts=list(p["conflicts"]),
        position_notes=[{"symbol": n["symbol"], "note": n["note"]} for n in p["position_notes"]],
    )
