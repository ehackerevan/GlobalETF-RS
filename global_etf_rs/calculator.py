"""以同日美元調整價格計算相對 SPY 的加權強度。"""
import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .universe import BENCHMARK

WINDOWS = (63, 126, 189, 252)
WEIGHTS = (0.4, 0.2, 0.2, 0.2)


def calculate(prices, universe, expected_session):
    """回傳合格排名及排除清單；缺價不前向填補，SPY 不參與 PR。"""
    if prices.empty or not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("價格資料必須有日期索引且不得為空")
    if prices.index.has_duplicates or prices.columns.has_duplicates:
        raise ValueError("價格日期或代碼重複")
    prices = prices.sort_index().copy()
    prices.index = prices.index.tz_localize(None).normalize()
    if prices.index.has_duplicates:
        raise ValueError("價格日期正規化後重複")
    expected = pd.Timestamp(expected_session).tz_localize(None).normalize()
    prices = prices.loc[:expected]
    if BENCHMARK not in prices or expected not in prices.index:
        raise ValueError("缺少 SPY 或預期最新收盤日，拒絕產出排名")
    calendar = xcals.get_calendar("XNYS")
    if not calendar.is_session(expected):
        raise ValueError("指定日期不是美股交易日")
    sessions = calendar.sessions_in_range(calendar.session_offset(expected, -252), expected).tz_localize(None)
    prices = prices.reindex(sessions)
    benchmark = pd.to_numeric(prices[BENCHMARK], errors="coerce")
    if benchmark.isna().any():
        raise ValueError("SPY 歷史不足 253 個交易日或期間缺價")
    if not np.isfinite(benchmark).all() or (benchmark <= 0).any():
        raise ValueError("SPY 包含無效價格")
    rows, excluded = [], []
    for item in universe.to_dict("records"):
        ticker = item["ticker"]
        if ticker not in prices:
            excluded.append({**item, "reason": "下載未提供行情"})
            continue
        close = pd.to_numeric(prices[ticker], errors="coerce")
        reason = None
        if not np.isfinite(close.iloc[-1]) or close.iloc[-1] <= 0:
            reason = "最新收盤缺失或無效"
        elif close.isna().any():
            reason = "253 個交易日歷史不足或期間缺價"
        elif not np.isfinite(close).all() or (close <= 0).any():
            reason = "價格包含非正數或無限值"
        if reason:
            excluded.append({**item, "reason": reason})
            continue
        row = {**item, "data_date": expected.date().isoformat(), "adjusted_close": close.iloc[-1]}
        relative_returns = []
        for window in WINDOWS:
            total_return = close.iloc[-1] / close.iloc[-window - 1] - 1
            spy_return = benchmark.iloc[-1] / benchmark.iloc[-window - 1] - 1
            relative = (1 + total_return) / (1 + spy_return) - 1
            row[f"return_{window}d_pct"] = total_return * 100
            row[f"relative_{window}d_pct"] = relative * 100
            relative_returns.append(relative)
        row["rs_score"] = float(np.dot(relative_returns, WEIGHTS) * 100)
        row["outperforms_spy"] = row["rs_score"] > 0
        row["rs_line_1y"] = 100 * (1 + relative_returns[-1])
        rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("沒有可計算的標的")
    ranked = result["ticker"].ne(BENCHMARK)
    result["rs_rank"] = np.nan
    result["category_rank"] = np.nan
    result.loc[ranked, "rs_rank"] = np.ceil(result.loc[ranked, "rs_score"].rank(pct=True) * 99).clip(1, 99)
    result.loc[ranked, "category_rank"] = np.ceil(
        result.loc[ranked].groupby("category")["rs_score"].rank(pct=True) * 99
    ).clip(1, 99)
    for column in ["rs_rank", "category_rank"]:
        result[column] = result[column].astype("Int64")
    result = result.sort_values(["rs_score", "ticker"], ascending=[False, True]).reset_index(drop=True)
    exclusions = pd.DataFrame(excluded, columns=list(universe.columns) + ["reason"])
    return result, exclusions
