"""Indian equity transaction costs -- pure, Decimal-only.

``compute_costs`` turns one order leg into a itemised ``CostBreakdown``.
It knows nothing about YAML or dates: the caller resolves the rates in
force on the trade date (``stk.config.costs.rates_for``) and passes them
in as plain ``CostRates``. That keeps this module trivially testable
against hand-worked examples, which is the whole point -- a one-line
mistake here is a *persistent small bias* in every backtest and every
paper fill.

Compute order (mirrors config/costs.yaml):
    turnover -> brokerage -> STT -> stamp duty -> exchange txn -> IPFT
    -> SEBI turnover fee -> GST (on the taxable subset only)

GST applies to brokerage + exchange txn + SEBI fee + IPFT and NOT to STT
or stamp duty. The taxable set is named explicitly in
``CostRates.gst_applies_to`` so the config, not this code, is the source
of truth -- and ``test_costs_compute`` pins it.

The DP (depository) charge is deliberately NOT part of ``compute_costs``:
it is levied once per scrip per day on the SELL leg, not per order, so a
day with two partial sells still pays it once. Use ``dp_charge``.

Rates in config/costs.yaml are unverified against primary circulars --
see the warning there. Nothing here changes that.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from stk.core.money import to_money

CRORE = Decimal(10_000_000)


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class Product(StrEnum):
    DELIVERY = "delivery"
    INTRADAY = "intraday"


@dataclass(frozen=True)
class BrokerageRule:
    """How brokerage is charged for one product.

    model:
      flat_per_order          -> ``flat`` rupees per order
      pct                     -> ``pct`` of turnover
      min_of_pct_and_flat     -> the smaller of ``pct`` of turnover and ``flat``
    """

    model: str
    pct: Decimal = Decimal(0)
    flat: Decimal = Decimal(0)

    def charge(self, turnover: Decimal) -> Decimal:
        if self.model == "flat_per_order":
            return self.flat
        if self.model == "pct":
            return turnover * self.pct
        if self.model == "min_of_pct_and_flat":
            return min(turnover * self.pct, self.flat)
        raise ValueError(f"unknown brokerage model {self.model!r}")


@dataclass(frozen=True)
class ProductRates:
    brokerage: BrokerageRule
    stt_buy: Decimal
    stt_sell: Decimal
    stamp_buy: Decimal
    stamp_sell: Decimal


@dataclass(frozen=True)
class CostRates:
    """Every rate in force on one date for one exchange."""

    gst_rate: Decimal
    gst_applies_to: frozenset[str]
    delivery: ProductRates
    intraday: ProductRates
    exchange_txn_rate: Decimal  # fraction of turnover
    ipft_per_crore: Decimal  # rupees per crore of turnover; 0 for BSE
    sebi_rate: Decimal  # fraction of turnover
    dp_charge_inr: Decimal
    dp_gst_applicable: bool

    def for_product(self, product: Product) -> ProductRates:
        return self.delivery if product is Product.DELIVERY else self.intraday


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised charges for one leg. Every field is paise-rounded rupees."""

    turnover: Decimal
    brokerage: Decimal
    stt: Decimal
    stamp_duty: Decimal
    exchange_txn: Decimal
    ipft: Decimal
    sebi_fee: Decimal
    gst: Decimal

    @property
    def total(self) -> Decimal:
        return (
            self.brokerage
            + self.stt
            + self.stamp_duty
            + self.exchange_txn
            + self.ipft
            + self.sebi_fee
            + self.gst
        )


def compute_costs(
    side: Side,
    product: Product,
    turnover: Decimal,
    rates: CostRates,
) -> CostBreakdown:
    """Itemised charges for one order leg of ``turnover`` rupees.

    Excludes the DP charge -- see ``dp_charge``.
    """
    if turnover < 0:
        raise ValueError(f"turnover must be non-negative, got {turnover}")

    pr = rates.for_product(product)
    is_buy = side is Side.BUY

    brokerage = to_money(pr.brokerage.charge(turnover))
    stt = to_money(turnover * (pr.stt_buy if is_buy else pr.stt_sell))
    stamp = to_money(turnover * (pr.stamp_buy if is_buy else pr.stamp_sell))
    exchange_txn = to_money(turnover * rates.exchange_txn_rate)
    ipft = to_money(turnover / CRORE * rates.ipft_per_crore)
    sebi = to_money(turnover * rates.sebi_rate)

    taxable = {
        "brokerage": brokerage,
        "exchange_txn": exchange_txn,
        "sebi_turnover_fee": sebi,
        "ipft": ipft,
        "stt": stt,
        "stamp_duty": stamp,
    }
    gst_base = sum(
        (taxable[name] for name in rates.gst_applies_to if name in taxable),
        Decimal(0),
    )
    gst = to_money(gst_base * rates.gst_rate)

    return CostBreakdown(
        turnover=turnover,
        brokerage=brokerage,
        stt=stt,
        stamp_duty=stamp,
        exchange_txn=exchange_txn,
        ipft=ipft,
        sebi_fee=sebi,
        gst=gst,
    )


def dp_charge(rates: CostRates) -> Decimal:
    """Depository-participant charge for ONE scrip sold on ONE day.

    Flat, sell leg only, delivery only. The caller applies it once per
    (scrip, day) however many sell orders that day produced. GST is
    added when the schedule says it is applicable.
    """
    base = rates.dp_charge_inr
    if rates.dp_gst_applicable:
        base = base * (Decimal(1) + rates.gst_rate)
    return to_money(base)
