"""XIRR -- pure.

Annualised internal rate of return for dated cash flows, on the actual/365 convention
(the spreadsheet definition), solved by Newton's method with a bisection fallback so a
badly-behaved series still converges instead of diverging.

Returns None -- never 0 -- when no rate exists: fewer than two flows, or flows that are all one
sign (nothing was ever put in, or nothing ever came out). "There is no answer" and "the answer
is 0%" are different statements.
"""

from __future__ import annotations

from datetime import date

Flow = tuple[date, float]

_MAX_ITER = 100
_TOL = 1e-9


def _npv(rate: float, flows: list[Flow], t0: date) -> float:
    return sum(cf / (1.0 + rate) ** ((d - t0).days / 365.0) for d, cf in flows)


def _dnpv(rate: float, flows: list[Flow], t0: date) -> float:
    total = 0.0
    for d, cf in flows:
        t = (d - t0).days / 365.0
        total -= t * cf / (1.0 + rate) ** (t + 1.0)
    return total


def xirr(flows: list[Flow]) -> float | None:
    """Rate as a fraction (0.12 = 12% a year), or None if undefined."""
    if len(flows) < 2:
        return None
    has_in = any(cf < 0 for _, cf in flows)
    has_out = any(cf > 0 for _, cf in flows)
    if not (has_in and has_out):
        return None
    ordered = sorted(flows, key=lambda f: f[0])
    t0 = ordered[0][0]
    if ordered[-1][0] == t0:
        return None  # everything on one day: no time, no annualised rate

    rate = 0.1
    for _ in range(_MAX_ITER):
        f = _npv(rate, ordered, t0)
        if abs(f) < _TOL:
            return rate
        d = _dnpv(rate, ordered, t0)
        if d == 0:
            break
        nxt = rate - f / d
        if nxt <= -0.999999:  # Newton stepped outside the domain of (1 + r)
            break
        if abs(nxt - rate) < _TOL:
            return nxt
        rate = nxt

    return _bisect(ordered, t0)


def _bisect(flows: list[Flow], t0: date) -> float | None:
    lo, hi = -0.999999, 1e6
    f_lo, f_hi = _npv(lo, flows, t0), _npv(hi, flows, t0)
    if f_lo * f_hi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2.0
        f_mid = _npv(mid, flows, t0)
        if abs(f_mid) < _TOL:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0
