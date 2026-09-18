"""Decimal-safe money arithmetic and Indian-style (lakh/crore) formatting.

Every rupee amount in this codebase is a ``Decimal``, never a ``float``.
Floats lose cents-level precision over compounding operations (cost
pipelines, P&L ledgers) in ways that are individually tiny and
collectively wrong.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def to_money(value: float | int | str | Decimal) -> Decimal:
    """Convert any numeric input to a Decimal rounded to paise."""
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def bps(value: Decimal, basis: Decimal) -> Decimal:
    """Express ``value`` as basis points of ``basis``. Returns 0 if basis is 0."""
    if basis == 0:
        return Decimal("0")
    return (value / basis) * Decimal("10000")


def format_inr(amount: Decimal | float | int, *, symbol: bool = True) -> str:
    """Format a rupee amount with Indian digit grouping (lakh/crore).

    format_inr(1234567.5) -> "12,34,567.50"
    format_inr(-950)      -> "-950.00"
    """
    value = to_money(amount)
    sign = "-" if value < 0 else ""
    value = abs(value)
    rupees, _, paise = f"{value:.2f}".partition(".")

    if len(rupees) <= 3:
        grouped = rupees
    else:
        # Last 3 digits, then group the remainder in pairs of 2 (Indian system).
        last3 = rupees[-3:]
        remainder = rupees[:-3]
        parts: list[str] = []
        while len(remainder) > 2:
            parts.insert(0, remainder[-2:])
            remainder = remainder[:-2]
        if remainder:
            parts.insert(0, remainder)
        grouped = ",".join([*parts, last3])

    prefix = "₹" if symbol else ""
    return f"{sign}{prefix}{grouped}.{paise}"
