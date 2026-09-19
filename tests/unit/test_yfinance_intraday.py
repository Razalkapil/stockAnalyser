"""The intraday provider: gated by its own switch, raw-bytes-first, and strict about time."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import yfinance

from stk.config.settings import get_settings
from stk.core.errors import ConfigError, DataNotPublished
from stk.core.time import IST
from stk.providers.base import IntradayCandle
from stk.providers.registry import get_intraday_provider, get_price_provider
from stk.providers.yfinance.intraday import YFinanceIntradayProvider, parse_candles_json


def payload(*candles: dict) -> bytes:
    return json.dumps({"symbol": "X", "exchange": "NSE", "candles": list(candles)}).encode()


def rec(ts: str, *, o="100", h="101", low="99", c="100.5", v=1000) -> dict:
    return {"ts": ts, "o": o, "h": h, "l": low, "c": c, "v": v}


class TestParse:
    def test_parses_and_converts_to_ist(self):
        # 03:45 UTC is 09:15 IST, the market open
        out = parse_candles_json(payload(rec("2026-09-18T03:45:00+00:00")))
        assert out[0].start == datetime(2026, 9, 18, 9, 15, tzinfo=IST)
        assert str(out[0].start.utcoffset()) == "5:30:00"

    def test_sorts_by_time_whatever_the_feed_order(self):
        out = parse_candles_json(payload(rec("2026-09-18T10:05:00+05:30"),
                                         rec("2026-09-18T09:15:00+05:30")))
        assert [c.start.hour * 60 + c.start.minute for c in out] == [9 * 60 + 15, 10 * 60 + 5]

    def test_prices_are_decimals_not_floats(self):
        c = parse_candles_json(payload(rec("2026-09-18T09:15:00+05:30", o="2945.35")))[0]
        assert str(c.open) == "2945.35"

    def test_a_naive_timestamp_is_refused(self):
        with pytest.raises(DataNotPublished, match="no timezone"):
            parse_candles_json(payload(rec("2026-09-18T09:15:00")))

    @pytest.mark.parametrize("bad", [b"", b"not json", b'{"nope": 1}', b"[]"])
    def test_garbage_is_a_loud_error(self, bad):
        with pytest.raises(DataNotPublished):
            parse_candles_json(bad)

    def test_the_candle_model_itself_rejects_naive_times(self):
        with pytest.raises(ValueError):
            IntradayCandle(start=datetime(2026, 9, 18, 9, 15), open=1, high=1, low=1, close=1)

    def test_any_offset_is_normalised(self):
        ist = parse_candles_json(payload(rec("2026-09-18T09:15:00+05:30")))[0].start
        utc = parse_candles_json(payload(rec("2026-09-18T03:45:00+00:00")))[0].start
        odd = parse_candles_json(payload(rec("2026-09-17T23:45:00-04:00")))[0].start
        assert ist == utc == odd


class FakeFrame:
    """Just enough of a pandas frame for fetch_candles_raw."""

    empty = False

    def iterrows(self):
        base = datetime(2026, 9, 18, 9, 15, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        for i in range(3):
            yield base + timedelta(minutes=5 * i), {
                "Open": 100 + i, "High": 101 + i, "Low": 99 + i, "Close": 100.5 + i, "Volume": 900}


class TestFetch:
    def patch_yf(self, monkeypatch, frame):
        class T:
            def __init__(self, *a, **k):
                pass

            def history(self, **k):
                return frame

        monkeypatch.setattr(yfinance, "Ticker", T)
        monkeypatch.setattr("stk.providers.yfinance.session.build_session", object)
        monkeypatch.setattr("stk.providers.yfinance.session.throttle", lambda: None)

    def test_raw_bytes_round_trip_through_the_parser(self, monkeypatch):
        self.patch_yf(monkeypatch, FakeFrame())
        p = YFinanceIntradayProvider()
        art = p.fetch_candles_raw("RELIANCE", "NSE")
        assert art.source == "yfinance_intraday" and art.url.endswith("RELIANCE.NS/5m")
        candles = p.parse_candles(art)
        assert len(candles) == 3 and candles[0].close == pytest.approx(100.5)

    def test_an_empty_frame_is_not_treated_as_no_trading(self, monkeypatch):
        class Empty:
            empty = True
        self.patch_yf(monkeypatch, Empty())
        with pytest.raises(DataNotPublished, match="no intraday candles"):
            YFinanceIntradayProvider().fetch_candles_raw("RELIANCE", "NSE")

    def test_an_unsupported_interval_is_rejected_before_any_network(self):
        with pytest.raises(ValueError, match="interval"):
            YFinanceIntradayProvider().fetch_candles_raw("RELIANCE", "NSE", "1h")

    def test_it_declares_itself_approximate_and_not_realtime(self):
        caps = YFinanceIntradayProvider().capabilities
        assert caps.is_approximate and not caps.is_realtime and caps.supports_intraday


@pytest.fixture
def switches(monkeypatch):
    """Set the two yfinance switches and force settings to re-read them; restore afterwards
    (settings are a process-wide cache, so a leaked value would poison later tests)."""

    def set_(*, intraday: bool, fallback: bool) -> None:
        monkeypatch.setenv("STK_PROVIDERS__ENABLE_YFINANCE_INTRADAY", str(intraday).lower())
        monkeypatch.setenv("STK_PROVIDERS__ENABLE_YFINANCE_FALLBACK", str(fallback).lower())
        get_settings(force_reload=True)

    yield set_
    monkeypatch.undo()
    get_settings(force_reload=True)


class TestSeparateSwitch:
    def test_off_means_off(self, switches):
        switches(intraday=False, fallback=False)
        assert get_settings().providers.enable_yfinance_intraday is False  # the switch took effect
        with pytest.raises(ConfigError, match="intraday provider is disabled"):
            get_intraday_provider()

    def test_on_builds_the_provider(self, switches):
        switches(intraday=True, fallback=False)
        assert isinstance(get_intraday_provider(), YFinanceIntradayProvider)

    def test_intraday_being_on_does_not_enable_the_eod_yfinance_price_path(self, switches):
        """The whole point of a separate switch."""
        switches(intraday=True, fallback=False)
        assert isinstance(get_intraday_provider(), YFinanceIntradayProvider)
        with pytest.raises(ConfigError, match="yfinance provider is disabled"):
            get_price_provider("yfinance")

    def test_and_the_reverse(self, switches):
        switches(intraday=False, fallback=True)
        get_price_provider("yfinance")  # allowed
        with pytest.raises(ConfigError, match="intraday provider is disabled"):
            get_intraday_provider()

    def test_unknown_name(self, switches):
        switches(intraday=True, fallback=False)
        with pytest.raises(ConfigError, match="unknown intraday provider"):
            get_intraday_provider("nope")
