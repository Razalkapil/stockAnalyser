"""Live pick tracking -- pure.

Given the bars that followed a pick's signal date, decide where the pick
stands: not yet entered, open (marked to market), or closed (stop, target or
time). The rules deliberately MIRROR ``stk.backtest.engine`` so that a live
track record is comparable with the backtest it is being held against:

  * entry at the next session's OPEN;
  * no exit check on the entry bar itself (the engine does the same);
  * a gap through the stop fills at the open, not the stop;
  * stop beats target when one bar touches both;
  * time exit at the close once ``hold_days`` sessions have passed.

Bars are the back-adjusted series, so a split or bonus during the hold can
never look like a crash: only RATIOS between adjusted prices are used, never
an absolute level. ``cost_pct`` is the round-trip cost drag as a fraction of
the position, subtracted so live returns are net, like the backtest's.

Known simplification, shared with the backtest: circuit locks and the
participation cap are not modelled here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Bar:
    date: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class TrackedPick:
    status: str  # pending_entry | open | closed
    entry_date: date | None = None
    entry_price: float | None = None
    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str | None = None  # stop | target | time
    last_date: date | None = None
    last_close: float | None = None
    net_return: float | None = None  # after costs; marked to market while open
    holding_days: int = 0
    mfe: float = 0.0  # best excursion vs entry (fraction)
    mae: float = 0.0  # worst excursion vs entry (fraction, <= 0)
    marks: tuple[tuple[date, float], ...] = ()  # (date, net return) per session held


def _exit_on(bar: Bar, stop: float | None, target: float | None) -> tuple[float, str] | None:
    if stop is not None and bar.open <= stop:
        return bar.open, "stop"
    if stop is not None and bar.low <= stop:
        return stop, "stop"
    if target is not None and bar.open >= target:
        return bar.open, "target"
    if target is not None and bar.high >= target:
        return target, "target"
    return None


def track_pick(
    bars: list[Bar],
    *,
    stop_pct: float | None,
    target_pct: float | None,
    hold_days: int,
    cost_pct: float = 0.0,
) -> TrackedPick:
    """``bars`` must be strictly AFTER the signal date, in date order."""
    if not bars:
        return TrackedPick(status="pending_entry")

    entry = bars[0]
    entry_price = entry.open
    stop = entry_price * (1.0 - stop_pct) if stop_pct is not None else None
    target = entry_price * (1.0 + target_pct) if target_pct is not None else None

    marks: list[tuple[date, float]] = []
    mfe = mae = 0.0

    def net(price: float) -> float:
        return price / entry_price - 1.0 - cost_pct

    for i, bar in enumerate(bars):
        mfe = max(mfe, bar.high / entry_price - 1.0)
        mae = min(mae, bar.low / entry_price - 1.0)
        hit = _exit_on(bar, stop, target) if i > 0 else None
        if hit is None and i >= hold_days:
            hit = (bar.close, "time")
        if hit is not None:
            price, reason = hit
            marks.append((bar.date, net(price)))
            return TrackedPick(
                status="closed", entry_date=entry.date, entry_price=entry_price,
                exit_date=bar.date, exit_price=price, exit_reason=reason,
                last_date=bar.date, last_close=bar.close, net_return=net(price),
                holding_days=i, mfe=mfe, mae=mae, marks=tuple(marks),
            )
        marks.append((bar.date, net(bar.close)))

    last = bars[-1]
    return TrackedPick(
        status="open", entry_date=entry.date, entry_price=entry_price,
        last_date=last.date, last_close=last.close, net_return=net(last.close),
        holding_days=len(bars) - 1, mfe=mfe, mae=mae, marks=tuple(marks),
    )
