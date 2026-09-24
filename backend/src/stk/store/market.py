"""Index closes for a given day, derived from ``indices_daily`` and honest about WHICH day.

``stk.api`` and ``stk.ai`` are peers and may not import each other, so the one fact they must agree
on -- what the market did on day D, and whether we even have day D -- lives here, below both (the
same arrangement as ``repos/ai_briefs``). Nothing is stored: the figures are derived on read, so
the number on screen can never be a second copy that drifts from the lake.

THE FAILURE THIS PREVENTS. "The latest row at or before D" is not "D". A review run before that
day's index ingest used to receive D-1's close and describe it as today's. ``IndexMoves`` therefore
carries the date each figure is FROM, and ``is_stale_for(day)`` says whether they are from ``day``.
``prev_date`` is exposed too: the previous ROW is not the previous SESSION when a day is missing
from the lake, and a change spanning a gap should be visible as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from stk.store import duck

#: The benchmarks a brief reports. Canonical codes, never printed names (NSE renamed the Nifty).
BRIEF_INDICES: tuple[str, ...] = ("NIFTY_50", "NIFTY_500")

#: Calendar days scanned back for a previous close; covers a long weekend plus holidays.
LOOKBACK_DAYS = 10


def benchmark_series(parquet_root: Path, *, index_code: str, start: date, end: date
                     ) -> pd.DataFrame:
    """Benchmark closes keyed on the canonical index_code (never the printed name)."""
    with duck.connect(parquet_root) as session:
        return session.sql(
            "benchmark_series", [index_code, start.isoformat(), end.isoformat()]
        ).df()


@dataclass(frozen=True)
class IndexMove:
    index_code: str
    name: str
    close: float
    change_pct: float
    as_of: date
    prev_close: float
    prev_date: date


@dataclass(frozen=True)
class IndexMoves:
    rows: list[IndexMove] = field(default_factory=list)

    @property
    def as_of(self) -> date | None:
        """The OLDEST date any figure is from: one stale index makes the block stale."""
        return min((r.as_of for r in self.rows), default=None)

    @property
    def latest(self) -> date | None:
        return max((r.as_of for r in self.rows), default=None)

    def is_stale_for(self, day: date) -> bool:
        """True when there is nothing, or any figure is from a day other than ``day``."""
        return not self.rows or any(r.as_of != day for r in self.rows)


def _as_date(v: object) -> date:
    return pd.Timestamp(v).date()


def index_moves(parquet_root: Path, day: date, codes: tuple[str, ...] = BRIEF_INDICES
                ) -> IndexMoves:
    """Each index's latest close at or before ``day`` and its move from the previous row."""
    out: list[IndexMove] = []
    for code in codes:
        df = benchmark_series(parquet_root, index_code=code,
                              start=day - timedelta(days=LOOKBACK_DAYS), end=day)
        if len(df) < 2:
            continue
        last, prev = df.iloc[-1], df.iloc[-2]
        last_close, prev_close = float(last["close"]), float(prev["close"])
        out.append(IndexMove(
            index_code=code, name=str(last["index_name"]),
            close=round(last_close, 2),
            change_pct=round((last_close / prev_close - 1) * 100, 2),
            as_of=_as_date(last["date"]), prev_close=round(prev_close, 2),
            prev_date=_as_date(prev["date"])))
    return IndexMoves(out)
