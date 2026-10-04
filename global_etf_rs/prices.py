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


def extract_close(frame, field="Close"):
    if frame is None or frame.empty:
        raise ValueError("Yahoo 未提供行情")
    if not isinstance(frame.columns, pd.MultiIndex):
        raise ValueError("行情欄位未包含 ETF 代碼")
    for level in range(frame.columns.nlevels):
        if field in frame.columns.get_level_values(level):
            result = frame.xs(field, axis=1, level=level).copy()
            result.index = pd.to_datetime(result.index).tz_localize(None).normalize()
            return result.sort_index()
    raise ValueError("行情缺少調整後 Close 欄位")


def download_prices(tickers, session, with_market_data=False):
    session = pd.Timestamp(session)
    fields = ['Adj Close', 'Volume', 'Close'] if with_market_data else ['Close']
    collections = {field: [] for field in fields}

    def download(batch):
        return yf.download(
            batch, start=(session - timedelta(days=730)).date().isoformat(),
            end=(session + timedelta(days=1)).date().isoformat(),
            auto_adjust=not with_market_data, interval="1d", group_by="column",
            threads=False, progress=False, timeout=20)

    for offset in range(0, len(tickers), 25):
        raw = download(tickers[offset:offset + 25])
        if raw is not None and not raw.empty:
            for field in fields:
                try:
                    collections[field].append(extract_close(raw, field))
                except ValueError:
                    if field == fields[0]:
                        raise
    if not collections[fields[0]]:
        raise ValueError("所有行情批次下載失敗")
    frames = {field: pd.concat(parts, axis=1) if parts else pd.DataFrame()
              for field, parts in collections.items()}
    for ticker in tickers:
        prices = frames[fields[0]]
        if ticker not in prices or prices[ticker].isna().any():
            raw = download([ticker])
            if raw is None or raw.empty:
                continue
            for field in fields:
                try:
                    recovered = extract_close(raw, field)
                except ValueError:
                    continue
                if ticker in recovered:
                    frame = frames[field].reindex(frames[field].index.union(recovered.index)).sort_index()
                    values = recovered[ticker].reindex(frame.index)
                    frame[ticker] = values.combine_first(frame[ticker]) if ticker in frame else values
                    frames[field] = frame
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(session - timedelta(days=730), session).tz_localize(None)
    frames = {field: frame.reindex(sessions) for field, frame in frames.items()}
    if with_market_data:
        return frames['Adj Close'], frames['Volume'], frames['Close']
    return frames['Close']
