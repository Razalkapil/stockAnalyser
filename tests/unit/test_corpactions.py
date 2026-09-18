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


# --- Regressions from running the parser over 3,180 REAL NSE subjects -----------------------
#
# The original cases above were hand-written; real data showed ~1/3 of subjects unparsed.
# Every string below is copied verbatim from the live NSE corporates-corporateActions API
# (fetched 2026-09-19, --since 2025-06-01). The stakes: the unparsed set included 62 real
# STOCK SPLITS (a 5:1 split reads as an 80% crash if unadjusted).

REAL_DIVIDENDS = [
    "Dividend - Re 1 Per Share",  # singular "Re" -- 600 of these
    "Interim Dividend - Re 1 Per Share",
    "Dividend - Re 1 Per Sh",  # NSE truncates some subjects
    "Interim Dividend - Rs 0.75 Per Sh",
    "Dividend - Rs 160 Per Share & Special Dividend - Rs 375",  # no "Per Share" on the 2nd
    "Dividend - Rs 35 Per Share & Special Dividend Of Rs 100 Per Share/ Special Dividend Of Rs 30",
    "Interim Dividend - Re 0.75 Per Share & Special Dividend Rs 1.25 Per Share",
]


@pytest.mark.parametrize("subject", REAL_DIVIDENDS)
def test_real_dividend_subjects_parse_as_cash_events_with_no_price_factor(subject):
    r = parse_subject(subject)
    assert r.status == "parsed", subject
    assert all(a.action_type is ActionType.DIVIDEND for a in r.actions)
    assert all(a.price_factor is None for a in r.actions)  # cash events never adjust prices


def test_dividend_amount_with_singular_re():
    assert parse_subject("Dividend - Re 1 Per Share").actions[0].dividend_per_share == Decimal(1)
    assert parse_subject("Interim Dividend - Rs 0.75 Per Sh").actions[0].dividend_per_share == \
        Decimal("0.75")


REAL_SPLITS = [
    # (subject, face value from, to, price factor)
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", 10, 2, "0.2"),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share", 10, 1, "0.1"),
    ("Face Value Split (Sub-Division) - From Rs 5/- Per Share To Rs 1/- Per Share", 5, 1, "0.2"),
]


@pytest.mark.parametrize(("subject", "fv_from", "fv_to", "price_factor"), REAL_SPLITS)
def test_real_face_value_splits_are_parsed_into_correct_factors(
    subject, fv_from, fv_to, price_factor
):
    """The one that must never be missed: an unparsed split silently corrupts a price series."""
    r = parse_subject(subject)
    assert r.status == "parsed", subject
    (a,) = r.actions
    assert a.action_type is ActionType.SPLIT
    assert (a.face_value_from, a.face_value_to) == (Decimal(fv_from), Decimal(fv_to))
    assert a.price_factor == Decimal(price_factor)
    assert a.price_factor * a.volume_factor == Decimal(1)  # value conserved


def test_a_consolidation_with_face_values_is_a_reverse_split_with_factors():
    """VERTOZ: 'Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share'.
    10 old shares become 1, so historical prices scale UP by 10 and volumes DOWN by 10."""
    r = parse_subject("Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share")
    assert r.status == "parsed"
    (a,) = r.actions
    assert a.action_type is ActionType.CONSOLIDATION
    assert a.price_factor == Decimal(10) and a.volume_factor == Decimal("0.1")


def test_a_consolidation_with_no_numbers_stays_unadjustable_not_guessed():
    (a,) = parse_subject("Consolidation of shares").actions
    assert a.price_factor is None  # recognised, but we refuse to invent a ratio


REAL_DISTRIBUTIONS = [
    "Distribution - Rs 3.75 Per Unit Consisting Of Interest Rs 1.96 Per Unit/ Treasury Income Re "
    "0.01 Per Unit/Dividend Re 0.32 Per Unit/ Repayment Of Spv Loan Rs 1.46 Per Unit",
    "Distribution - Re 0.395 Per Unit Consists Of Re 0.392 Per Unit As Interest/ Re 0.003 Per "
    "Unit As Other Income",
    "Distribution Rs 1.60 Consists Of Rs 1.44 Per Unit As Interest/ Re 0.12 Per Unit As Return "
    "Of Capital/ Re 0.04 Per Unit As Exempt Dividend",
]


@pytest.mark.parametrize("subject", REAL_DISTRIBUTIONS)
def test_invit_reit_distributions_are_cash_events(subject):
    r = parse_subject(subject)
    assert r.status == "parsed", subject
    assert r.actions[0].action_type is ActionType.DISTRIBUTION
    assert r.actions[0].price_factor is None
    assert r.actions[0].dividend_per_share is not None


def test_a_bond_interest_payment_is_a_recognised_cash_event():
    r = parse_subject("Interest Payment")
    assert r.status == "parsed" and r.actions[0].action_type is ActionType.DISTRIBUTION


def test_rights_issues_remain_ambiguous_because_a_factor_needs_the_issue_price():
    """Unchanged, and deliberate: excluded from adjustment and COUNTED (job degraded)."""
    r = parse_subject("Rights 3:25 @ Premium Rs 1799/-")
    assert r.status == "ambiguous" and r.actions[0].price_factor is None


def test_genuinely_unknown_subjects_are_still_unparsed():
    """Widening the parser must not turn it into a catch-all."""
    for subject in ("Something Entirely New", "Distributionally Challenged", "Capital Reduction"):
        assert parse_subject(subject).status == "unparsed", subject


def test_a_distribution_with_no_rupee_marker_is_still_a_cash_event():
    """SEITINVIT, verbatim from the API: 'Distribution - 3.04316 Consisting Of ...'."""
    r = parse_subject("Distribution - 3.04316 Consisting Of Interest Rs 3.04013 Per Unit / "
                      "Other Income - Rs 0.00303")
    assert r.status == "parsed"
    assert r.actions[0].action_type is ActionType.DISTRIBUTION
    assert r.actions[0].dividend_per_share == Decimal("3.04316")


def test_any_rights_wording_is_recognised_as_rights_never_unparsed():
    """QUINT, verbatim: 'Rights - 7 Ccps And 7 Warrants:40'. Rights are a KNOWN action type we
    deliberately cannot compute a factor for, so an exotic wording must land as recognised-but-
    ambiguous (counted, run marked degraded) -- not as an unknown subject that fails the run."""
    r = parse_subject("Rights - 7 Ccps And 7 Warrants:40")
    assert r.status == "ambiguous"
    assert r.actions[0].action_type is ActionType.RIGHTS
    assert r.actions[0].price_factor is None
    assert r.actions[0].ratio_numerator is None  # no ratio was extractable; none is invented
