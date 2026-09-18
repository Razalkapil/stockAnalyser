"""Fill-price rules -- pure.

Two rules matter and both are easy to get subtly wrong:

1. NEXT-OPEN FILLS. A signal computed from day T's close cannot trade at
   day T's close -- that price was not knowable when the decision was
   made. It fills at day T+1's open.

2. CIRCUIT LOCKS. A stock sitting at its upper circuit has buyers and no
   sellers: you cannot buy it. At its lower circuit you cannot sell. A
   backtest that fills anyway books trades that did not exist.

CIRCUIT-LOCK DETECTION IS A HEURISTIC, and says so. We do not hold
historical per-symbol price bands (config/costs.yaml notes the
authoritative band is only available for the current day), so a bar is
treated as locked when it is *frozen* (open == high == low == close) AND
the close-to-previous-close move lands on one of the exchange's allowed
band percentages within a tolerance for tick rounding. A frozen bar at
some other percentage (a genuinely illiquid name that simply did not
trade) is NOT a lock. The heuristic can miss a lock that opened and
traded briefly before freezing; it will not invent one out of thin air.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Lock(StrEnum):
    NONE = "none"
    UPPER = "upper"
    LOWER = "lower"


@dataclass(frozen=True)
class BarPrices:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


def circuit_lock(
    bar: BarPrices,
    prev_close: Decimal | None,
    band_pcts: tuple[Decimal, ...],
    tolerance_pct: Decimal = Decimal("0.35"),
) -> Lock:
    """Classify a bar as upper-locked, lower-locked or neither. See module docstring."""
    if prev_close is None or prev_close <= 0:
        return Lock.NONE
    if not (bar.open == bar.high == bar.low == bar.close):
        return Lock.NONE
    move_pct = (bar.close / prev_close - Decimal(1)) * Decimal(100)
    for band in band_pcts:
        if abs(abs(move_pct) - band) <= tolerance_pct:
            return Lock.UPPER if move_pct > 0 else Lock.LOWER
    return Lock.NONE


def can_buy(lock: Lock) -> bool:
    return lock is not Lock.UPPER


def can_sell(lock: Lock) -> bool:
    return lock is not Lock.LOWER
