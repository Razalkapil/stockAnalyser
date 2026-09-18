"""Strategy DSL: schema strictness, semantic validation, interpreter semantics, seeds."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from stk.config.horizons import load_horizons
from stk.domain.dsl.catalogue import CATALOGUE, all_columns
from stk.domain.dsl.evaluate import (
    add_prev_columns,
    entry_mask,
    explain,
    scores,
)
from stk.domain.dsl.model import StrategySpec
from stk.domain.dsl.validate import param_combinations, validate_spec
from stk.domain.indicators import compute_indicators

REPO = Path(__file__).parent.parent.parent
SEEDS = sorted((REPO / "config" / "strategies").glob("*.json"))
HORIZONS = load_horizons()


def spec_dict(**overrides) -> dict:
    base = {
        "slug": "unit_test_strategy", "name": "Unit test strategy", "horizon": "swing",
        "entry": {"left": {"ind": "rsi", "period": 14}, "op": "<", "right": 30},
        "exit": {"stop": {"type": "pct", "value": 0.1}, "max_hold_days": 20},
    }
    base.update(overrides)
    return base


def errors_of(**overrides) -> list[str]:
    return validate_spec(StrategySpec.model_validate(spec_dict(**overrides)), HORIZONS)


class TestSchemaStrictness:
    def test_a_valid_minimal_spec_parses_and_validates(self):
        assert errors_of() == []

    def test_unknown_top_level_key_is_rejected_not_ignored(self):
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(spec_dict(surprise="x"))

    def test_unknown_key_inside_a_condition_is_rejected(self):
        bad = {"left": 1, "op": ">", "right": 2, "exec": "os.system('x')"}
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(spec_dict(entry=bad))

    def test_unknown_operator_is_rejected(self):
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(spec_dict(
                entry={"left": {"ind": "close"}, "op": "matches", "right": 1}))

    def test_bad_slug_is_rejected(self):
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(spec_dict(slug="Has Spaces!"))

    def test_json_schema_can_be_exported(self):
        schema = StrategySpec.model_json_schema()
        assert schema["additionalProperties"] is False
        assert "$defs" in schema


class TestSemanticValidation:
    def test_unknown_indicator_is_named_in_the_error(self):
        errs = errors_of(entry={"left": {"ind": "magic_oscillator"}, "op": ">", "right": 1})
        assert any("unknown indicator 'magic_oscillator'" in e for e in errs)

    def test_illegal_period_lists_the_allowed_ones(self):
        errs = errors_of(entry={"left": {"ind": "sma", "period": 7}, "op": ">",
                                "right": {"ind": "close"}})
        assert any("sma needs period in [20, 50, 100, 200]" in e for e in errs)

    def test_period_on_an_indicator_that_takes_none(self):
        errs = errors_of(entry={"left": {"ind": "gap_pct", "period": 5}, "op": ">", "right": 1})
        assert any("takes no period" in e for e in errs)

    def test_price_compared_with_a_bare_number_is_rejected(self):
        """close > 500 would mean different things depending on when corporate actions
        were applied -- the whole reason close_raw exists."""
        errs = errors_of(entry={"left": {"ind": "close"}, "op": ">", "right": 500})
        assert any("back-adjusted price" in e and "close_raw" in e for e in errs)

    def test_close_raw_against_a_number_is_fine(self):
        assert errors_of(entry={"left": {"ind": "close_raw"}, "op": ">", "right": 500}) == []

    def test_price_against_a_multiple_of_another_price_is_fine(self):
        entry = {"left": {"ind": "close"}, "op": "<=",
                 "right": {"mul": [1.03, {"ind": "low_prior", "period": 60}]}}
        assert errors_of(entry=entry) == []

    def test_undefined_parameter_reference(self):
        errs = errors_of(entry={"left": {"ind": "rsi", "period": 14}, "op": "<",
                                "right": {"param": "nope"}})
        assert any("parameter 'nope' is not defined" in e for e in errs)

    def test_crosses_needs_plain_operands(self):
        entry = {"left": {"mul": [2, {"ind": "close"}]}, "op": "crosses_above",
                 "right": {"ind": "sma", "period": 20}}
        assert any("crosses_above operands" in e for e in errors_of(entry=entry))

    def test_between_needs_a_pair_and_only_between_takes_one(self):
        assert any("needs a [lo, hi] pair" in e for e in errors_of(
            entry={"left": {"ind": "rsi", "period": 14}, "op": "between", "right": 5}))
        assert any("only 'between' takes a pair" in e for e in errors_of(
            entry={"left": {"ind": "rsi", "period": 14}, "op": "<", "right": [1, 2]}))

    def test_too_many_conditions(self):
        leaf = {"left": {"ind": "rsi", "period": 14}, "op": "<", "right": 30}
        assert any("exceeds the limit" in e for e in errors_of(entry={"all": [leaf] * 13}))

    def test_nesting_too_deep(self):
        leaf = {"left": {"ind": "rsi", "period": 14}, "op": "<", "right": 30}
        deep = {"all": [{"any": [{"all": [{"any": [leaf]}]}]}]}
        assert any("nested deeper" in e for e in errors_of(entry=deep))

    def test_hold_days_must_sit_inside_the_horizon_window(self):
        errs = errors_of(horizon="short_term",
                         exit={"stop": {"type": "pct", "value": 0.1}, "max_hold_days": 40})
        assert any("outside the short_term window" in e for e in errs)

    def test_stop_needs_a_positive_size(self):
        errs = errors_of(exit={"stop": {"type": "atr"}, "max_hold_days": 20})
        assert any("needs a positive mult" in e for e in errs)

    def test_param_grid_explosion(self):
        params = {f"p{i}": {"default": 1, "grid": [1, 2, 3]} for i in range(3)}  # 27 combos
        assert any("grid combinations" in e for e in errors_of(params=params))

    def test_all_problems_are_reported_at_once(self):
        errs = errors_of(
            entry={"all": [{"left": {"ind": "nope"}, "op": ">", "right": 1},
                           {"left": {"ind": "close"}, "op": ">", "right": 5}]},
            exit={"stop": {"type": "atr"}, "max_hold_days": 999})
        assert len(errs) >= 3

    def test_param_combinations(self):
        spec = StrategySpec.model_validate(spec_dict(params={
            "a": {"default": 1, "grid": [1, 2]}, "b": {"default": 5, "grid": [5, 6]}}))
        assert len(param_combinations(spec)) == 4
        assert param_combinations(StrategySpec.model_validate(spec_dict())) == [{}]


def frame(**cols) -> pd.DataFrame:
    n = len(next(iter(cols.values())))
    df = pd.DataFrame(cols)
    df["symbol"] = [f"S{i}" for i in range(n)]
    df["date"] = pd.Timestamp("2024-06-03")
    return df


class TestInterpreter:
    def spec(self, entry, **kw) -> StrategySpec:
        return StrategySpec.model_validate(spec_dict(entry=entry, **kw))

    def test_comparison_and_between(self):
        f = frame(rsi14=[10.0, 45.0, 90.0])
        lt = self.spec({"left": {"ind": "rsi", "period": 14}, "op": "<", "right": 30})
        bt = self.spec({"left": {"ind": "rsi", "period": 14}, "op": "between", "right": [40, 60]})
        assert entry_mask(lt, f).tolist() == [True, False, False]
        assert entry_mask(bt, f).tolist() == [False, True, False]

    def test_null_never_satisfies_any_comparison(self):
        """No delivery data / no benchmark / no ROCE must read as 'condition false'."""
        f = frame(rsi14=[np.nan, 20.0])
        for op in ("<", "<=", ">", ">="):
            spec = self.spec({"left": {"ind": "rsi", "period": 14}, "op": op, "right": 50})
            assert not entry_mask(spec, f).iloc[0]
        bt = self.spec({"left": {"ind": "rsi", "period": 14}, "op": "between", "right": [0, 100]})
        assert entry_mask(bt, f).tolist() == [False, True]

    def test_not_of_null_is_still_false_for_the_underlying_condition(self):
        f = frame(rsi14=[np.nan])
        spec = self.spec({"not": {"left": {"ind": "rsi", "period": 14}, "op": "<", "right": 30}})
        # NOT(false) is true: 'not oversold' is honestly true of an unknown RSI. Documented.
        assert entry_mask(spec, f).tolist() == [True]

    def test_all_any_not(self):
        f = frame(rsi14=[10.0, 50.0, 90.0], ret5=[0.1, 0.1, -0.1])
        low = {"left": {"ind": "rsi", "period": 14}, "op": "<", "right": 60}
        up = {"left": {"ind": "ret", "period": 5}, "op": ">", "right": 0}
        assert entry_mask(self.spec({"all": [low, up]}), f).tolist() == [True, True, False]
        assert entry_mask(self.spec({"any": [low, up]}), f).tolist() == [True, True, False]
        assert entry_mask(self.spec({"all": [{"not": low}, up]}), f).tolist() == [
            False, False, False]

    def test_arithmetic_and_params(self):
        f = frame(close=[100.0, 100.0], ema20=[100.0, 90.0])  # 100<=101 yes; 100<=90.9 no
        spec = self.spec(
            {"left": {"ind": "close"}, "op": "<=",
             "right": {"mul": [{"param": "k"}, {"ind": "ema", "period": 20}]}},
            params={"k": {"default": 1.01}})
        assert entry_mask(spec, f).tolist() == [True, False]
        assert entry_mask(spec, f, {"k": 1.2}).tolist() == [True, True]

    def test_division_by_zero_is_missing_not_infinite(self):
        f = frame(close=[100.0], ema20=[0.0])
        spec = self.spec({"left": {"div": [{"ind": "close"}, {"ind": "ema", "period": 20}]},
                          "op": ">", "right": 1})
        assert entry_mask(spec, f).tolist() == [False]

    def test_crosses_above_uses_yesterday(self):
        f = frame(rsi14=[45.0, 45.0, 35.0])
        f["rsi14__prev"] = [35.0, 50.0, 35.0]
        spec = self.spec({"left": {"ind": "rsi", "period": 14}, "op": "crosses_above", "right": 40})
        assert entry_mask(spec, f).tolist() == [True, False, False]  # already-above is not a cross

    def test_universe_filters(self):
        f = frame(close_raw=[10.0, 100.0], turnover_med20=[1e6, 1e9], bar_count=[500, 500])
        spec = self.spec({"left": {"ind": "bar_count"}, "op": ">", "right": 0},
                         universe={"min_price_raw": 50, "min_median_turnover_inr": 1e7})
        assert entry_mask(spec, f).tolist() == [False, True]

    def test_scores_are_percentile_ranks_and_respect_direction(self):
        spec = StrategySpec.model_validate(spec_dict(rank={"by": [{"ind": "rsi", "period": 14,
                                                                   "dir": "asc"}]}))
        s = scores(spec, frame(rsi14=[10.0, 50.0, 90.0]))
        assert s.iloc[0] > s.iloc[1] > s.iloc[2]  # asc: lowest RSI ranks best

    def test_a_lone_candidate_still_scores(self):
        spec = StrategySpec.model_validate(spec_dict(rank={"by": [{"ind": "rsi", "period": 14}]}))
        assert scores(spec, frame(rsi14=[42.0])).iloc[0] == pytest.approx(1.0)

    def test_prev_columns_are_a_strictly_past_shift(self):
        f = frame(rsi14=[1.0, 2.0, 3.0])
        f["symbol"] = "A"
        f["date"] = pd.bdate_range("2024-01-01", periods=3)
        out = add_prev_columns(f, {"rsi14"})
        assert np.isnan(out["rsi14__prev"].iloc[0])
        assert out["rsi14__prev"].tolist()[1:] == [1.0, 2.0]

    def test_explain_is_readable(self):
        spec = StrategySpec.model_validate(spec_dict())
        lines = explain(spec)
        assert lines[0] == "rsi14 < 30"
        assert any("Stop: 10.0% from entry" in x for x in lines)
        assert lines[-1] == "Time exit: 20 trading days"


class TestSeeds:
    def test_there_are_ten_seed_strategies(self):
        assert len(SEEDS) == 10

    @pytest.mark.parametrize("path", SEEDS, ids=lambda p: p.stem)
    def test_seed_parses_validates_and_explains(self, path):
        spec = StrategySpec.model_validate_json(path.read_text())
        assert spec.slug == path.stem
        assert validate_spec(spec, HORIZONS) == []
        assert explain(spec)

    def test_seeds_cover_every_horizon(self):
        horizons = {json.loads(p.read_text())["horizon"] for p in SEEDS}
        assert horizons == {"short_term", "swing", "momentum", "long_term"}

    def test_slugs_are_unique(self):
        slugs = [json.loads(p.read_text())["slug"] for p in SEEDS]
        assert len(slugs) == len(set(slugs))


class TestCatalogueMatchesIndicators:
    """The catalogue is a promise about which columns exist. Break it and a spec that
    validates would evaluate against a missing column (silently all-False)."""

    def test_every_non_fundamental_catalogue_column_is_actually_computed(self):
        rng = np.random.default_rng(1)
        rows = []
        for sym in ("AAA", "BBB"):
            close = 100 * np.cumprod(1 + rng.normal(0, 0.01, 300))
            for d, c in zip(pd.bdate_range("2022-01-03", periods=300), close, strict=True):
                rows.append(dict(date=d, symbol=sym, open=c, high=c * 1.01, low=c * 0.99, close=c,
                                 volume=1000, turnover=c * 1000, delivery_pct=40.0))
        days = pd.bdate_range("2022-01-03", periods=300)
        idx = pd.Series(np.linspace(1000, 1200, 300), index=days)
        out = compute_indicators(pd.DataFrame(rows), idx)
        fundamentals = {
            e.column(p) for e in CATALOGUE.values() if e.kind.value == "fund"
            for p in (e.periods or (None,))
        }
        missing = (all_columns() - fundamentals) - set(out.columns)
        assert not missing, f"catalogue promises columns the indicators do not compute: {missing}"
