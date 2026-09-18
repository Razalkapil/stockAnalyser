"""Free-text corporate-action subject parser.

NSE's corporate-actions API returns a free-text ``subject`` field (e.g.
"Dividend - Rs 17.70 Per Share", "Bonus 1:1", "Face Value Split From Rs
10 To Rs 2") rather than structured fields. This module is the single
place that turns that prose into typed, price/volume-adjusting facts.

THE RULE THIS MODULE EXISTS TO ENFORCE: an unrecognised subject must
NEVER silently become a no-op action. A subject that matches nothing
returns ``parse_status="unparsed"`` with ``price_factor=None`` --
never ``price_factor=1.0`` as a "safe-looking" default. That specific
silent default is how a real 1:1 bonus, phrased in a way this parser
doesn't yet recognise, becomes a phantom 50% price crash in every chart
and every backtest that touches the symbol afterwards: the raw price
series looks like it halved overnight, and nothing about a fallback of
1.0 would have flagged the corporate action as unhandled.

A compound subject ("Dividend - Rs 5 Per Share and Bonus 1:1") must
parse to TWO ParsedAction records, not one merged/lossy one.
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

PARSER_VERSION = 1


class ActionType(StrEnum):
    DIVIDEND = "DIVIDEND"
    BONUS = "BONUS"
    SPLIT = "SPLIT"
    RIGHTS = "RIGHTS"
    BUYBACK = "BUYBACK"
    CONSOLIDATION = "CONSOLIDATION"
    DEMERGER = "DEMERGER"
    AGM = "AGM"
    OTHER = "OTHER"


class ParsedAction(BaseModel):
    action_type: ActionType
    dividend_per_share: Decimal | None = None
    ratio_numerator: int | None = None
    ratio_denominator: int | None = None
    face_value_from: Decimal | None = None
    face_value_to: Decimal | None = None
    price_factor: Decimal | None = None
    volume_factor: Decimal | None = None


class ParseResult(BaseModel):
    """Outcome of parsing one subject string.

    ``status`` is "parsed" (one or more ParsedAction produced, all
    price/volume-affecting fields populated), "ambiguous" (recognised
    the action type but could not extract a clean ratio/amount -- e.g.
    a malformed number), or "unparsed" (subject matched no known
    pattern at all). Only "parsed" rows should feed into
    adjustment_factors.
    """

    status: str  # "parsed" | "ambiguous" | "unparsed"
    actions: list[ParsedAction] = []


# --- Regexes, ordered from most to least specific -------------------------

_DIVIDEND_RE = re.compile(
    r"(?:interim\s+|final\s+|special\s+)?dividend\s*-?\s*rs\.?\s*([\d,]+(?:\.\d+)?)\s*per\s*share",
    re.IGNORECASE,
)
_BONUS_RE = re.compile(
    r"bonus(?:\s+issue)?\s+(\d+)\s*:\s*(\d+)",
    re.IGNORECASE,
)
_FACE_VALUE_SPLIT_RE = re.compile(
    r"face\s+value\s+split\s+from\s+rs\.?\s*([\d,]+(?:\.\d+)?)/?-?\s+to\s+rs\.?\s*([\d,]+(?:\.\d+)?)/?-?",
    re.IGNORECASE,
)
_RIGHTS_RE = re.compile(
    r"rights\s+(\d+)\s*:\s*(\d+)",
    re.IGNORECASE,
)
_CONSOLIDATION_RE = re.compile(r"consolidation\s+of\s+shares", re.IGNORECASE)
_BUYBACK_RE = re.compile(r"buy\s*-?\s*back", re.IGNORECASE)
_DEMERGER_RE = re.compile(r"demerger|scheme\s+of\s+arrangement", re.IGNORECASE)
_AGM_RE = re.compile(
    r"annual\s+general\s+meeting|extraordinary\s+general\s+meeting|\bagm\b|\begm\b",
    re.IGNORECASE,
)


def _parse_decimal(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def _parse_dividend(match: re.Match) -> ParsedAction:
    return ParsedAction(
        action_type=ActionType.DIVIDEND,
        dividend_per_share=_parse_decimal(match.group(1)),
        # Dividends do not adjust historical price series in this
        # codebase's convention (they are cash events, not price
        # events) -- factors are left None deliberately.
    )


def _parse_bonus(match: re.Match) -> ParsedAction:
    num, den = int(match.group(1)), int(match.group(2))
    # Bonus N:M means holders of M shares get N additional shares.
    # Post-bonus, (M + N) shares represent what M shares represented
    # pre-bonus, so pre-bonus prices must be scaled DOWN by M/(M+N) and
    # pre-bonus volumes scaled UP by (M+N)/M, so that
    # price_factor * volume_factor == 1 (value is conserved).
    price_factor = Decimal(den) / Decimal(num + den)
    volume_factor = Decimal(num + den) / Decimal(den)
    return ParsedAction(
        action_type=ActionType.BONUS,
        ratio_numerator=num,
        ratio_denominator=den,
        price_factor=price_factor,
        volume_factor=volume_factor,
    )


def _parse_face_value_split(match: re.Match) -> ParsedAction:
    fv_from = _parse_decimal(match.group(1))
    fv_to = _parse_decimal(match.group(2))
    if fv_from <= 0 or fv_to <= 0:
        # Malformed numbers (e.g. a zero face value) -- recognised the
        # pattern but cannot compute a safe factor. Ambiguous, not parsed.
        return ParsedAction(
            action_type=ActionType.SPLIT, face_value_from=fv_from, face_value_to=fv_to
        )
    ratio = fv_from / fv_to  # e.g. 10 -> 2 means each old share becomes 5 new shares
    price_factor = Decimal(1) / ratio
    volume_factor = ratio
    return ParsedAction(
        action_type=ActionType.SPLIT,
        face_value_from=fv_from,
        face_value_to=fv_to,
        price_factor=price_factor,
        volume_factor=volume_factor,
    )


def _parse_rights(match: re.Match) -> ParsedAction:
    num, den = int(match.group(1)), int(match.group(2))
    # Rights issues are price-affecting but require the subscription
    # price (frequently absent or in a separate field) to compute a
    # theoretical ex-rights price -- deliberately left as ambiguous
    # (no factor) until that is available. Recording the ratio is still
    # useful for audit/UI purposes.
    return ParsedAction(action_type=ActionType.RIGHTS, ratio_numerator=num, ratio_denominator=den)


_SIMPLE_MATCHERS: list[tuple[re.Pattern, ActionType]] = [
    (_CONSOLIDATION_RE, ActionType.CONSOLIDATION),
    (_BUYBACK_RE, ActionType.BUYBACK),
    (_DEMERGER_RE, ActionType.DEMERGER),
    (_AGM_RE, ActionType.AGM),
]


class _ClauseResult(BaseModel):
    """Outcome of parsing a single clause of a (possibly compound) subject."""

    action: ParsedAction | None = None
    recognised: bool = False
    ambiguous: bool = False


def _parse_clause(clause: str) -> _ClauseResult:
    """Parse one clause (a compound subject split on "and"/"&") in isolation."""
    if m := _DIVIDEND_RE.search(clause):
        return _ClauseResult(action=_parse_dividend(m), recognised=True)

    if m := _BONUS_RE.search(clause):
        return _ClauseResult(action=_parse_bonus(m), recognised=True)

    if m := _FACE_VALUE_SPLIT_RE.search(clause):
        parsed = _parse_face_value_split(m)
        return _ClauseResult(action=parsed, recognised=True, ambiguous=parsed.price_factor is None)

    if m := _RIGHTS_RE.search(clause):
        # Rights issues always lack a computable factor here (need the
        # subscription price, which this parser does not yet consume).
        return _ClauseResult(action=_parse_rights(m), recognised=True, ambiguous=True)

    for pattern, action_type in _SIMPLE_MATCHERS:
        if pattern.search(clause):
            return _ClauseResult(action=ParsedAction(action_type=action_type), recognised=True)

    # Matched nothing. Do NOT silently drop it or treat the whole
    # subject as fully parsed -- surface it as ambiguous with no action.
    return _ClauseResult(recognised=False, ambiguous=True)


def parse_subject(subject: str) -> ParseResult:
    """Parse a free-text corporate-action subject into typed actions.

    Handles compound subjects ("X and Y") by parsing each clause
    independently and returning multiple ParsedAction records. Returns
    status="unparsed" (empty actions list) if NOTHING recognisable is
    found -- callers must treat this as a hard failure per
    ``ingest.fail_on_unparsed_corp_action``, never as a no-op.
    """
    text = subject.strip()
    if not text:
        return ParseResult(status="unparsed", actions=[])

    # Split compound subjects on " and " / " & " at the top level only
    # (not inside numbers), so "Dividend - Rs 5 Per Share and Bonus 1:1"
    # becomes two clauses.
    raw_clauses = re.split(r"\s+and\s+|\s*&\s*", text, flags=re.IGNORECASE)

    actions: list[ParsedAction] = []
    any_ambiguous = False
    any_recognised = False

    for raw_clause in raw_clauses:
        clause = raw_clause.strip()
        if not clause:
            continue

        result = _parse_clause(clause)
        if result.action is not None:
            actions.append(result.action)
        any_recognised = any_recognised or result.recognised
        any_ambiguous = any_ambiguous or result.ambiguous

    if not any_recognised:
        return ParseResult(status="unparsed", actions=[])
    if any_ambiguous:
        return ParseResult(status="ambiguous", actions=actions)
    return ParseResult(status="parsed", actions=actions)
