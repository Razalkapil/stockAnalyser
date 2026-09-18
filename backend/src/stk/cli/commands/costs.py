"""`stk costs` -- inspect the transaction-cost model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import typer

from stk.config.costs import get_rate_schedule
from stk.core.money import bps, format_inr
from stk.domain.costs import Product, Side, compute_costs, dp_charge

app = typer.Typer(help="Transaction-cost model.")


@app.command("quote")
def quote(
    value: float = typer.Option(..., "--value", help="Order value in rupees"),
    side: str = typer.Option("sell", "--side", help="buy or sell"),
    product: str = typer.Option("delivery", "--product", help="delivery or intraday"),
    exchange: str = typer.Option("NSE", "--exchange", help="NSE or BSE"),
    on: str | None = typer.Option(None, "--date", help="YYYY-MM-DD; defaults to today"),
) -> None:
    """Itemise the charges on one order leg, using the rates in force on a date.

    Rates in config/costs.yaml are UNVERIFIED against primary circulars.
    """
    when = datetime.strptime(on, "%Y-%m-%d").date() if on else datetime.now().date()
    rates = get_rate_schedule().rates_for(exchange.upper(), when)
    turnover = Decimal(str(value))
    leg_side = Side(side.lower())
    prod = Product(product.lower())
    b = compute_costs(leg_side, prod, turnover, rates)

    typer.echo(
        f"{exchange.upper()} {prod.value} {leg_side.value} of {format_inr(turnover)} on {when}"
    )
    for label, amount in (
        ("brokerage", b.brokerage),
        ("STT", b.stt),
        ("stamp duty", b.stamp_duty),
        ("exchange txn", b.exchange_txn),
        ("IPFT", b.ipft),
        ("SEBI fee", b.sebi_fee),
        ("GST", b.gst),
    ):
        typer.echo(f"  {label:<14}{format_inr(amount):>14}")
    typer.echo(f"  {'subtotal':<14}{format_inr(b.total):>14}  ({bps(b.total, turnover):.1f} bps)")
    if leg_side is Side.SELL and prod is Product.DELIVERY:
        dp = dp_charge(rates)
        typer.echo(
            f"  {'DP charge':<14}{format_inr(dp):>14}  "
            f"({bps(dp, turnover):.1f} bps, once per scrip/day)"
        )
        all_in = b.total + dp
        typer.echo(f"  {'all-in':<14}{format_inr(all_in):>14}  ({bps(all_in, turnover):.1f} bps)")
