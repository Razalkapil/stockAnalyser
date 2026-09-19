"""Delayed intraday candles from Yahoo Finance, for the paper-trading poller ONLY.

Yahoo is approximate, ~15 minutes delayed, unofficial and rate-limited. It is acceptable here
because the playground's contract with the user is explicit: every fill made from this feed is
stamped ``delayed_intraday`` and shown as such, and when the feed is stale nothing fills and
the order falls back to the end-of-day bar. It must NEVER feed the EOD pipeline or a backtest --
which is why this is a separate ``IntradayProvider`` behind its own config switch
(``providers.enable_yfinance_intraday``), independent of ``enable_yfinance_fallback``.

RAW BYTES FIRST. ``fetch_candles_raw`` returns the candles as JSON bytes exactly as fetched;
``parse_candles`` is a pure function of those bytes, so a parser fix never needs the network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from stk.core.errors import DataNotPublished, ProviderUnavailable
from stk.core.time import IST
from stk.providers.base import (
    IntradayCandle,
    IntradayProvider,
    ProviderCapabilities,
    RawArtifact,
)
from stk.providers.yfinance.prices import ticker_for

SOURCE = "yfinance_intraday"
_SUPPORTED_INTERVALS = {"1m", "5m", "15m"}


class YFinanceIntradayProvider(IntradayProvider):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=SOURCE, exchanges=frozenset({"NSE", "BSE"}), supports_intraday=True,
            is_approximate=True, is_realtime=False,
        )

    def fetch_candles_raw(self, symbol: str, exchange: str, interval: str = "5m") -> RawArtifact:
        if interval not in _SUPPORTED_INTERVALS:
            raise ValueError(f"interval must be one of {sorted(_SUPPORTED_INTERVALS)}, "
                             f"got {interval!r}")
        from stk.providers.yfinance.session import build_session, throttle  # noqa: PLC0415

        ticker_symbol = ticker_for(symbol, exchange)
        throttle()
        try:
            import yfinance  # noqa: PLC0415

            frame = yfinance.Ticker(ticker_symbol, session=build_session()).history(
                period="1d", interval=interval, auto_adjust=False, actions=False)
        # yfinance raises a wide, unstable set of exception types; all mean "no feed" here.
        except Exception as exc:
            raise ProviderUnavailable(
                f"yfinance intraday failed for {ticker_symbol}: {type(exc).__name__}: {exc}"
            ) from exc
        if frame is None or frame.empty:
            raise DataNotPublished(
                f"yfinance returned no intraday candles for {ticker_symbol} -- outside market "
                "hours, a wrong ticker mapping, or a rate limit"
            )

        records = [
            {"ts": ts.isoformat(), "o": str(row["Open"]), "h": str(row["High"]),
             "l": str(row["Low"]), "c": str(row["Close"]), "v": int(row["Volume"])}
            for ts, row in frame.iterrows()
        ]
        body = json.dumps({"symbol": symbol, "exchange": exchange, "interval": interval,
                           "ticker": ticker_symbol, "candles": records}).encode()
        return RawArtifact(
            source=SOURCE, business_date=None, url=f"yfinance://{ticker_symbol}/{interval}",
            content=body, content_type="application/json", http_status=200,
            fetched_at=datetime.now(UTC),
        )

    def parse_candles(self, artifact: RawArtifact) -> list[IntradayCandle]:
        return parse_candles_json(artifact.content)


def parse_candles_json(content: bytes) -> list[IntradayCandle]:
    """Pure: bytes -> candles, sorted by start, in IST. Rejects a malformed record loudly."""
    try:
        doc = json.loads(content)
        raw = doc["candles"]
    except (ValueError, KeyError, TypeError) as exc:
        raise DataNotPublished(f"unreadable intraday payload: {exc}") from exc
    out: list[IntradayCandle] = []
    for rec in raw:
        ts = datetime.fromisoformat(rec["ts"])
        if ts.tzinfo is None:
            raise DataNotPublished(f"intraday candle {rec['ts']!r} has no timezone")
        out.append(IntradayCandle(
            start=ts.astimezone(IST), open=Decimal(rec["o"]), high=Decimal(rec["h"]),
            low=Decimal(rec["l"]), close=Decimal(rec["c"]), volume=int(rec["v"]),
        ))
    return sorted(out, key=lambda c: c.start)
