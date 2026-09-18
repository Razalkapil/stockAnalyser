"""Tiered slippage and the participation cap -- pure.

Slippage is a function of how liquid the name is, not a flat number: a
Rs 50 crore/day large-cap and a Rs 2 crore/day small-cap do not fill
alike. Tiers are keyed on trailing average daily turnover (rupees) and
supplied by the caller from config/backtest.yaml.

The participation cap bounds one order's size to a fraction of the
bar's traded volume. Above it, the order is *partially filled*; we never
pretend a small stock can absorb an order larger than the market traded.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stk.domain.costs import Side


@dataclass(frozen=True)
class SlippageTier:
    """Applies when trailing ADV turnover >= ``min_adv_turnover_inr``."""

    min_adv_turnover_inr: Decimal
    bps: Decimal


def slippage_bps(adv_turnover_inr: Decimal | None, tiers: tuple[SlippageTier, ...]) -> Decimal:
    """Basis points of slippage for a name with the given trailing ADV turnover.

    ``tiers`` must be non-empty. Unknown ADV (None -- a name with no
    trailing history) gets the *worst* tier, never the best: not knowing
    how liquid something is is not evidence that it is liquid.
    """
    if not tiers:
        raise ValueError("at least one slippage tier is required")
    ordered = sorted(tiers, key=lambda t: t.min_adv_turnover_inr, reverse=True)
    if adv_turnover_inr is None:
        return max(t.bps for t in tiers)
    for tier in ordered:
        if adv_turnover_inr >= tier.min_adv_turnover_inr:
            return tier.bps
    return ordered[-1].bps  # below the lowest threshold: lowest tier's bps


def apply_slippage(price: Decimal, side: Side, bps: Decimal) -> Decimal:
    """Adverse slippage: buys fill higher, sells fill lower."""
    factor = bps / Decimal(10_000)
    return price * (Decimal(1) + factor) if side is Side.BUY else price * (Decimal(1) - factor)


def cap_quantity(desired_qty: int, bar_volume: int, participation_cap: Decimal) -> int:
    """Largest fillable quantity given a bar's volume and a participation cap (0..1]."""
    if desired_qty < 0 or bar_volume < 0:
        raise ValueError("quantities must be non-negative")
    if not (Decimal(0) < participation_cap <= Decimal(1)):
        raise ValueError(f"participation_cap must be in (0, 1], got {participation_cap}")
    limit = int(Decimal(bar_volume) * participation_cap)
    return min(desired_qty, limit)
