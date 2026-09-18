"""Post-ingest sanity assertions.

Run after every parse, before a partition write is considered
successful. All fatal: a violation raises IngestAssertionError rather
than being logged and ignored, because these specific invariants
catch unit/parsing mistakes (e.g. a lakhs-to-rupees conversion bug)
that would otherwise silently corrupt every backtest touching the
affected symbol.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stk.core.errors import IngestAssertionError
from stk.ingest.normalise import IndexBar
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


def assert_bars_match_requested_date(
    bars: list[CanonicalBar], requested_date: date, *, context: str
) -> None:
    """Assert every parsed bar's date matches the date we actually
    requested from the provider.

    This is not a hypothetical check: NSE's own sec_bhavdata_full
    archive was found, during real backfill testing, to occasionally
    serve a historical file whose CONTENT is dated differently from
    what its URL/filename promises -- e.g. the file requested for
    2019-09-30 was observed serving rows dated 27-Jun-2019, and the
    file requested for 2019-10-02 was observed serving a duplicate of
    2019-10-01's content. Without this check, such a mismatch would be
    silently written into the partition keyed under the WRONG date
    (whatever business_date's replace_dates targeted), corrupting that
    date's history while leaving the date the content actually
    belongs to untouched or duplicated. This must fail loudly instead
    -- see the project's "raw bytes are sacred, fail loudly" principle
    in CLAUDE.md.
    """
    mismatched = {bar.date for bar in bars if bar.date != requested_date}
    if mismatched:
        raise IngestAssertionError(
            f"{context}: requested data for {requested_date} but the fetched "
            f"content is dated {sorted(mismatched)} instead -- the source "
            f"served the wrong file's content for this date. Refusing to "
            f"write (would corrupt the partition under the wrong date key)."
        )


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


def assert_index_bars_sane(bars: list[IndexBar], *, context: str) -> None:
    """Post-parse sanity checks for index bars.

    Deliberately narrower than assert_bars_sane: an index has no
    delivery quantity, no turnover-vs-vwap relationship, and legitimate
    null OHLC on derived series (NSE's file carries e.g. "Nifty50
    Dividend Points", which has a close and nothing else). So only the
    invariants that genuinely hold are asserted.
    """
    if not bars:
        raise IngestAssertionError(f"{context}: parsed zero index bars")

    seen: set[tuple[str, date]] = set()
    for bar in bars:
        key = (bar.index_name, bar.date)
        if key in seen:
            raise IngestAssertionError(
                f"{context}: duplicate row for index {bar.index_name} on {bar.date}"
            )
        seen.add(key)

        if bar.close <= 0:
            raise IngestAssertionError(
                f"{context}: index {bar.index_name} has non-positive close {bar.close}"
            )

        if bar.high is not None and bar.low is not None and bar.high < bar.low:
            raise IngestAssertionError(
                f"{context}: index {bar.index_name} has high {bar.high} < low {bar.low}"
            )

        present = [v for v in (bar.open, bar.close, bar.low) if v is not None]
        if bar.high is not None and present and bar.high < max(present):
            raise IngestAssertionError(
                f"{context}: index {bar.index_name} has high {bar.high} below "
                f"open/close/low max {max(present)}"
            )


def assert_index_bars_match_requested_date(
    bars: list[IndexBar], requested_date: date, *, context: str
) -> None:
    """Same guard as assert_bars_match_requested_date, for index bars.

    ADR 0003 documents NSE's archive serving content dated differently
    from what the URL promises. That was found on the price archive;
    nothing says the index archive is immune, and the check is nearly
    free.
    """
    mismatched = {bar.date for bar in bars if bar.date != requested_date}
    if mismatched:
        raise IngestAssertionError(
            f"{context}: requested index data for {requested_date} but the fetched "
            f"content is dated {sorted(mismatched)} instead -- refusing to write it "
            "under the requested date's partition key."
        )
