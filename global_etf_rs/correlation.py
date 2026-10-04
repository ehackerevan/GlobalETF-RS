"""使用同日調整收盤報酬估計相關性，不宣稱為持倉重疊。"""
import exchange_calendars as xcals
import numpy as np
import pandas as pd


def calculate_correlation(prices, result):
    end = pd.Timestamp(result.data_date.iloc[0])
    calendar = xcals.get_calendar('XNYS')
    sessions = calendar.sessions_in_range(calendar.session_offset(end, -63), end).tz_localize(None)
    frame = prices.copy()
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    if frame.index.has_duplicates or frame.columns.has_duplicates:
        raise ValueError('相關性資料日期或代碼重複')
    tickers = result.ticker.tolist()
    frame = frame.reindex(index=sessions, columns=tickers).apply(pd.to_numeric, errors='coerce')
    returns = frame.pct_change(fill_method=None).iloc[1:].replace([np.inf,-np.inf], np.nan)
    # 不補缺價；近乎常數報酬視為無法估計，避免浮點噪音被放大。
    stable = returns.std(ddof=1).gt(1e-10)
    valid_returns = returns.copy()
    valid_returns.loc[:, ~stable] = np.nan
    correlation = valid_returns.corr(min_periods=60)
    counts = returns.notna().astype(int).T.dot(returns.notna().astype(int))
    row_result = result.copy()
    row_result['correlation_spy_63d'] = row_result.ticker.map(correlation['SPY'])
    row_result['most_correlated_ticker'] = ''
    row_result['highest_peer_correlation_63d'] = np.nan
    row_result['peer_correlation_samples'] = np.nan
    for index, row in row_result[row_result.ticker.ne('SPY')].iterrows():
        peers = correlation.loc[row.ticker].drop(labels=[row.ticker,'SPY'], errors='ignore').dropna()
        if not peers.empty:
            peer = peers.idxmax()
            row_result.loc[index, 'most_correlated_ticker'] = peer
            row_result.loc[index, 'highest_peer_correlation_63d'] = peers.loc[peer]
            row_result.loc[index, 'peer_correlation_samples'] = counts.loc[row.ticker, peer]
    payload = {'tickers': tickers, 'matrix': correlation.replace({np.nan: None}).values.tolist(),
               'samples': counts.values.tolist(), 'window_sessions': 63, 'min_samples': 60,
               'start_date': sessions[1].date().isoformat(), 'end_date': end.date().isoformat()}
    return row_result, correlation, counts, payload
