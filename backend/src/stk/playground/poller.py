"""The intraday poller: fetch delayed candles, decide if the feed is alive, fill or park.

One ``poll_once`` does, in order:
  1. find the symbols that need candles (an active order or an open position);
  2. fetch each, persisting the RAW bytes before parsing (re-parse never needs the network);
  3. judge the feed: no candles, a failed fetch, or a newest candle whose END is older than
     ``stale_after_s`` all mean STALE;
  4. stale  -> park the affected orders as ``pending_eod`` and fill NOTHING (a fill on stale
     data would present a delayed guess as a real execution);
     alive  -> run the intraday fill pass, stamping every fill with the feed's lag.

Every poll leaves a ``poller_runs`` row, so an outage is visible after the fact rather than
being an absence of fills nobody can tell apart from a quiet market.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import structlog

from stk.config.playground import PollerConfig
from stk.core.errors import ProviderError
from stk.core.time import is_market_hours, now_ist
from stk.ingest.calendar import is_trading_day
from stk.ingest.raw_store import persist_document
from stk.playground import marketdata
from stk.playground.context import EXCHANGE, PlayCtx
from stk.playground.ledger import iso
from stk.playground.passes import active_symbols, intraday_pass, mark_pending_eod
from stk.providers.base import IntradayCandle, IntradayProvider

log = structlog.get_logger(__name__)


@dataclass
class PollOutcome:
    status: str  # ok | stale | failed | idle
    symbols: int = 0
    fills: int = 0
    newest_candle: datetime | None = None
    lag_s: int | None = None
    parked: int = 0
    errors: list[str] = field(default_factory=list)


def _record(conn: sqlite3.Connection, started: datetime, out: PollOutcome) -> None:
    conn.execute(
        """INSERT INTO poller_runs (started_at, finished_at, symbols, fills, status, newest_candle,
               lag_s, error) VALUES (?,?,?,?,?,?,?,?)""",
        (iso(started), iso(now_ist()), out.symbols, out.fills, out.status,
         iso(out.newest_candle) if out.newest_candle else None, out.lag_s,
         "; ".join(out.errors)[:500] or None),
    )


def poll_once(
    conn: sqlite3.Connection,
    ctx: PlayCtx,
    provider: IntradayProvider,
    *,
    raw_root: Path,
    cfg: PollerConfig,
    now: datetime | None = None,
) -> PollOutcome:
    now = now or now_ist()
    symbols = active_symbols(conn)
    out = PollOutcome(status="idle", symbols=len(symbols))
    if not symbols:
        _record(conn, now, out)
        return out

    candles: dict[str, list[IntradayCandle]] = {}
    failed: list[str] = []
    for sym in symbols:
        try:
            art = provider.fetch_candles_raw(sym, EXCHANGE, cfg.interval)
            persist_document(raw_root, conn, art)  # raw bytes on disk BEFORE parsing
            candles[sym] = provider.parse_candles(art)
        except ProviderError as exc:
            failed.append(sym)
            out.errors.append(f"{sym}: {exc}")
            log.warning("intraday_fetch_failed", symbol=sym, error=str(exc))

    span = timedelta(minutes=cfg.interval_minutes)
    ends = [max(c.start for c in cs) + span for cs in candles.values() if cs]
    if ends:
        out.newest_candle = max(ends)
        out.lag_s = int((now - max(ends)).total_seconds())

    # Judge each symbol on ITS OWN newest candle: one delisted ticker with no candles must not
    # park every other symbol's orders.
    fresh: dict[str, list[IntradayCandle]] = {}
    stale_symbols = list(failed)
    for sym, cs in candles.items():
        if not cs or (now - (max(c.start for c in cs) + span)).total_seconds() > cfg.stale_after_s:
            stale_symbols.append(sym)
        else:
            fresh[sym] = cs

    if stale_symbols:
        out.parked = mark_pending_eod(conn, stale_symbols)
    if fresh:
        day = now.date()
        prev = day - timedelta(days=1)
        closes = marketdata.last_closes(ctx.parquet_root, ctx.cfg, list(fresh), prev)
        result = intraday_pass(
            conn, ctx, fresh, feed_source=provider.capabilities.name,
            feed_lag_s=max(out.lag_s or 0, 0), candle_minutes=cfg.interval_minutes,
            prev_close={s: c[1] for s, c in closes.items()},
            adv=marketdata.adv_turnover(ctx.parquet_root, ctx.cfg, list(fresh), prev),
        )
        out.fills = result.fills
    out.status = "stale" if stale_symbols and not fresh else "ok"
    _record(conn, now, out)
    return out


def market_is_open(conn: sqlite3.Connection, now: datetime) -> bool:
    """Trading day per the calendar (unknown counts as open on weekdays) and 09:15-15:30 IST."""
    known = is_trading_day(conn, now.date(), EXCHANGE)
    trading = known is True or (known is None and now.weekday() < 5)
    return trading and is_market_hours(now)


def run_forever(conn: sqlite3.Connection, ctx: PlayCtx, provider: IntradayProvider, *,
                raw_root: Path, cfg: PollerConfig, once: bool = False) -> None:
    """Poll every ``poll_every_s`` while the market is open; idle (cheaply) otherwise."""
    while True:
        now = now_ist()
        if market_is_open(conn, now):
            out = poll_once(conn, ctx, provider, raw_root=raw_root, cfg=cfg, now=now)
            log.info("poll", status=out.status, symbols=out.symbols, fills=out.fills,
                     lag_s=out.lag_s, parked=out.parked)
            wait = cfg.poll_every_s
        else:
            if once:
                log.info("market_closed", now=now.isoformat())
            wait = 60  # cheap wake-ups; opening is detected within a minute
        if once:
            return
        time.sleep(wait)
