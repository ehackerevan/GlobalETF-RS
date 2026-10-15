"""取得已完成的美股交易日與 Yahoo 配息／拆分調整行情。"""
from datetime import timedelta
import math
import logging

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


def _closing_quote(ticker, session, low, high):
    """僅接受同交易日收盤／收盤競價時間的美元一般行情，不採盤中末筆。"""
    calendar = xcals.get_calendar("XNYS")
    close = calendar.session_close(session)
    if pd.Timestamp.now(tz="UTC") < close + pd.Timedelta(hours=1):
        return None
    if not all(math.isfinite(float(value)) and float(value) > 0 for value in [low, high]) or low > high:
        return None
    try:
        metadata = yf.Ticker(ticker).get_history_metadata()
        price = float(metadata['regularMarketPrice'])
        stamp = pd.Timestamp(metadata['regularMarketTime'], unit='s', tz='UTC')
        period_end = pd.Timestamp(metadata['currentTradingPeriod']['regular']['end'], unit='s', tz='UTC')
        if (metadata.get('currency') != 'USD' or period_end != close
                or not close <= stamp <= close + pd.Timedelta(minutes=5)
                or not math.isfinite(price) or price <= 0
                or not low - 0.011 <= price <= high + 0.011):
            return None
        return price, stamp.isoformat()
    except Exception as exc:
        logging.warning("%s 收盤行情補查失敗（%s），維持缺值", ticker, type(exc).__name__)
        return None


def download_prices(tickers, session, with_market_data=False, recovery_log=None):
    session = pd.Timestamp(session)
    fields = ['Adj Close', 'Volume', 'Close', 'Low', 'High'] if with_market_data else ['Close']
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
        for ticker in tickers:
            # 只補最新一日同時缺少調整／未調整收盤，過去缺日絕不推估。
            if (ticker not in frames['Adj Close'] or ticker not in frames['Close']
                    or not pd.isna(frames['Adj Close'].at[session, ticker])
                    or not pd.isna(frames['Close'].at[session, ticker])):
                continue
            low = frames['Low'].at[session, ticker] if ticker in frames['Low'] else float('nan')
            high = frames['High'].at[session, ticker] if ticker in frames['High'] else float('nan')
            quote = _closing_quote(ticker, session, low, high)
            if quote is None:
                continue
            price, stamp = quote
            # 當前最後收盤日尚無後續配息／拆分，當日調整價等於未調整價。
            frames['Adj Close'].at[session, ticker] = price
            frames['Close'].at[session, ticker] = price
            record = {'ticker': ticker, 'data_date': session.date().isoformat(),
                      'source': 'Yahoo regularMarketPrice at closing session',
                      'quote_time_utc': stamp, 'close': price,
                      'adjusted_close': price, 'adjustment_basis': 'latest session, factor 1'}
            if recovery_log is not None:
                recovery_log.append(record)
            logging.warning("%s %s：日線收盤缺值，採同日收盤時間一般行情 %s（%s）", ticker, session.date(), price, stamp)
        return frames['Adj Close'], frames['Volume'], frames['Close']
    return frames['Close']
