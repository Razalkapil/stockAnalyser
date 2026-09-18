"""The only window a strategy gets onto the data.

A strategy decides on the close of day T. Everything it can read must
have been knowable at that moment -- bars dated <= T, fundamentals whose
``available_at`` <= T. ``PointInTimeView`` is constructed per decision
date and is the *sole* data handle passed to ``Strategy.signals``; there
is no method that returns a row from the future.

Enforcement is two-layered, deliberately:
  1. Slicing: every accessor slices by ``searchsorted`` on the decision
     date, so future rows are never selected in the first place.
  2. Assertion: every returned frame is re-checked (``_guard``) and a
     violation raises ``LookAheadError`` instead of returning quietly.
     Layer 2 exists so a future refactor of layer 1 cannot silently
     re-introduce look-ahead -- the tests poison the future and prove it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd


class LookAheadError(AssertionError):
    """A read would have returned data not available at the decision date."""


@dataclass
class MarketData:
    """Adjusted daily bars for one exchange (+ optional point-in-time tables).

    ``bars`` columns: date (datetime64), symbol, open, high, low, close,
    volume, turnover, prev_close (previous *adjusted* close of the same
    symbol), adv_turnover (trailing median turnover, shifted so a bar's
    own value never leaks into it). Extra columns (features, delivery_pct)
    ride along untouched.

    ``fundamentals`` (optional) must carry ``available_at`` (datetime64).
    """

    bars: pd.DataFrame
    fundamentals: pd.DataFrame | None = None
    _dates: np.ndarray = field(init=False, repr=False)
    _by_symbol: dict[str, pd.DataFrame] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        bars = self.bars.sort_values(["date", "symbol"], kind="stable").reset_index(drop=True)
        bars["date"] = pd.to_datetime(bars["date"])
        self.bars = bars
        self._dates = bars["date"].to_numpy(dtype="datetime64[ns]")
        self._by_symbol = {
            str(sym): grp.reset_index(drop=True) for sym, grp in bars.groupby("symbol", sort=False)
        }
        if self.fundamentals is not None:
            f = self.fundamentals.copy()
            f["available_at"] = pd.to_datetime(f["available_at"])
            self.fundamentals = f.sort_values("available_at").reset_index(drop=True)

    def trading_dates(self, start: date, end: date) -> list[date]:
        """Distinct bar dates in [start, end] that actually appear in the data."""
        lo = np.datetime64(pd.Timestamp(start))
        hi = np.datetime64(pd.Timestamp(end))
        mask = (self._dates >= lo) & (self._dates <= hi)
        return [pd.Timestamp(d).date() for d in np.unique(self._dates[mask])]


class PointInTimeView:
    """Read-only view of ``MarketData`` as it stood at the close of ``decision_date``."""

    def __init__(self, data: MarketData, decision_date: date) -> None:
        self._data = data
        self.decision_date = decision_date
        self._cutoff = np.datetime64(pd.Timestamp(decision_date))
        self.reads = 0

    def _guard(self, frame: pd.DataFrame, column: str = "date") -> pd.DataFrame:
        self.reads += 1
        if len(frame) and frame[column].max() > pd.Timestamp(self.decision_date):
            raise LookAheadError(
                f"read returned {column} up to {frame[column].max().date()} "
                f"at decision date {self.decision_date}"
            )
        return frame

    def today(self) -> pd.DataFrame:
        """All symbols' bars dated exactly ``decision_date``."""
        d = self._data._dates
        lo = int(np.searchsorted(d, self._cutoff, side="left"))
        hi = int(np.searchsorted(d, self._cutoff, side="right"))
        return self._guard(self._data.bars.iloc[lo:hi])

    def history(self, symbol: str, n: int) -> pd.DataFrame:
        """The last ``n`` bars of ``symbol`` dated <= ``decision_date``."""
        frame = self._data._by_symbol.get(symbol)
        if frame is None:
            return self._guard(self._data.bars.iloc[0:0])
        dates = frame["date"].to_numpy(dtype="datetime64[ns]")
        hi = int(np.searchsorted(dates, self._cutoff, side="right"))
        return self._guard(frame.iloc[max(0, hi - n) : hi])

    def bars_until(self) -> pd.DataFrame:
        """Every bar dated <= ``decision_date`` (all symbols)."""
        hi = int(np.searchsorted(self._data._dates, self._cutoff, side="right"))
        return self._guard(self._data.bars.iloc[:hi])

    def fundamentals(self) -> pd.DataFrame | None:
        """Fundamentals rows whose ``available_at`` <= ``decision_date`` (else None if no table)."""
        f = self._data.fundamentals
        if f is None:
            return None
        cutoff = pd.Timestamp(self.decision_date)
        available = f["available_at"].to_numpy(dtype="datetime64[ns]")
        hi = int(np.searchsorted(available, np.datetime64(cutoff), side="right"))
        return self._guard(f.iloc[:hi], column="available_at")
