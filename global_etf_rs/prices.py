"""取得已完成的美股交易日與 Yahoo 配息／拆分調整行情。"""
from datetime import timedelta

import exchange_calendars as xcals
import pandas as pd
import yfinance as yf


def latest_closed_session(now=None):
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range((now - pd.Timedelta(days=14)).date(), now.date())
    # 收盤後留 1 小時供行情供應商更新；盤中與半日交易使用交易所日曆。
    closed = [session for session in sessions if calendar.session_close(session) + pd.Timedelta(hours=1) <= now]
    if not closed:
        raise ValueError("無法找出已完成的美股交易日")
    return pd.Timestamp(closed[-1]).tz_localize(None).normalize()


def extract_close(frame):
    if frame is None or frame.empty:
        raise ValueError("Yahoo 未提供行情")
    if not isinstance(frame.columns, pd.MultiIndex):
        raise ValueError("行情欄位未包含 ETF 代碼")
    for level in range(frame.columns.nlevels):
        if "Close" in frame.columns.get_level_values(level):
            result = frame.xs("Close", axis=1, level=level).copy()
            result.index = pd.to_datetime(result.index).tz_localize(None).normalize()
            return result.sort_index()
    raise ValueError("行情缺少調整後 Close 欄位")


def download_prices(tickers, session):
    session = pd.Timestamp(session)
    # 每次重抓完整調整歷史，避免配息後把新舊調整基準拼接。
    frames = []
    for offset in range(0, len(tickers), 25):
        batch = tickers[offset:offset + 25]
        raw = yf.download(
            batch, start=(session - timedelta(days=730)).date().isoformat(),
            end=(session + timedelta(days=1)).date().isoformat(),
            auto_adjust=True, interval="1d", group_by="column", threads=False,
            progress=False, timeout=20,
        )
        if raw is not None and not raw.empty:
            frames.append(extract_close(raw))
    if not frames:
        raise ValueError("所有行情批次下載失敗")
    result = pd.concat(frames, axis=1)
    # 單次來源失敗不代表 ETF 下市，不永久剔除標的。
    for ticker in tickers:
        if ticker not in result or result[ticker].isna().any():
            raw = yf.download(
                [ticker], start=(session - timedelta(days=730)).date().isoformat(),
                end=(session + timedelta(days=1)).date().isoformat(), auto_adjust=True,
                interval="1d", group_by="column", threads=False, progress=False, timeout=20,
            )
            if raw is not None and not raw.empty:
                recovered = extract_close(raw)
                if ticker in recovered:
                    result = result.reindex(result.index.union(recovered.index)).sort_index()
                    if ticker in result:
                        result[ticker] = recovered[ticker].reindex(result.index).combine_first(result[ticker])
                    else:
                        result[ticker] = recovered[ticker].reindex(result.index)
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(session - timedelta(days=730), session).tz_localize(None)
    return result.reindex(sessions)
