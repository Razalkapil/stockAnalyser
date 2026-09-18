"""Walk-forward window generation -- pure.

Tune on a training window, evaluate on the next *unseen* test window,
then roll forward. ``generate_windows`` only produces the calendar; the
harness in ``stk.backtest.walkforward`` does the running.

Windows are built on calendar months so they are stable across years
with different trading-day counts. Test windows never overlap one
another (the roll step equals the test length by default), so the
out-of-sample results are independent observations -- which is what the
promotion gate's "most windows" rule counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Window:
    label: str
    train_start: date
    train_end: date  # inclusive
    test_start: date
    test_end: date  # inclusive


def _add_months(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(idx, 12)
    return date(year, month0 + 1, 1)


def generate_windows(
    start: date,
    end: date,
    *,
    train_months: int,
    test_months: int,
    step_months: int | None = None,
) -> list[Window]:
    """Rolling windows over [start, end]. A window is kept only if its whole test span fits.

    All boundaries fall on the first of a month; ``start`` is snapped to
    its month's first day.
    """
    if train_months <= 0 or test_months <= 0:
        raise ValueError("train_months and test_months must be positive")
    step = step_months if step_months is not None else test_months
    if step <= 0:
        raise ValueError("step_months must be positive")

    cursor = date(start.year, start.month, 1)
    windows: list[Window] = []
    n = 1
    while True:
        train_start = cursor
        test_start = _add_months(train_start, train_months)
        test_end_excl = _add_months(test_start, test_months)
        train_end = date.fromordinal(test_start.toordinal() - 1)
        test_end = date.fromordinal(test_end_excl.toordinal() - 1)
        if test_end > end:
            break  # never truncate a test window: a short one is not comparable
        windows.append(
            Window(
                label=f"W{n}",
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        n += 1
        cursor = _add_months(cursor, step)
    return windows
