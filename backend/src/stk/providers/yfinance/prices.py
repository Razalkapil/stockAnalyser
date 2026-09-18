"""yfinance price provider -- approximate history, never the critical path.

WHAT THIS IS FOR. Filling a hole the official archives cannot: a
symbol's history before an exchange archive starts, or a spot check
against bhavcopy. It is NOT a substitute for bhavcopy and the registry
refuses to build it unless explicitly enabled.

WHAT IT CANNOT DO, declared rather than discovered:

  - **No fetch_eod.** There is no whole-market file; Yahoo is
    per-symbol. Calling it raises NotSupportedError rather than
    returning a partial market.
  - **is_approximate=True.** Yahoo serves restated, split-adjusted
    prices with no point-in-time knowledge date, so a backtest using
    them cannot honestly claim "this is what you would have seen".
  - **No delivery data, no rupee turnover.** Two inputs the short-term
    seed strategies actually need.
  - **Survivorship bias.** Delisted names are simply absent, which
    quietly flatters any backtest built on a universe derived from it.

TICKER MAPPING: `SYMBOL.NS` for NSE, `SCRIPCODE.BO` for BSE. The BSE
form takes a numeric scrip code, not a symbol -- BSE's legacy bhavcopy
identifies securities by scrip code too (ADR 0003), so callers holding
a BSE "symbol" from that source can pass it through. A wrong mapping
surfaces as an empty result, not an error, which is why
fetch_history raises on an empty frame rather than returning [].
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

from stk.core.errors import DataNotPublished, NotSupportedError, ProviderUnavailable
from stk.providers.base import (
    CanonicalBar,
    Interval,
    PriceProvider,
    ProviderCapabilities,
    RawArtifact,
)

SOURCE = "yfinance"

#: Yahoo's Indian equity history is deep but unverified. No earliest
#: date is claimed rather than asserting one we have not probed.
EARLIEST_DATE = None


def ticker_for(symbol: str, exchange: str) -> str:
    """Yahoo ticker for an Indian listing."""
    if exchange == "NSE":
        return f"{symbol}.NS"
    if exchange == "BSE":
        return f"{symbol}.BO"
    raise ValueError(f"no yfinance ticker mapping for exchange {exchange!r}")


class YFinancePriceProvider(PriceProvider):
    """PriceProvider backed by Yahoo Finance. Approximate; feature-flagged."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=SOURCE,
            exchanges=frozenset({"NSE", "BSE"}),
            earliest_date=EARLIEST_DATE,
            supports_delivery=False,
            supports_intraday=True,
            is_approximate=True,
            is_realtime=False,
        )

    def fetch_eod(self, business_date: date, exchange: str) -> RawArtifact:
        raise NotSupportedError(
            "yfinance has no whole-market EOD file -- it is per-symbol. "
            "Use fetch_history for a single symbol, or a bhavcopy provider "
            "for a full trading day."
        )

    def parse_eod(self, artifact: RawArtifact) -> Iterator[CanonicalBar]:
        raise NotSupportedError(
            "yfinance produces bars directly from fetch_history; there is no "
            "raw artifact to re-parse"
        )

    def fetch_history(
        self,
        symbol: str,
        exchange: str,
        start: date,
        end: date,
        interval: Interval = Interval.DAY_1,
    ) -> list[CanonicalBar]:
        """Daily bars for one symbol. Raises rather than returning [].

        An empty frame from Yahoo means one of: a wrong ticker mapping,
        a delisted name, or a rate limit -- none of which should look
        like "this symbol didn't trade".
        """
        if interval is not Interval.DAY_1:
            raise NotSupportedError(
                f"yfinance provider supports daily bars only, got {interval}"
            )

        from stk.providers.yfinance.session import build_session, throttle  # noqa: PLC0415

        ticker_symbol = ticker_for(symbol, exchange)
        throttle()

        try:
            import yfinance  # noqa: PLC0415

            ticker = yfinance.Ticker(ticker_symbol, session=build_session())
            frame = ticker.history(
                start=start.isoformat(),
                end=end.isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
            )
        # yfinance raises a wide, unstable set of exception types; every
        # one of them means the same thing to a caller.
        except Exception as exc:
            raise ProviderUnavailable(
                f"yfinance failed for {ticker_symbol}: {type(exc).__name__}: {exc}"
            ) from exc

        if frame is None or frame.empty:
            raise DataNotPublished(
                f"yfinance returned no rows for {ticker_symbol} between {start} and {end} "
                "-- wrong ticker mapping, a delisted name, or a rate limit. "
                "Deliberately not treated as 'did not trade'."
            )

        bars: list[CanonicalBar] = []
        for index, row in frame.iterrows():
            close = Decimal(str(row["Close"]))
            bars.append(
                CanonicalBar(
                    date=index.date(),
                    exchange=exchange,
                    symbol=symbol,
                    instrument_type="EQ",
                    open=Decimal(str(row["Open"])),
                    high=Decimal(str(row["High"])),
                    low=Decimal(str(row["Low"])),
                    close=close,
                    volume=int(row["Volume"]),
                    # Yahoo reports no rupee turnover. close*volume is a
                    # DERIVED approximation, flagged by is_approximate --
                    # it is not the exchange's traded value and must never
                    # be compared to a bhavcopy turnover as though it were.
                    turnover=close * Decimal(int(row["Volume"])),
                    source=SOURCE,
                )
            )
        return bars
