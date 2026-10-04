"""交易觀察指標與資料發布門檻；不產生買賣指令。"""
import numpy as np
import pandas as pd

MIN_OVERALL_COVERAGE = 0.90
MIN_CATEGORY_COVERAGE = 0.70
MIN_DOLLAR_VOLUME = 1_000_000


def coverage_summary(universe, result):
    expected = universe[universe.ticker.ne('SPY')]
    available = set(result.ticker) - {'SPY'}
    categories = []
    for category, group in expected.groupby('category'):
        count = len(set(group.ticker) & available)
        categories.append({'category': category, 'expected': len(group), 'eligible': count,
                           'coverage_pct': 100 * count / len(group)})
    overall = len(available) / len(expected) if len(expected) else 0
    passed = overall >= MIN_OVERALL_COVERAGE and all(
        row['coverage_pct'] >= 100 * MIN_CATEGORY_COVERAGE for row in categories)
    return {'expected_count': len(expected), 'eligible_count': len(available),
            'coverage_pct': 100 * overall, 'publishable': passed,
            'status': '完整' if overall == 1 else '部分資料',
            'minimum_overall_pct': 100 * MIN_OVERALL_COVERAGE,
            'minimum_category_pct': 100 * MIN_CATEGORY_COVERAGE, 'categories': categories}


def enrich_assessment(result, prices, volumes=None, raw_prices=None):
    result = result.copy()
    end = pd.Timestamp(result.data_date.iloc[0])
    import exchange_calendars as xcals
    calendar = xcals.get_calendar('XNYS')
    sessions = calendar.sessions_in_range(calendar.session_offset(end, -252), end).tz_localize(None)

    def align(frame):
        if frame is None:
            return None
        frame = frame.copy()
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        if frame.index.has_duplicates or frame.columns.has_duplicates:
            raise ValueError('評估資料日期或代碼重複')
        return frame.reindex(sessions).apply(pd.to_numeric, errors="coerce")

    prices, volumes, raw_prices = align(prices), align(volumes), align(raw_prices)
    values = []
    for row in result.to_dict('records'):
        ticker = row['ticker']
        close = prices[ticker]
        returns = close.pct_change(fill_method=None).dropna()
        volatility = returns.std(ddof=1) * np.sqrt(252) * 100
        downside = np.sqrt(np.mean(np.minimum(returns.to_numpy(), 0) ** 2)) * np.sqrt(252) * 100
        drawdowns = (close / close.cummax() - 1) * 100
        ma50, ma200 = close.tail(50).mean(), close.tail(200).mean()
        absolute = sum(weight * row[f'return_{window}d_pct'] for window, weight in
                       [(63, .4), (126, .2), (189, .2), (252, .2)])
        relative_strong, absolute_up = row['rs_score'] > 0, absolute > 0
        state = ('相對強・絕對上漲' if absolute_up else '相對強・絕對非上漲') if relative_strong else (
            '相對非強・絕對上漲' if absolute_up else '相對非強・絕對非上漲')
        if ticker == 'SPY':
            state = '基準'
        turnover = np.nan
        if volumes is not None and raw_prices is not None and ticker in volumes and ticker in raw_prices:
            volume = pd.to_numeric(volumes[ticker].tail(20), errors='coerce')
            raw = pd.to_numeric(raw_prices[ticker].tail(20), errors='coerce')
            if np.isfinite(volume).all() and np.isfinite(raw).all() and (volume >= 0).all() and (raw > 0).all():
                turnover = float((volume * raw).mean())
        liquidity = '未知' if not np.isfinite(turnover) else ('低成交額' if turnover < MIN_DOLLAR_VOLUME else '成交額達門檻')
        values.append({
            'absolute_momentum_pct': absolute, 'trade_state': state,
            'above_ma50': close.iloc[-1] > ma50, 'above_ma200': close.iloc[-1] > ma200,
            'ma50_gap_pct': (close.iloc[-1] / ma50 - 1) * 100,
            'ma200_gap_pct': (close.iloc[-1] / ma200 - 1) * 100,
            'volatility_1y_pct': volatility, 'downside_risk_1y_pct': downside,
            'max_drawdown_1y_pct': drawdowns.min(), 'current_drawdown_1y_pct': drawdowns.iloc[-1],
            'avg_dollar_volume_20d': turnover, 'liquidity_status': liquidity,
            'data_completeness_pct': 100 * close.notna().sum() / 253,
        })
    return pd.concat([result.reset_index(drop=True), pd.DataFrame(values)], axis=1)
