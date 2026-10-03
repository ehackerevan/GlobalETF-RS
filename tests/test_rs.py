import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from global_etf_rs.calculator import calculate
from global_etf_rs.universe import load_universe


@pytest.fixture
def sample():
    dates = xcals.get_calendar("XNYS").sessions_in_range(
        xcals.get_calendar("XNYS").session_offset("2026-09-30", -252), "2026-09-30")
    prices = pd.DataFrame({"SPY": 100 * 1.001 ** np.arange(253),
                           "MTUM": 100 * 1.002 ** np.arange(253),
                           "DBA": 100 * 0.999 ** np.arange(253),
                           "CORN": 100 * 0.999 ** np.arange(253)}, index=dates)
    universe = load_universe()
    universe = universe[universe.ticker.isin(prices.columns)]
    return prices, universe, dates[-1]


def test_relative_formula_and_separate_ranks(sample):
    prices, universe, date = sample
    result, excluded = calculate(prices, universe, date)
    rows = result.set_index("ticker")
    assert excluded.empty
    expected = sum(w * ((1.002 / 1.001) ** n - 1) for n, w in zip([63, 126, 189, 252], [.4, .2, .2, .2])) * 100
    assert rows.loc["MTUM", "rs_score"] == pytest.approx(expected)
    assert rows.loc["SPY", "rs_score"] == pytest.approx(0)
    assert pd.isna(rows.loc["SPY", "rs_rank"])
    assert rows.loc["MTUM", "rs_rank"] == 99
    assert rows.loc["DBA", "rs_rank"] == rows.loc["CORN", "rs_rank"]
    assert rows.loc["DBA", "rs_score"] < 0
    assert rows.loc["DBA", "category_rank"] == 75


@pytest.mark.parametrize("location", [0, 100, 252])
def test_missing_spy_stops_report(sample, location):
    prices, universe, date = sample
    prices.iloc[location, prices.columns.get_loc("SPY")] = np.nan
    with pytest.raises(ValueError, match="SPY"):
        calculate(prices, universe, date)


@pytest.mark.parametrize("value", [0, -1, np.inf])
def test_invalid_benchmark(sample, value):
    prices, universe, date = sample
    prices.loc[date, "SPY"] = value
    with pytest.raises(ValueError, match="SPY"):
        calculate(prices, universe, date)


def test_etf_missing_latest_excluded_not_forward_filled(sample):
    prices, universe, date = sample
    prices.loc[date, "MTUM"] = np.nan
    result, excluded = calculate(prices, universe, date)
    assert "MTUM" not in set(result.ticker)
    assert excluded.iloc[0].reason == "最新收盤缺失或無效"


def test_etf_sparse_history_is_excluded(sample):
    prices, universe, date = sample
    prices.loc[prices.index[10], "DBA"] = np.nan
    result, excluded = calculate(prices, universe, date)
    assert "DBA" not in set(result.ticker)
    assert "歷史不足" in excluded.iloc[0].reason


def test_future_and_extra_weekend_do_not_change_scores(sample):
    prices, universe, date = sample
    baseline, _ = calculate(prices, universe, date)
    prices.loc[date + pd.Timedelta(days=1)] = 1e9
    prices.loc[pd.Timestamp("2026-09-27")] = 1e8
    result, _ = calculate(prices, universe, date)
    pd.testing.assert_frame_equal(result, baseline)


def test_duplicate_dates_rejected(sample):
    prices, universe, date = sample
    with pytest.raises(ValueError, match="重複"):
        calculate(pd.concat([prices, prices.tail(1)]), universe, date)


def test_universe_covers_agriculture_and_other_assets():
    universe = load_universe()
    assert set(universe[universe.category.eq("農產品")].ticker) == {"DBA", "CORN", "WEAT", "SOYB", "CANE"}
    assert {"各國股市", "債券", "投資風格", "市值規模", "大宗商品"} <= set(universe.category)
