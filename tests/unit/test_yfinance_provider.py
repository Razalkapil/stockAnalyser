"""Unit tests for the yfinance fallback provider.

Almost every test here is about a guard rather than a feature. This
provider serves approximate, restated, survivorship-biased prices with
no point-in-time knowledge date; the valuable behaviour is that it
says so, refuses what it cannot honestly do, and cannot be reached by
accident.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pandas as pd
import pytest

from stk.config.settings import get_settings
from stk.core.errors import ConfigError, DataNotPublished, NotSupportedError, ProviderUnavailable
from stk.providers.base import Interval
from stk.providers.registry import get_price_provider
from stk.providers.yfinance.prices import YFinancePriceProvider, ticker_for


@pytest.fixture
def provider() -> YFinancePriceProvider:
    return YFinancePriceProvider()


@pytest.fixture
def enabled(monkeypatch):
    """Turn the feature flag on for tests that need the provider built.

    get_settings() is a process-wide singleton, so it must be forced to
    reload both on the way in and on the way out -- otherwise the flag
    leaks into whichever test runs next.
    """
    monkeypatch.setenv("STK_PROVIDERS__ENABLE_YFINANCE_FALLBACK", "true")
    get_settings(force_reload=True)
    yield
    monkeypatch.delenv("STK_PROVIDERS__ENABLE_YFINANCE_FALLBACK", raising=False)
    get_settings(force_reload=True)


def _frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    index = pd.to_datetime([r.pop("date") for r in rows])
    return pd.DataFrame(rows, index=index)


class TestTickerMapping:
    def test_nse_uses_ns_suffix(self):
        assert ticker_for("RELIANCE", "NSE") == "RELIANCE.NS"

    def test_bse_uses_bo_suffix(self):
        assert ticker_for("500325", "BSE") == "500325.BO"

    def test_unknown_exchange_raises(self):
        with pytest.raises(ValueError, match="no yfinance ticker mapping"):
            ticker_for("RELIANCE", "MCX")


class TestCapabilities:
    def test_declares_itself_approximate(self, provider):
        """The flag the UI's `approx` badge and every backtest honesty
        check ultimately read."""
        assert provider.capabilities.is_approximate is True
        assert provider.capabilities.is_realtime is False
        assert provider.capabilities.supports_delivery is False


class TestUnsupportedOperations:
    def test_fetch_eod_raises_rather_than_returning_a_partial_market(self, provider):
        with pytest.raises(NotSupportedError, match="no whole-market EOD file"):
            provider.fetch_eod(date(2026, 9, 17), "NSE")

    def test_parse_eod_raises(self, provider):
        with pytest.raises(NotSupportedError):
            list(provider.parse_eod(None))  # type: ignore[arg-type]

    def test_intraday_interval_raises(self, provider):
        with pytest.raises(NotSupportedError, match="daily bars only"):
            provider.fetch_history(
                "RELIANCE", "NSE", date(2026, 9, 1), date(2026, 9, 17), Interval.MIN_5
            )


class TestFetchHistory:
    def _run(self, provider, frame):
        with (
            patch("stk.providers.yfinance.session.throttle"),
            patch("stk.providers.yfinance.session.build_session", return_value=object()),
            patch("yfinance.Ticker") as ticker_cls,
        ):
            ticker_cls.return_value.history.return_value = frame
            return provider.fetch_history(
                "RELIANCE", "NSE", date(2026, 9, 16), date(2026, 9, 18)
            )

    def test_maps_rows_to_canonical_bars(self, provider, enabled):
        frame = _frame(
            [
                {
                    "date": "2026-09-17", "Open": 100.0, "High": 105.0,
                    "Low": 99.0, "Close": 102.0, "Volume": 1000,
                }
            ]
        )
        bars = self._run(provider, frame)

        assert len(bars) == 1
        bar = bars[0]
        assert bar.date == date(2026, 9, 17)
        assert bar.symbol == "RELIANCE"
        assert bar.close == Decimal("102.0")
        assert bar.source == "yfinance"

    def test_turnover_is_a_derived_approximation(self, provider, enabled):
        """Yahoo reports no rupee turnover. close*volume is derived and
        must never be compared to a bhavcopy turnover as an equal."""
        frame = _frame(
            [
                {
                    "date": "2026-09-17", "Open": 100.0, "High": 105.0,
                    "Low": 99.0, "Close": 102.0, "Volume": 1000,
                }
            ]
        )
        bars = self._run(provider, frame)
        assert bars[0].turnover == Decimal("102.0") * 1000

    def test_no_delivery_data_is_reported(self, provider, enabled):
        frame = _frame(
            [
                {
                    "date": "2026-09-17", "Open": 100.0, "High": 105.0,
                    "Low": 99.0, "Close": 102.0, "Volume": 1000,
                }
            ]
        )
        assert self._run(provider, frame)[0].delivery_qty is None

    def test_an_empty_frame_raises_rather_than_looking_like_no_trading(
        self, provider, enabled
    ):
        """An empty result means a wrong ticker, a delisted name, or a
        rate limit -- never 'this symbol did not trade'."""
        with pytest.raises(DataNotPublished, match="wrong ticker mapping"):
            self._run(provider, pd.DataFrame())

    def test_an_upstream_error_becomes_provider_unavailable(self, provider, enabled):
        with (
            patch("stk.providers.yfinance.session.throttle"),
            patch("stk.providers.yfinance.session.build_session", return_value=object()),
            patch("yfinance.Ticker", side_effect=RuntimeError("rate limited")),
            pytest.raises(ProviderUnavailable, match="rate limited"),
        ):
            provider.fetch_history("RELIANCE", "NSE", date(2026, 9, 1), date(2026, 9, 17))


class TestFeatureFlag:
    def test_registry_refuses_to_build_it_by_default(self, monkeypatch):
        """It cannot drift onto the critical path just by being named
        in a config list."""
        monkeypatch.delenv("STK_PROVIDERS__ENABLE_YFINANCE_FALLBACK", raising=False)
        get_settings(force_reload=True)
        with pytest.raises(ConfigError, match="enable_yfinance_fallback"):
            get_price_provider("yfinance")

    def test_registry_builds_it_when_explicitly_enabled(self, enabled):
        assert isinstance(get_price_provider("yfinance"), YFinancePriceProvider)


@pytest.mark.live
class TestLiveEndpoint:
    def test_single_symbol_smoke(self, provider, enabled):
        bars = provider.fetch_history("RELIANCE", "NSE", date(2026, 9, 1), date(2026, 9, 18))
        assert bars
        assert all(b.close > 0 for b in bars)
