import exchange_calendars as xcals
import pandas as pd

from global_etf_rs.history import METHOD_ID
from global_etf_rs.rs_change_rankings import build_rs_change_rankings


def test_short_term_rankings_use_exact_observed_snapshots_and_limit_to_five():
    end = pd.Timestamp('2026-09-30')
    calendar = xcals.get_calendar('XNYS')
    tickers = [f'T{i:02d}' for i in range(12)]
    result = pd.DataFrame({
        'data_date': [end.date().isoformat()] * len(tickers),
        'ticker': tickers, 'name': [f'ETF {ticker}' for ticker in tickers],
        'category': ['測試'] * len(tickers), 'rs_score': [0.] * len(tickers),
    })
    changes = {ticker: (i + 1 if i < 6 else -(i - 5)) for i, ticker in enumerate(tickers)}
    records = []
    for window in (1, 3, 5, 10):
        prior_date = calendar.session_offset(end, -window).date().isoformat()
        kind = 'reconstructed' if window == 3 else 'observed'
        for ticker in tickers:
            records.append({'data_date': prior_date, 'ticker': ticker,
                            'rs_score': -changes[ticker], 'method_id': METHOD_ID,
                            'snapshot_kind': kind})
    rankings = build_rs_change_rankings(result, pd.DataFrame(records))

    assert rankings['1']['gainers'][0]['ticker'] == 'T05'
    assert [row['ticker'] for row in rankings['1']['gainers']] == [
        'T05', 'T04', 'T03', 'T02', 'T01']
    assert [row['ticker'] for row in rankings['1']['decliners']] == [
        'T11', 'T10', 'T09', 'T08', 'T07']
    assert len(rankings['1']['gainers']) == len(rankings['1']['decliners']) == 5
    assert rankings['3']['available'] is False
    assert rankings['5']['available'] is True


def test_short_term_rankings_are_unavailable_without_matching_snapshot():
    result = pd.DataFrame({'data_date': ['2026-09-30'], 'ticker': ['T01'],
                           'name': ['ETF 1'], 'category': ['測試'], 'rs_score': [1.]})
    rankings = build_rs_change_rankings(result, pd.DataFrame())
    assert all(not ranking['available'] for ranking in rankings.values())
