"""Free-text corporate-action subject parser, plus the fetch/parse/
upsert orchestration that uses it.

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
import sqlite3
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from stk.core.errors import ParseError
from stk.ingest.jobs import job_run
from stk.providers.base import RawCorporateAction
from stk.providers.registry import get_corporate_actions_provider
from stk.store.db.engine import connect, transaction

#: 2: real-data pass over 3,180 NSE subjects -- singular "Re", truncated "Per Sh", the
#: "(Sub-Division)" split wording, face-value consolidations, InvIT/REIT distributions,
#: bond interest payments. v1 rows (none survive in a fresh DB) parsed ~2/3 of real subjects.
#: 3: the 193 subjects v2 left unparsed over 2021-2026 -- "Bonus- 1:2" (a real bonus: AJANTPHARM's
#: adjusted series showed a phantom 34% crash), EGM spellings, "Divdend"/"Div", "Rs - 2.10",
#: InvIT interest/return-of-capital payouts, capital reductions, bond redemptions.
PARSER_VERSION = 3


class ActionType(StrEnum):
    DIVIDEND = "DIVIDEND"
    DISTRIBUTION = "DISTRIBUTION"  # InvIT/REIT unit payouts, bond interest: cash, like a dividend
    BONUS = "BONUS"
    SPLIT = "SPLIT"
    RIGHTS = "RIGHTS"
    BUYBACK = "BUYBACK"
    CONSOLIDATION = "CONSOLIDATION"
    CAPITAL_REDUCTION = "CAPITAL_REDUCTION"  # price-affecting; the subject never carries a ratio
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

# "Rs", "Rs." and the SINGULAR "Re" all appear ("Dividend - Re 1 Per Share" is ~600 of the real
# subjects); NSE also truncates some subjects to "Per Sh". Cash events never adjust prices, so
# being liberal on them cannot corrupt a series -- unlike splits/bonuses, matched strictly below.
_RUPEE = r"(?:rs|re)\.?"
_AMOUNT = r"([\d,]+(?:\.\d+)?)"
# "Divdend", "Div". No leading \b: NSE glues words ("Interimdividend", "Meetingdividend"); the
# trailing \b is what keeps "Sub-Division" out.
_DIVIDEND_WORD = r"(?:interim\s+|final\s+|special\s+)?div(?:idend|dend)?\b"
_DIVIDEND_RE = re.compile(
    rf"{_DIVIDEND_WORD}\s*(?:-|of)?\s*(?:{_RUPEE}\s*-?\s*)?{_AMOUNT}",
    re.IGNORECASE,
)
# A dividend whose amount is missing or garbled ("Interim Dividend", "Rs Per 0.50 Share"). Cash
# never adjusts prices, so this is recognised -- but ambiguous, since there is no amount to credit.
_DIVIDEND_ANY_RE = re.compile(rf"^\s*{_DIVIDEND_WORD}", re.IGNORECASE)
# Checked BEFORE dividends: a distribution's own text contains "Dividend Re 0.32 Per Unit",
# which would otherwise be misread as the whole payout.
_DISTRIBUTION_WORD = r"distr\w*ion\b"  # also NSE's "Distritbution"
_DISTRIBUTION_RE = re.compile(
    rf"{_DISTRIBUTION_WORD}\s*(?:-|of)?\s*(?:{_RUPEE}\s*)?{_AMOUNT}", re.IGNORECASE
)
# InvIT/REIT unit payouts split into components with no single total ("Interest Amount - Rs
# 1.20 Per Unit/ Return On Capital - Rs 0.80 Per Unit", "Nterest Amount- Rs 3.0556/..."). Cash,
# recognised, ambiguous: summing free-text components is a guess this parser does not make.
_UNIT_PAYOUT_RE = re.compile(
    rf"^\s*(?:\w+\s+)?(?:{_DISTRIBUTION_WORD}|i?nterest\b|return\s+o[nf]\s+capital)",
    re.IGNORECASE,
)
# A bond/G-sec series repaying principal ("Redemption"): the instrument ends; no equity series.
_REDEMPTION_RE = re.compile(r"^\s*redemption\b", re.IGNORECASE)
_INTEREST_PAYMENT_RE = re.compile(r"^\s*interest\s+payment\b", re.IGNORECASE)
_BONUS_RE = re.compile(
    r"bonus(?:\s+issue)?\s*-?\s*(\d+)\s*:\s*(\d+)",  # "Bonus- 1:2" is a real subject
    re.IGNORECASE,
)
# Any other bonus ("Bonus Ncrps 1:116" -- preference shares, not equity): price-affecting, but
# not an equity share ratio. Recognised and ambiguous, so it is counted rather than applied.
_BONUS_ANY_RE = re.compile(r"^\s*bonus\b", re.IGNORECASE)
_CAPITAL_REDUCTION_RE = re.compile(r"capital\s+reduction", re.IGNORECASE)
_FROM_TO = (
    rf"from\s+{_RUPEE}\s*{_AMOUNT}\s*/?-?\s*(?:per\s*sh(?:are)?\s+)?to\s+{_RUPEE}\s*{_AMOUNT}"
)
_FACE_VALUE_SPLIT_RE = re.compile(
    rf"face\s+value\s+split(?:\s*\(\s*sub-?\s*division\s*\))?\s*-?\s*{_FROM_TO}",
    re.IGNORECASE,
)
_CONSOLIDATION_VALUES_RE = re.compile(
    rf"consolidation\s+of\s+(?:equity\s+)?shares\s+{_FROM_TO}", re.IGNORECASE
)
_RIGHTS_RE = re.compile(
    r"rights\s+(\d+)\s*:\s*(\d+)",
    re.IGNORECASE,
)
# ANY subject that opens with "Rights" is a rights issue, whatever the wording (real example:
# "Rights - 7 Ccps And 7 Warrants:40"). We cannot compute a factor for one either way, so the
# exact ratio text is irrelevant to the limitation; what matters is that it is RECOGNISED
# (counted, run degraded) rather than treated as an unknown subject that fails the whole run.
_RIGHTS_ANY_RE = re.compile(r"^\s*rights\b", re.IGNORECASE)
_CONSOLIDATION_RE = re.compile(r"consolidation\s+of\s+(?:equity\s+)?shares", re.IGNORECASE)
_BUYBACK_RE = re.compile(r"buy\s*-?\s*back", re.IGNORECASE)
_DEMERGER_RE = re.compile(r"demerger|scheme\s+of\s+arr?angement", re.IGNORECASE)
# EGMs are informational like AGMs; NSE spells them "Extra Ordinary", "Extra-Ordinary", "Entra
# Ordinary", "Extra Oridinary", "Extra General Meeting", "... Meting". Liberal on purpose: a
# meeting has no price effect, and every price rule is tried before this one.
_AGM_RE = re.compile(r"general\s+me\w*?t|\bagm\b|\begm\b", re.IGNORECASE)


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


def _parse_distribution(match: re.Match) -> ParsedAction:
    # Cash to unit holders: no price factor, same convention as a dividend.
    return ParsedAction(
        action_type=ActionType.DISTRIBUTION, dividend_per_share=_parse_decimal(match.group(1))
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


def _parse_face_value_split(
    match: re.Match, action_type: ActionType = ActionType.SPLIT
) -> ParsedAction:
    """A face-value change, used for both splits (10 -> 2) and consolidations (1 -> 10).

    The same arithmetic covers both: old/new face value is how many NEW shares one OLD share
    becomes, so prices before the ex-date scale by its inverse and volumes by it. A
    consolidation is just a ratio below 1 (Re 1 -> Rs 10 gives price x10, volume x0.1).
    """
    fv_from = _parse_decimal(match.group(1))
    fv_to = _parse_decimal(match.group(2))
    if fv_from <= 0 or fv_to <= 0:
        # Malformed numbers (e.g. a zero face value) -- recognised the
        # pattern but cannot compute a safe factor. Ambiguous, not parsed.
        return ParsedAction(action_type=action_type, face_value_from=fv_from, face_value_to=fv_to)
    ratio = fv_from / fv_to  # e.g. 10 -> 2 means each old share becomes 5 new shares
    price_factor = Decimal(1) / ratio
    volume_factor = ratio
    return ParsedAction(
        action_type=action_type,
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


def _cash_dividend(m: re.Match) -> _ClauseResult:
    return _ClauseResult(action=_parse_dividend(m), recognised=True)


def _cash_distribution(m: re.Match) -> _ClauseResult:
    return _ClauseResult(action=_parse_distribution(m), recognised=True)


def _bond_interest(_m: re.Match) -> _ClauseResult:
    # A bond coupon: cash to holders, amount not in the subject. Not an equity price event.
    return _ClauseResult(action=ParsedAction(action_type=ActionType.DISTRIBUTION), recognised=True)


def _ambiguous(action_type: ActionType) -> Callable[[re.Match], _ClauseResult]:
    def build(_m: re.Match) -> _ClauseResult:
        return _ClauseResult(action=ParsedAction(action_type=action_type), recognised=True,
                             ambiguous=True)

    return build


def _bonus(m: re.Match) -> _ClauseResult:
    return _ClauseResult(action=_parse_bonus(m), recognised=True)


def _face_value_change(action_type: ActionType) -> Callable[[re.Match], _ClauseResult]:
    def build(m: re.Match) -> _ClauseResult:
        parsed = _parse_face_value_split(m, action_type)
        return _ClauseResult(action=parsed, recognised=True, ambiguous=parsed.price_factor is None)

    return build


def _rights_any(_m: re.Match) -> _ClauseResult:
    return _ClauseResult(action=ParsedAction(action_type=ActionType.RIGHTS), recognised=True,
                         ambiguous=True)


def _rights(m: re.Match) -> _ClauseResult:
    # Rights issues always lack a computable factor here (need the subscription price, which
    # this parser does not yet consume).
    return _ClauseResult(action=_parse_rights(m), recognised=True, ambiguous=True)


#: ORDER MATTERS. A distribution's own text contains "Dividend Re 0.32 Per Unit", so
#: distributions are tried before dividends or that fragment would be read as the payout.
_CLAUSE_RULES: list[tuple[re.Pattern, Callable[[re.Match], _ClauseResult]]] = [
    (_DISTRIBUTION_RE, _cash_distribution),
    (_INTEREST_PAYMENT_RE, _bond_interest),
    (_REDEMPTION_RE, _bond_interest),
    (_DIVIDEND_RE, _cash_dividend),
    # After dividends, so "Interest - Rs 1.24/.../Dividend - Rs 2.21 Per Unit" keeps the v2 reading.
    (_UNIT_PAYOUT_RE, _ambiguous(ActionType.DISTRIBUTION)),
    (_DIVIDEND_ANY_RE, _ambiguous(ActionType.DIVIDEND)),
    (_BONUS_RE, _bonus),
    (_BONUS_ANY_RE, _ambiguous(ActionType.BONUS)),  # after the ratio form, as for rights
    (_CAPITAL_REDUCTION_RE, _ambiguous(ActionType.CAPITAL_REDUCTION)),
    (_FACE_VALUE_SPLIT_RE, _face_value_change(ActionType.SPLIT)),
    (_CONSOLIDATION_VALUES_RE, _face_value_change(ActionType.CONSOLIDATION)),
    (_RIGHTS_RE, _rights),
    (_RIGHTS_ANY_RE, _rights_any),  # after the ratio form, so a parseable ratio is kept
]


def _parse_clause(clause: str) -> _ClauseResult:
    """Parse one clause (a compound subject split on "and"/"&") in isolation."""
    for pattern, build in _CLAUSE_RULES:
        if m := pattern.search(clause):
            return build(m)

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


# --- Fetch/parse/upsert orchestration --------------------------------------


class UnparsedCorporateActionsError(ParseError):
    """Raised AFTER every row has been stored, naming every subject that matched nothing.

    A ParseError subclass so existing handlers keep working. Carries the full result so a
    caller can still see what landed (notably ``new_ex_dates``, which say the adjusted price
    series is stale even though the run failed).
    """

    def __init__(self, unparsed: list[tuple[str, str]], result: CorpActionIngestResult) -> None:
        self.unparsed = unparsed
        self.result = result
        shown = "; ".join(f"{sym}: {subject!r}" for sym, subject in unparsed[:5])
        more = f" (+{len(unparsed) - 5} more)" if len(unparsed) > 5 else ""
        super().__init__(
            f"{len(unparsed)} unparsed corporate-action subject(s) -- {shown}{more}. All rows "
            "were stored (unparsed ones as parse_status='unparsed'); extend the parser or review "
            "them before trusting the adjusted price series."
        )


class CorpActionIngestResult:
    def __init__(
        self,
        fetched: int,
        upserted: int,
        unparsed: int,
        new_ex_dates: set[date] | None = None,
    ) -> None:
        self.fetched = fetched
        self.upserted = upserted
        self.unparsed = unparsed
        #: Ex-dates of rows this run actually INSERTED (not merely
        #: re-saw). Non-empty means the adjusted price series is now
        #: stale and must be rebuilt -- see ingest.adjustments.
        self.new_ex_dates: set[date] = new_ex_dates or set()


def _resolve_security_id(conn: sqlite3.Connection, *, exchange: str, symbol: str) -> int | None:
    row = conn.execute(
        "SELECT security_id FROM listings WHERE exchange=? AND symbol=?", (exchange, symbol)
    ).fetchone()
    return int(row["security_id"]) if row is not None else None


def _typed_columns(result: ParseResult) -> tuple[object, ...]:
    """The parser-derived columns, in schema order: action_type through parser_version.

    A compound subject can produce multiple ParsedAction rows; only the first is used for the
    typed factor columns (price/volume adjustment only ever applies once per ex-date in this
    schema) -- subject_raw itself is preserved verbatim regardless, so nothing about a second
    clause (e.g. "and Bonus 1:1") is lost to a reader. No stored subject has two price-affecting
    clauses (checked over 2021-2026); one that did would lose its second factor here.
    """
    action = result.actions[0] if result.actions else None
    return (
        action.action_type.value if action else None,
        float(action.dividend_per_share) if action and action.dividend_per_share else None,
        action.ratio_numerator if action else None,
        action.ratio_denominator if action else None,
        float(action.face_value_from) if action and action.face_value_from else None,
        float(action.face_value_to) if action and action.face_value_to else None,
        float(action.price_factor) if action and action.price_factor is not None else None,
        float(action.volume_factor) if action and action.volume_factor is not None else None,
        result.status,
        PARSER_VERSION,
    )


_TYPED_COLUMNS = (
    "action_type", "dividend_per_share", "ratio_numerator", "ratio_denominator",
    "face_value_from", "face_value_to", "price_factor", "volume_factor", "parse_status",
    "parser_version",
)


class ReparseResult(BaseModel):
    reparsed: int
    #: (old parse_status, new parse_status) -> count, for rows whose status changed.
    transitions: dict[str, int]
    #: Ex-dates of rows that gained or changed a price factor: the adjusted series is stale.
    changed_price_ex_dates: set[date]
    still_unparsed: list[tuple[str, str]]


def _reparse_rows(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> ReparseResult:
    transitions: dict[str, int] = {}
    changed: set[date] = set()
    still_unparsed: list[tuple[str, str]] = []
    assignments = ", ".join(f"{c}=?" for c in _TYPED_COLUMNS)
    for row in rows:
        result = parse_subject(row["subject_raw"])
        columns = _typed_columns(result)
        conn.execute(
            f"UPDATE corporate_actions SET {assignments} WHERE ca_id=?",
            (*columns, row["ca_id"]),
        )
        if result.status != row["parse_status"]:
            key = f"{row['parse_status']}->{result.status}"
            transitions[key] = transitions.get(key, 0) + 1
        new_factor = columns[_TYPED_COLUMNS.index("price_factor")]
        if new_factor != row["price_factor"] and row["ex_date"]:
            changed.add(date.fromisoformat(row["ex_date"]))
        if result.status == "unparsed":
            still_unparsed.append((row["symbol"], row["subject_raw"]))
    return ReparseResult(reparsed=len(rows), transitions=transitions,
                         changed_price_ex_dates=changed, still_unparsed=still_unparsed)


def reparse_stored_actions(*, sqlite_path: Path) -> ReparseResult:
    """Re-run the CURRENT parser over stored rows written by an older one. No network.

    Rows are keyed on (source, source_hash) and inserted ON CONFLICT DO NOTHING, so a parser
    fix never reaches rows already stored -- re-fetching changes nothing. subject_raw is kept
    verbatim for exactly this. Only the parser-derived columns are rewritten.
    """
    conn = connect(sqlite_path)
    try:
        with job_run(conn, "reparse_corporate_actions") as handle:
            rows = conn.execute(
                "SELECT ca_id, symbol, ex_date, subject_raw, parse_status, price_factor "
                "FROM corporate_actions WHERE parser_version IS NULL OR parser_version < ?",
                (PARSER_VERSION,),
            ).fetchall()
            with transaction(conn):  # all rows re-parsed, or none
                result = _reparse_rows(conn, rows)
            handle.rows_in = len(rows)
            handle.rows_written = len(rows)
            handle.metrics.update(result.transitions)
            handle.metrics["unparsed"] = len(result.still_unparsed)
            handle.metrics["changed_price_ex_dates"] = len(result.changed_price_ex_dates)
        return result
    finally:
        conn.close()


def _upsert_action(conn: sqlite3.Connection, raw: RawCorporateAction) -> tuple[str, bool]:
    """Parse raw.subject_raw and upsert one corporate_actions row keyed
    on (source, source_hash) -- re-ingesting an unchanged action is a
    no-op; NSE correcting a date or subject produces a NEW source_hash
    (a different, distinguishable row), never an in-place mutation.

    Returns (parse_status, inserted). ``inserted`` distinguishes a
    genuinely new action from a re-seen one, which is what tells the
    caller whether the adjusted price series needs rebuilding.

    An unparsed subject is STORED (parse_status='unparsed'), never dropped and never turned
    into a no-op. Failing on it is the caller's job, and happens only after the whole batch
    has been stored -- see ``ingest_corporate_actions``.
    """
    result = parse_subject(raw.subject_raw)
    security_id = _resolve_security_id(conn, exchange=raw.exchange, symbol=raw.symbol)

    changes_before = conn.total_changes
    conn.execute(
        """INSERT INTO corporate_actions
               (security_id, isin, symbol, exchange, ex_date, record_date, bc_start_date,
                bc_end_date, subject_raw, action_type, dividend_per_share, ratio_numerator,
                ratio_denominator, face_value_from, face_value_to, price_factor, volume_factor,
                parse_status, parser_version, source, source_hash, captured_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (source, source_hash) DO NOTHING""",
        (
            security_id, raw.isin, raw.symbol, raw.exchange,
            raw.ex_date.isoformat() if raw.ex_date else None,
            raw.record_date.isoformat() if raw.record_date else None,
            raw.bc_start_date.isoformat() if raw.bc_start_date else None,
            raw.bc_end_date.isoformat() if raw.bc_end_date else None,
            raw.subject_raw,
            *_typed_columns(result),
            raw.source, raw.source_hash,
            raw.captured_at.isoformat(),
        ),
    )
    # ON CONFLICT DO NOTHING means rowcount is unreliable across
    # drivers; the connection's total_changes delta is not.
    inserted = conn.total_changes > changes_before
    return result.status, inserted


def ingest_corporate_actions(
    *,
    sqlite_path: Path,
    since: date | None = None,
    fail_on_unparsed: bool = True,
    provider_name: str = "nse_corp_actions",
) -> CorpActionIngestResult:
    """Fetch corporate actions, parse subjects, and upsert into
    corporate_actions. One job_run scope covers fetch through upsert,
    same single-scope pattern as ingest.daily -- see jobs.py's
    docstring for why a failure during fetch must be just as visible
    as one during parsing.

    fail_on_unparsed defaults to True, matching
    config/defaults.yaml's ingest.fail_on_unparsed_corp_action -- an
    unrecognised subject FAILS the run (after storing every row) rather than silently
    defaulting to a no-op action (see this module's top docstring).
    """
    conn = connect(sqlite_path)
    try:
        with job_run(conn, "ingest_corporate_actions", business_date=since) as handle:
            provider = get_corporate_actions_provider(provider_name)
            raw_actions = provider.fetch_actions(since)

            upserted = 0
            unparsed_rows: list[tuple[str, str]] = []
            new_ex_dates: set[date] = set()
            for raw in raw_actions:
                status, inserted = _upsert_action(conn, raw)
                upserted += 1
                if status == "unparsed":
                    unparsed_rows.append((raw.symbol, raw.subject_raw))
                if inserted and raw.ex_date is not None:
                    new_ex_dates.add(raw.ex_date)

            handle.rows_in = len(raw_actions)
            handle.rows_written = upserted
            handle.metrics["unparsed"] = len(unparsed_rows)
            handle.metrics["new_ex_dates"] = len(new_ex_dates)
            result = CorpActionIngestResult(
                len(raw_actions), upserted, len(unparsed_rows), new_ex_dates
            )
            # Fail LOUDLY, but only now that every good row behind a bad one is safely stored:
            # raising on the first unparsed subject used to discard the real splits after it.
            if unparsed_rows and fail_on_unparsed:
                raise UnparsedCorporateActionsError(unparsed_rows, result)

        return result
    finally:
        conn.close()
