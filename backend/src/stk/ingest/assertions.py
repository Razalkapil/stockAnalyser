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

#: Series where an OHLC ordering violation means a parsing/units bug and must abort the day.
#: EQ/BE/BZ are the equity series we trade (BE/BZ are trade-for-trade); SM/ST are the SME
#: segments. Anything else in the file is an AUXILIARY series -- see ``assert_bars_sane``.
OHLC_STRICT_SERIES = frozenset({"EQ", "BE", "BZ", "SM", "ST"})


def assert_bars_sane(bars: list[CanonicalBar], *, context: str) -> list[str]:
    """Cheap, fast invariant checks over a batch of parsed bars.

    Returns a list of NON-FATAL anomaly descriptions (empty when clean); every
    other violation raises ``IngestAssertionError``.

    THE ONE RELAXATION. ``high >= max(open, close, low)`` is fatal for the equity
    series in ``OHLC_STRICT_SERIES`` but only an anomaly for auxiliary series.
    Found by a live backfill: sec_bhavdata_full carries rows such as WIPRO's ``T0``
    (T+0 settlement) beside the real ``EQ`` row -- 3 shares traded, open=high=low=
    269.00, but CLOSE_PRICE carrying the EQ close of 269.65. That row is internally
    inconsistent by NSE's own construction, and aborting the whole day over it blocked
    about a third of real trading days. A check that cries wolf that often teaches you
    to ignore it, which is worse than no check. The rows are still STORED (raw data is
    kept whole); they are counted and returned so the caller can log and record them.
    Every other invariant below applies to every series.

    Deliberately does NOT include the "row count within 30% of trailing
    20-day median" check from the build plan -- that needs historical
    context (prior days' counts) that isn't available to a pure
    function over a single day's bars; it belongs in the orchestrator
    once enough history has accumulated to compute a median against.
    """
    if not bars:
        raise IngestAssertionError(f"{context}: zero bars parsed")

    anomalies: list[str] = []
    delivery_violations: list[str] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for bar in bars:
        key = (bar.exchange, bar.symbol, bar.series or "", bar.date.isoformat())
        if key in seen_keys:
            raise IngestAssertionError(f"{context}: duplicate row for {key}")
        seen_keys.add(key)

        if bar.high < max(bar.open, bar.close, bar.low):
            message = (
                f"{context}: {bar.symbol} high={bar.high} < max(open,close,low) on {bar.date}"
            )
            if (bar.series or "") in OHLC_STRICT_SERIES:
                raise IngestAssertionError(message)
            anomalies.append(f"{message} (series {bar.series!r}, auxiliary: kept, not fatal)")
        if bar.close <= 0:
            raise IngestAssertionError(f"{context}: {bar.symbol} close<=0 on {bar.date}")
        if bar.volume < 0:
            raise IngestAssertionError(f"{context}: {bar.symbol} negative volume on {bar.date}")
        if bar.delivery_qty is not None and bar.delivery_qty > bar.volume:
            delivery_violations.append(
                f"{bar.symbol} delivery_qty={bar.delivery_qty} > volume={bar.volume} "
                f"on {bar.date}"
            )
        if bar.turnover < 0:
            raise IngestAssertionError(f"{context}: {bar.symbol} negative turnover on {bar.date}")
        _assert_turnover_plausible(bar, context)

    anomalies += _judge_delivery_violations(delivery_violations, len(bars), context)
    return anomalies


#: delivery_qty > volume is impossible, so it is always reported -- but whether it ABORTS the day
#: depends on how widespread it is. Found on real data: NSE's 2024-02-19 file has ONE row (WTICAB,
#: 0.2% over) and aborting the day for it discarded ~2,700 good symbols. A units or column-shift
#: bug, by contrast, breaks a large share of rows at once. So: a handful of rows, and under this
#: fraction of the batch, is a counted source quirk; anything more is treated as systemic.
_DELIVERY_TOLERATED_ROWS = 5
_DELIVERY_TOLERATED_FRACTION = 0.005


def _judge_delivery_violations(violations: list[str], total: int, context: str) -> list[str]:
    limit = min(_DELIVERY_TOLERATED_ROWS, int(total * _DELIVERY_TOLERATED_FRACTION))
    if len(violations) > limit:
        raise IngestAssertionError(
            f"{context}: {len(violations)} of {total} rows have delivery_qty > volume "
            f"(tolerated: at most {limit}) -- looks systemic, not a one-off source quirk; "
            f"e.g. {'; '.join(violations[:3])}"
        )
    return [f"{context}: {v} (isolated source quirk: kept, not fatal)" for v in violations]


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

    That same distinction governs the close: a PRICE LEVEL is always
    positive, but a derived counter is not a level and zero is a real
    reading for it. "Nifty50 Dividend Points" accumulates dividend
    points across a financial year and RESETS TO ZERO on the first
    sessions of the next one -- live-confirmed: it prints 289.38 on
    2025-03-27 and 4.22 by 2025-04-28. Treating that zero as corrupt
    aborted the whole day's index ingest and cost the benchmark 65
    trading days between 2021 and 2026, every one of them in the first
    weeks of April. The series is told apart by what it carries, not by
    its name: no open, no high and no low means it is not a price level.
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

        # A negative reading is nonsense for either kind of series.
        price_level = not (bar.open is None and bar.high is None and bar.low is None)
        if bar.close < 0 or (price_level and bar.close == 0):
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
