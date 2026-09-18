"""Post-ingest sanity assertions.

Run after every parse, before a partition write is considered
successful. All fatal: a violation raises IngestAssertionError rather
than being logged and ignored, because these specific invariants
catch unit/parsing mistakes (e.g. a lakhs-to-rupees conversion bug)
that would otherwise silently corrupt every backtest touching the
affected symbol.
"""

from __future__ import annotations

from decimal import Decimal

from stk.core.errors import IngestAssertionError
from stk.providers.base import CanonicalBar


def assert_bars_sane(bars: list[CanonicalBar], *, context: str) -> None:
    """Cheap, fast invariant checks over a batch of parsed bars.

    Deliberately does NOT include the "row count within 30% of trailing
    20-day median" check from the build plan -- that needs historical
    context (prior days' counts) that isn't available to a pure
    function over a single day's bars; it belongs in the orchestrator
    once enough history has accumulated to compute a median against.
    """
    if not bars:
        raise IngestAssertionError(f"{context}: zero bars parsed")

    seen_keys: set[tuple[str, str, str, str]] = set()
    for bar in bars:
        key = (bar.exchange, bar.symbol, bar.series or "", bar.date.isoformat())
        if key in seen_keys:
            raise IngestAssertionError(f"{context}: duplicate row for {key}")
        seen_keys.add(key)

        if bar.high < max(bar.open, bar.close, bar.low):
            raise IngestAssertionError(
                f"{context}: {bar.symbol} high={bar.high} < max(open,close,low) on {bar.date}"
            )
        if bar.close <= 0:
            raise IngestAssertionError(f"{context}: {bar.symbol} close<=0 on {bar.date}")
        if bar.volume < 0:
            raise IngestAssertionError(f"{context}: {bar.symbol} negative volume on {bar.date}")
        if bar.delivery_qty is not None and bar.delivery_qty > bar.volume:
            raise IngestAssertionError(
                f"{context}: {bar.symbol} delivery_qty={bar.delivery_qty} "
                f"> volume={bar.volume} on {bar.date}"
            )
        if bar.turnover < 0:
            raise IngestAssertionError(f"{context}: {bar.symbol} negative turnover on {bar.date}")
        _assert_turnover_plausible(bar, context)


# Below this absolute rupee value, turnover/volume/vwap rounding noise
# dominates the ratio check -- this is routinely hit by thin government
# securities (gilts, SGBs) that appear in sec_bhavdata_full alongside
# equities with near-zero traded value. The check exists to catch a
# UNITS bug (e.g. forgetting the lakhs conversion), which manifests as
# an orders-of-magnitude error, not a rounding-scale one -- so a floor
# here does not weaken what the check is actually for.
_TURNOVER_CHECK_FLOOR_INR = Decimal("10000")


def _assert_turnover_plausible(bar: CanonicalBar, context: str) -> None:
    """Turnover should be within a generous 3x band of volume*vwap when
    vwap is available -- a much larger deviation usually means a units
    mistake (e.g. forgetting the lakhs conversion) rather than a real
    trading pattern."""
    if bar.vwap is None or bar.volume == 0:
        return
    implied = Decimal(bar.volume) * bar.vwap
    if implied < _TURNOVER_CHECK_FLOOR_INR:
        return
    ratio = bar.turnover / implied
    if not (Decimal("0.33") <= ratio <= Decimal("3")):
        raise IngestAssertionError(
            f"{context}: {bar.symbol} turnover={bar.turnover} implausible vs "
            f"volume*vwap={implied} (ratio={ratio}) on {bar.date} -- check units"
        )
