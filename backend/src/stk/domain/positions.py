"""Position accounting -- pure, Decimal-only, average-cost method.

``avg_cost`` EXCLUDES charges: brokerage, STT and the rest are tracked separately and shown as
their own line ("Charges paid"), so realised P&L here is GROSS and the portfolio's net figure is
realised - charges. Mixing them would make both numbers impossible to reconcile against a
contract note.

No shorting: a sell larger than the holding is an error, not a negative position.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from stk.core.money import to_money

ZERO = Decimal(0)


class PositionError(ValueError):
    pass


@dataclass(frozen=True)
class Position:
    qty: int = 0
    avg_cost: Decimal = ZERO
    realised_pnl: Decimal = ZERO  # gross of charges

    @property
    def cost_basis(self) -> Decimal:
        return self.avg_cost * self.qty

    def unrealised(self, mark: Decimal) -> Decimal:
        return (mark - self.avg_cost) * self.qty


def apply_buy(pos: Position, qty: int, price: Decimal) -> Position:
    if qty < 1:
        raise PositionError("buy quantity must be positive")
    total = pos.qty + qty
    avg = (pos.avg_cost * pos.qty + price * qty) / total
    return Position(total, avg, pos.realised_pnl)


def apply_sell(pos: Position, qty: int, price: Decimal) -> Position:
    if qty < 1:
        raise PositionError("sell quantity must be positive")
    if qty > pos.qty:
        raise PositionError(f"cannot sell {qty}: only {pos.qty} held (no shorting)")
    remaining = pos.qty - qty
    return Position(
        remaining,
        pos.avg_cost if remaining else ZERO,  # a closed position carries no stale cost
        pos.realised_pnl + (price - pos.avg_cost) * qty,
    )


@dataclass(frozen=True)
class SplitResult:
    position: Position
    dropped_shares: Decimal  # the fractional entitlement that does not exist as a share
    dropped_cost: Decimal


def apply_split_or_bonus(pos: Position, volume_factor: Decimal) -> SplitResult:
    """A split or bonus multiplies the share count by ``volume_factor`` (1:1 bonus -> 2).

    TOTAL COST IS CONSERVED: you paid the same money for more shares, so the average falls. A
    fractional entitlement (a 3:2 bonus on 5 shares -> 12.5) is floored, since there is no
    such thing as half a share; the fraction is reported, and its share of cost is written off
    rather than silently kept on a position that no longer holds it.
    """
    if volume_factor <= 0:
        raise PositionError("volume_factor must be positive")
    if pos.qty == 0:
        return SplitResult(pos, ZERO, ZERO)
    exact = Decimal(pos.qty) * volume_factor
    new_qty = int(exact.to_integral_value(rounding=ROUND_FLOOR))
    dropped = exact - new_qty
    if new_qty == 0:
        return SplitResult(Position(0, ZERO, pos.realised_pnl), exact, pos.cost_basis)
    kept_cost = pos.cost_basis * Decimal(new_qty) / exact
    return SplitResult(
        Position(new_qty, kept_cost / new_qty, pos.realised_pnl),
        dropped,
        pos.cost_basis - kept_cost,
    )


def dividend_cash(qty_held: int, per_share: Decimal) -> Decimal:
    """Cash credited for a dividend on the shares held at the ex-date's previous close."""
    if qty_held < 0 or per_share < 0:
        raise PositionError("dividend inputs must be non-negative")
    return to_money(per_share * qty_held)
