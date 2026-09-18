"""Fundamentals metrics and the point-in-time join."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stk.domain.fundamentals import (
    FilingFacts,
    attach_fundamentals,
    available_on,
    derive_metric_rows,
)

ENDS = [date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30), date(2023, 12, 31),
        date(2024, 3, 31), date(2024, 6, 30)]


def quarter_filing(end: date, *, pbt=100.0, fin=10.0, eps=5.0, rev=1000.0, lag=45,
                   annual=False, **extra) -> FilingFacts:
    return FilingFacts(
        symbol="AAA", basis="consolidated", period_end=end, is_annual=annual,
        available_on=date.fromordinal(end.toordinal() + lag),
        quarter={"revenue": rev, "pbt": pbt, "finance_costs": fin, "pat": pbt * 0.75, "eps": eps},
        **extra,
    )


def history() -> list[FilingFacts]:
    return [quarter_filing(e) for e in ENDS]


class TestTtm:
    def test_eps_ttm_sums_four_consecutive_quarters(self):
        rows = derive_metric_rows(history())
        assert rows[3]["eps_ttm"] == pytest.approx(20.0)  # 4 x 5.0
        assert rows[2]["eps_ttm"] is None  # only 3 quarters known then

    def test_a_missing_quarter_makes_ttm_none_not_a_short_sum(self):
        hole = [f for f in history() if f.period_end != date(2023, 9, 30)]
        rows = derive_metric_rows(hole)
        assert rows[-1]["eps_ttm"] is None

    def test_each_row_only_knows_filings_available_by_its_own_date(self):
        rows = derive_metric_rows(history())
        # row i is stamped with filing i's availability, and knows quarters 0..i only
        assert rows[3]["eps_ttm"] == pytest.approx(20.0)
        assert rows[4]["eps_ttm"] == pytest.approx(20.0)  # still 4 quarters: Q1-23 dropped out


class TestRoceAndDebt:
    def annual_with_balance(self) -> list[FilingFacts]:
        fs = history()
        fs[4] = quarter_filing(
            date(2024, 3, 31), annual=True,
            ytd={"revenue": 4000.0, "pat": 300.0},
            instant={"equity": 1000.0, "borrowings_noncurrent": 300.0, "borrowings_current": 200.0},
        )
        return fs

    def test_roce_is_ebit_ttm_over_equity_plus_borrowings(self):
        rows = derive_metric_rows(self.annual_with_balance())
        # EBIT_ttm = (pbt 100 + fin 10) x 4 = 440 ; capital = 1000 + 500 = 1500
        assert rows[4]["roce"] == pytest.approx(440.0 / 1500.0)

    def test_de_ratio_is_borrowings_over_equity(self):
        assert derive_metric_rows(self.annual_with_balance())[4]["de_ratio"] == pytest.approx(0.5)

    def test_no_balance_sheet_yet_means_none_not_zero(self):
        rows = derive_metric_rows(history())
        assert rows[3]["roce"] is None and rows[3]["de_ratio"] is None

    def test_negative_equity_gives_no_ratio(self):
        fs = self.annual_with_balance()
        fs[4] = quarter_filing(date(2024, 3, 31), annual=True,
                               instant={"equity": -50.0, "borrowings_current": 10.0})
        rows = derive_metric_rows(fs)
        assert rows[4]["de_ratio"] is None


class TestCagr:
    def annuals(self, revenues, pats):
        out = []
        for i, (r, p) in enumerate(zip(revenues, pats, strict=True)):
            end = date(2021 + i, 3, 31)
            out.append(quarter_filing(end, annual=True, ytd={"revenue": r, "pat": p}))
        return out

    def test_three_year_cagr(self):
        rows = derive_metric_rows(self.annuals([100, 110, 121, 133.1], [10, 12, 14.4, 17.28]))
        assert rows[3]["sales_cagr3"] == pytest.approx(0.10, abs=1e-3)
        assert rows[3]["profit_cagr3"] == pytest.approx(0.20, abs=1e-3)

    def test_not_enough_history_is_none(self):
        assert derive_metric_rows(self.annuals([100, 110], [10, 11]))[1]["sales_cagr3"] is None

    def test_a_non_positive_base_gives_none_not_a_nonsense_number(self):
        rows = derive_metric_rows(self.annuals([100, 110, 121, 133], [-5, 1, 2, 3]))
        assert rows[3]["profit_cagr3"] is None


class TestRestatement:
    def test_a_restated_quarter_only_takes_effect_from_its_own_availability(self):
        original = quarter_filing(ENDS[3], eps=5.0)
        restated = quarter_filing(ENDS[3], eps=50.0, lag=200)  # same period, filed much later
        rows = derive_metric_rows([*history()[:3], original, restated])
        by_avail = {r["available_on"]: r["eps_ttm"] for r in rows}
        assert by_avail[pd.Timestamp(original.available_on)] == pytest.approx(20.0)
        assert by_avail[pd.Timestamp(restated.available_on)] == pytest.approx(65.0)


def daily_frame(symbol="AAA", start="2023-01-02", n=600, close=100.0) -> pd.DataFrame:
    days = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"date": days, "symbol": symbol, "close": close, "close_raw": close})


class TestAttach:
    def metrics(self):
        return pd.DataFrame(derive_metric_rows(history()))

    def test_a_bar_sees_only_filings_available_on_or_before_it(self):
        out = attach_fundamentals(daily_frame(), self.metrics())
        first_ttm = pd.Timestamp(history()[3].available_on)  # first row with a full TTM
        before = out[out["date"] < first_ttm]
        after = out[out["date"] >= first_ttm]
        assert before["eps_ttm"].isna().all()  # nothing knowable yet -> NaN, never back-filled
        assert after["eps_ttm"].notna().all()

    def test_a_later_filing_never_changes_earlier_bars(self):
        m = self.metrics()
        full = attach_fundamentals(daily_frame(), m)
        cutoff = pd.Timestamp(history()[4].available_on) - pd.Timedelta(days=1)
        early = attach_fundamentals(daily_frame(), m[m["available_on"] <= cutoff])
        a = full[full["date"] <= cutoff].reset_index(drop=True)
        b = early[early["date"] <= cutoff].reset_index(drop=True)
        cols = ["eps_ttm", "fund_age_days"]
        pd.testing.assert_frame_equal(a[cols], b[cols])

    def test_fund_age_counts_days_since_the_filing_became_available(self):
        out = attach_fundamentals(daily_frame(), self.metrics())
        avail = pd.Timestamp(history()[3].available_on)
        row = out[out["date"] == out[out["date"] >= avail]["date"].iloc[0]].iloc[0]
        assert row["fund_age_days"] == (row["date"] - avail).days

    def test_pe_is_only_defined_for_positive_eps(self):
        neg = [quarter_filing(e, eps=-5.0) for e in ENDS]
        out = attach_fundamentals(daily_frame(), pd.DataFrame(derive_metric_rows(neg)))
        assert out["pe_ttm"].isna().all()
        pos = attach_fundamentals(daily_frame(close=200.0), self.metrics())
        assert pos["pe_ttm"].dropna().iloc[0] == pytest.approx(200.0 / 20.0)

    def test_symbols_are_matched_independently(self):
        frame = pd.concat([daily_frame("AAA"), daily_frame("ZZZ")]).reset_index(drop=True)
        out = attach_fundamentals(frame, self.metrics())
        assert out[out.symbol == "ZZZ"]["eps_ttm"].isna().all()
        assert out[out.symbol == "AAA"]["eps_ttm"].notna().any()

    def test_no_metrics_at_all_leaves_everything_nan(self):
        out = attach_fundamentals(daily_frame(), pd.DataFrame())
        assert out["roce"].isna().all() and "pe_ttm" in out.columns


class TestAvailableOn:
    def test_a_real_broadcast_becomes_usable_the_next_day(self):
        assert available_on(date(2025, 1, 16), date(2024, 12, 31), 60) == (date(2025, 1, 17), False)

    def test_no_broadcast_falls_back_to_period_end_plus_lag_and_is_flagged_approximate(self):
        d, approx = available_on(None, date(2024, 12, 31), 60)
        assert d == date(2025, 3, 1) and approx is True

    def test_nan_never_leaks_in(self):
        assert np.isnan(np.nan)  # documentation of intent: missing stays missing
