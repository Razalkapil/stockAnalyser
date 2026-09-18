"""Table-driven tests for the free-text corporate-action subject parser.

The critical property this file enforces: an unrecognised subject must
NEVER produce a silent no-op (action_type=OTHER, price_factor=1.0).
That specific silent default is how a missed 1:1 bonus becomes a
phantom 50% price crash in every downstream chart and backtest. See
ingest/corpactions.py's module docstring for the full rationale.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stk.ingest.corpactions import ActionType, parse_subject

# (subject, expected_status, expected_action_types)
PARSE_CASES = [
    ("Dividend - Rs 17.70 Per Share", "parsed", [ActionType.DIVIDEND]),
    ("Interim Dividend - Rs 5 Per Share", "parsed", [ActionType.DIVIDEND]),
    ("Dividend Rs.2.50 Per Share", "parsed", [ActionType.DIVIDEND]),
    ("Final Dividend - Rs 10 Per Share", "parsed", [ActionType.DIVIDEND]),
    ("Bonus 1:1", "parsed", [ActionType.BONUS]),
    ("Bonus Issue 3:5", "parsed", [ActionType.BONUS]),
    ("Face Value Split From Rs 10 To Rs 2", "parsed", [ActionType.SPLIT]),
    ("Face Value Split From Rs.10/- To Rs.1/-", "parsed", [ActionType.SPLIT]),
    ("Consolidation of shares", "parsed", [ActionType.CONSOLIDATION]),
    ("Rights 1:4 @ Premium Rs 50", "ambiguous", [ActionType.RIGHTS]),
    ("Annual General Meeting", "parsed", [ActionType.AGM]),
    ("Scheme of Arrangement", "parsed", [ActionType.DEMERGER]),
    ("Buy-Back", "parsed", [ActionType.BUYBACK]),
    (
        "Dividend - Rs 5 Per Share and Bonus 1:1",
        "parsed",
        [ActionType.DIVIDEND, ActionType.BONUS],
    ),
]


@pytest.mark.parametrize(("subject", "expected_status", "expected_types"), PARSE_CASES)
def test_known_subjects_parse_correctly(subject, expected_status, expected_types):
    result = parse_subject(subject)
    assert result.status == expected_status, f"subject={subject!r}"
    assert [a.action_type for a in result.actions] == expected_types, f"subject={subject!r}"


def test_dividend_amount_extracted():
    result = parse_subject("Dividend - Rs 17.70 Per Share")
    assert result.actions[0].dividend_per_share == Decimal("17.70")


def test_bonus_ratio_extracted():
    result = parse_subject("Bonus 1:1")
    action = result.actions[0]
    assert action.ratio_numerator == 1
    assert action.ratio_denominator == 1


def test_bonus_35_ratio_extracted():
    result = parse_subject("Bonus Issue 3:5")
    action = result.actions[0]
    assert action.ratio_numerator == 3
    assert action.ratio_denominator == 5


def test_face_value_split_factors():
    result = parse_subject("Face Value Split From Rs 10 To Rs 2")
    action = result.actions[0]
    assert action.face_value_from == Decimal("10")
    assert action.face_value_to == Decimal("2")
    # 5-for-1 split: price should scale down by 1/5, volume up by 5.
    assert action.price_factor == Decimal("1") / Decimal("5")
    assert action.volume_factor == Decimal("5")


# --- The critical negative test --------------------------------------------


UNRECOGNISED_SUBJECTS = [
    "",
    "Some Entirely Novel Corporate Action Nobody Has Seen Before",
    "Merger of XYZ Limited with ABC Limited effective from a date TBD",
    "Change of Company Name",
]


@pytest.mark.parametrize("subject", UNRECOGNISED_SUBJECTS)
def test_unrecognised_subject_is_unparsed_not_silently_defaulted(subject):
    """An unrecognised subject must be flagged unparsed with NO actions --
    never silently treated as a no-op (action_type=OTHER, factor=1.0).
    """
    result = parse_subject(subject)
    assert result.status == "unparsed"
    assert result.actions == []
    # Explicitly assert the dangerous silent-default shape never appears.
    for action in result.actions:
        looks_like_other = action.action_type == ActionType.OTHER
        looks_like_unity = action.price_factor == Decimal("1.0")
        assert not (looks_like_other and looks_like_unity)


def test_compound_subject_produces_two_actions_not_one_merged():
    result = parse_subject("Dividend - Rs 5 Per Share and Bonus 1:1")
    assert len(result.actions) == 2
    assert result.actions[0].action_type == ActionType.DIVIDEND
    assert result.actions[0].dividend_per_share == Decimal("5")
    assert result.actions[1].action_type == ActionType.BONUS
    assert result.actions[1].ratio_numerator == 1
    assert result.actions[1].ratio_denominator == 1


# --- Property-based test: value conservation for BONUS/SPLIT ---------------


@given(num=st.integers(min_value=1, max_value=20), den=st.integers(min_value=1, max_value=20))
def test_bonus_price_and_volume_factors_conserve_value(num, den):
    result = parse_subject(f"Bonus {num}:{den}")
    assert result.status == "parsed"
    action = result.actions[0]
    product = action.price_factor * action.volume_factor
    assert abs(product - Decimal("1")) < Decimal("0.0000001")


@given(
    fv_from=st.integers(min_value=1, max_value=1000),
    fv_to=st.integers(min_value=1, max_value=1000),
)
def test_split_price_and_volume_factors_conserve_value(fv_from, fv_to):
    result = parse_subject(f"Face Value Split From Rs {fv_from} To Rs {fv_to}")
    assert result.status == "parsed"
    action = result.actions[0]
    product = action.price_factor * action.volume_factor
    assert abs(product - Decimal("1")) < Decimal("0.0000001")
