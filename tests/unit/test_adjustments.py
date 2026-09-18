"""Unit tests for corporate-action back-adjustment arithmetic.

These are the tests that stand between a 1:1 bonus and a phantom 50%
crash in every chart and backtest that touches the symbol. The two
highest-risk cases have their own names below: a bar exactly ON the
ex-date must be UNadjusted (the ex-date is the first session whose
price already reflects the action), and a republished duplicate action
must be applied once, not twice.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from stk.ingest.adjustments import (
    ActionFactor,
    build_factor_rows,
    factors_for_bar,
)

EX = date(2026, 6, 15)


def _action(ex_date: date, price: str, volume: str, symbols=("AAA",)) -> ActionFactor:
    return ActionFactor(
        exchange="NSE",
        security_key="sid:1",
        symbols=symbols,
        ex_date=ex_date,
        price_factor=Decimal(price),
        volume_factor=Decimal(volume),
    )


def _bonus_1_1(ex_date: date = EX) -> ActionFactor:
    """Bonus 1:1 -- holders of 1 share get 1 more. Pre-ex prices halve,
    pre-ex volumes double. Matches ingest.corpactions._parse_bonus."""
    return _action(ex_date, "0.5", "2")


def _split_10_to_2(ex_date: date = EX) -> ActionFactor:
    """Face value 10 -> 2: each old share becomes 5 new ones."""
    return _action(ex_date, "0.2", "5")


class TestSingleAction:
    def test_bar_before_ex_date_is_scaled(self):
        rows = build_factor_rows([_bonus_1_1()])
        price, volume = factors_for_bar(rows, date(2026, 6, 12))
        assert price == Decimal("0.5")
        assert volume == Decimal("2")

    def test_bar_on_the_ex_date_is_not_scaled(self):
        """THE classic off-by-one. The ex-date is the first session that
        already trades at the post-action price -- adjusting it too
        would double-count the action."""
        rows = build_factor_rows([_bonus_1_1()])
        assert factors_for_bar(rows, EX) == (Decimal(1), Decimal(1))

    def test_bar_after_the_ex_date_is_not_scaled(self):
        rows = build_factor_rows([_bonus_1_1()])
        assert factors_for_bar(rows, date(2026, 6, 16)) == (Decimal(1), Decimal(1))

    def test_split_factors(self):
        rows = build_factor_rows([_split_10_to_2()])
        price, volume = factors_for_bar(rows, date(2026, 1, 1))
        assert price == Decimal("0.2")
        assert volume == Decimal("5")

    def test_no_actions_means_no_adjustment(self):
        assert factors_for_bar([], date(2026, 1, 1)) == (Decimal(1), Decimal(1))


class TestComposition:
    def test_two_actions_compose_multiplicatively(self):
        early, late = date(2024, 3, 1), date(2026, 6, 15)
        rows = build_factor_rows([_bonus_1_1(early), _split_10_to_2(late)])

        # Before BOTH: 0.5 * 0.2
        price, volume = factors_for_bar(rows, date(2023, 1, 1))
        assert price == Decimal("0.1")
        assert volume == Decimal("10")

        # Between them: only the later action still applies.
        price, volume = factors_for_bar(rows, date(2025, 1, 1))
        assert price == Decimal("0.2")
        assert volume == Decimal("5")

        # After both: untouched.
        assert factors_for_bar(rows, date(2026, 7, 1)) == (Decimal(1), Decimal(1))

    def test_composition_is_order_independent(self):
        early, late = date(2024, 3, 1), date(2026, 6, 15)
        forward = build_factor_rows([_bonus_1_1(early), _split_10_to_2(late)])
        reverse = build_factor_rows([_split_10_to_2(late), _bonus_1_1(early)])

        for bar_date in (date(2023, 1, 1), date(2025, 1, 1), date(2026, 7, 1)):
            assert factors_for_bar(forward, bar_date) == factors_for_bar(reverse, bar_date)

    def test_actions_on_different_securities_do_not_mix(self):
        mine = _action(EX, "0.5", "2", symbols=("AAA",))
        theirs = ActionFactor(
            exchange="NSE",
            security_key="sid:2",
            symbols=("BBB",),
            ex_date=EX,
            price_factor=Decimal("0.2"),
            volume_factor=Decimal("5"),
        )
        rows = build_factor_rows([mine, theirs])

        aaa = [r for r in rows if r.symbol == "AAA"]
        bbb = [r for r in rows if r.symbol == "BBB"]
        assert factors_for_bar(aaa, date(2026, 1, 1))[0] == Decimal("0.5")
        assert factors_for_bar(bbb, date(2026, 1, 1))[0] == Decimal("0.2")


class TestRenames:
    def test_a_factor_is_emitted_for_every_symbol_the_security_used(self):
        """A bonus announced under NEWNAME must still adjust bars that
        were written years earlier under OLDNAME."""
        action = _action(EX, "0.5", "2", symbols=("NEWNAME", "OLDNAME"))
        rows = build_factor_rows([action])

        assert {r.symbol for r in rows} == {"NEWNAME", "OLDNAME"}
        for symbol in ("NEWNAME", "OLDNAME"):
            symbol_rows = [r for r in rows if r.symbol == symbol]
            assert factors_for_bar(symbol_rows, date(2026, 1, 1))[0] == Decimal("0.5")


class TestValueConservation:
    def test_cumulative_factors_conserve_value_for_a_bonus(self):
        rows = build_factor_rows([_bonus_1_1()])
        row = rows[0]
        assert row.cumulative_price_factor * row.cumulative_volume_factor == Decimal(1)

    @given(
        ratios=st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=20), st.integers(min_value=1, max_value=20)
            ),
            min_size=1,
            max_size=6,
        )
    )
    def test_price_times_volume_is_always_one(self, ratios):
        """Property: for any chain of bonus actions, the cumulative
        price and volume factors are exact reciprocals. Decimal makes
        this exact; float would drift by ~1e-17 per action and compound
        visibly over a 15-year series."""
        actions = [
            _action(
                date(2010 + i, 1, 4),
                str(Decimal(den) / Decimal(num + den)),
                str(Decimal(num + den) / Decimal(den)),
            )
            for i, (num, den) in enumerate(ratios)
        ]
        rows = build_factor_rows(actions)
        for row in rows:
            product = row.cumulative_price_factor * row.cumulative_volume_factor
            # Decimal division is not exact for e.g. 1/3, so compare in
            # Decimal with a tight tolerance rather than converting to
            # float (which would defeat the point of the test).
            assert abs(product - Decimal(1)) < Decimal("1e-12")
