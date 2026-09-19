"""Live pick tracking: same exit rules as the backtest, ratios only."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from stk.domain.tracking import Bar, track_pick

D0 = date(2025, 7, 1)


def bar(i: int, o: float, h: float | None = None, low: float | None = None,
        c: float | None = None) -> Bar:
    c = o if c is None else c
    return Bar(D0 + timedelta(days=i), o, o if h is None else h, o if low is None else low, c)


def flat(n: int, px: float = 100.0, start: int = 0) -> list[Bar]:
    return [bar(start + i, px) for i in range(n)]


class TestStates:
    def test_no_bars_yet_means_pending_entry(self):
        t = track_pick([], stop_pct=0.05, target_pct=0.1, hold_days=5)
        assert t.status == "pending_entry" and t.entry_price is None

    def test_enters_at_the_next_sessions_open(self):
        t = track_pick([bar(0, 107, c=108)], stop_pct=0.05, target_pct=None, hold_days=5)
        assert t.status == "open" and t.entry_price == 107

    def test_open_pick_is_marked_to_the_last_close(self):
        bars = [bar(0, 100), bar(1, 100, c=104), bar(2, 104, c=106)]
        t = track_pick(bars, stop_pct=0.1, target_pct=0.5, hold_days=10)
        assert t.status == "open" and t.net_return == pytest.approx(0.06)
        assert t.holding_days == 2
        assert [round(r, 3) for _, r in t.marks] == [0.0, 0.04, 0.06]


class TestExits:
    def test_stop_gap_fills_at_the_open_not_the_stop(self):
        bars = [bar(0, 100), bar(1, 90, 91, 89, 90)]
        t = track_pick(bars, stop_pct=0.05, target_pct=None, hold_days=10)
        assert (t.status, t.exit_reason, t.exit_price) == ("closed", "stop", 90)
        assert t.net_return == pytest.approx(-0.10)

    def test_intraday_stop_touch_fills_at_the_stop(self):
        bars = [bar(0, 100), bar(1, 100, 101, 94, 96)]
        t = track_pick(bars, stop_pct=0.05, target_pct=None, hold_days=10)
        assert t.exit_price == pytest.approx(95.0) and t.exit_reason == "stop"

    def test_target(self):
        bars = [bar(0, 100), bar(1, 101, 112, 100, 110)]
        t = track_pick(bars, stop_pct=0.05, target_pct=0.10, hold_days=10)
        assert (t.exit_reason, round(t.exit_price, 6)) == ("target", 110.0)

    def test_stop_wins_when_a_bar_touches_both(self):
        bars = [bar(0, 100), bar(1, 100, 120, 90, 100)]
        t = track_pick(bars, stop_pct=0.05, target_pct=0.10, hold_days=10)
        assert t.exit_reason == "stop"

    def test_time_exit_at_the_close_after_hold_days(self):
        t = track_pick(flat(8), stop_pct=None, target_pct=None, hold_days=3)
        assert (t.exit_reason, t.holding_days) == ("time", 3)
        assert t.exit_date == D0 + timedelta(days=3)

    def test_the_entry_bar_itself_never_exits(self):
        """Mirrors the engine: the entry session is not checked against the stop."""
        bars = [bar(0, 100, 100, 50, 60)]  # would blow through any stop, but it is the entry bar
        t = track_pick(bars, stop_pct=0.05, target_pct=None, hold_days=10)
        assert t.status == "open"

    def test_no_stop_and_no_target_only_time_can_close_it(self):
        bars = [bar(0, 100)] + [bar(i, 1.0) for i in range(1, 4)]  # a 99% crash
        t = track_pick(bars, stop_pct=None, target_pct=None, hold_days=10)
        assert t.status == "open" and t.net_return == pytest.approx(-0.99)


class TestCostsAndExcursions:
    def test_cost_drag_is_subtracted(self):
        t = track_pick([bar(0, 100), bar(1, 110, c=110)], stop_pct=None, target_pct=None,
                       hold_days=1, cost_pct=0.004)
        assert t.net_return == pytest.approx(0.10 - 0.004)

    def test_excursions(self):
        bars = [bar(0, 100), bar(1, 100, 108, 97, 105), bar(2, 105, 106, 99, 100)]
        t = track_pick(bars, stop_pct=None, target_pct=None, hold_days=10)
        assert t.mfe == pytest.approx(0.08) and t.mae == pytest.approx(-0.03)

    def test_a_corporate_action_cannot_create_a_fake_crash(self):
        """The bars are back-adjusted, so a 1:1 bonus mid-hold shows up as a continuous
        series. Feed the SAME economic path as an adjusted series and confirm no stop fires."""
        adjusted = [bar(0, 50), bar(1, 50, 51, 49, 50), bar(2, 51, 52, 50, 51.5)]
        t = track_pick(adjusted, stop_pct=0.05, target_pct=None, hold_days=10)
        assert t.status == "open" and t.net_return == pytest.approx(0.03)
