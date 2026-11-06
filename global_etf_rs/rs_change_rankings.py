"""短期相對強度分數變化排行，只比較實際保存的快照。"""
import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .history import METHOD_ID

WINDOWS = (1, 3, 5, 10)


def build_rs_change_rankings(result, history, top_n=5):
    """Return largest positive and negative score changes versus exact prior sessions."""
    end = pd.Timestamp(result.data_date.iloc[0]).normalize()
    calendar = xcals.get_calendar('XNYS')
    current = result[result.ticker.ne('SPY')][['ticker', 'name', 'category', 'rs_score']].copy()
    current['rs_score'] = pd.to_numeric(current.rs_score, errors='coerce')
    rankings = {}
    for window in WINDOWS:
        prior_date = calendar.session_offset(end, -window).date().isoformat()
        prior = pd.DataFrame()
        if history is not None and not history.empty:
            prior = history[(history.data_date.eq(prior_date)) &
                            history.snapshot_kind.eq('observed') &
                            history.method_id.eq(METHOD_ID)][['ticker', 'rs_score']].copy()
        if prior.empty:
            rankings[str(window)] = {
                'compare_date': prior_date, 'available': False,
                'gainers': [], 'decliners': [], 'compared_count': 0,
            }
            continue
        prior['rs_score'] = pd.to_numeric(prior.rs_score, errors='coerce')
        changes = current.merge(prior, on='ticker', how='inner', suffixes=('', '_prior'))
        changes['change'] = changes.rs_score - changes.rs_score_prior
        changes = changes[np.isfinite(changes.change)]
        gainers = changes[changes.change.gt(0)].sort_values(
            ['change', 'ticker'], ascending=[False, True]).head(top_n)
        decliners = changes[changes.change.lt(0)].sort_values(
            ['change', 'ticker'], ascending=[True, True]).head(top_n)

        def records(frame):
            return [{'ticker': row.ticker, 'name': row.name, 'category': row.category,
                     'change': float(row.change)} for row in frame.itertuples()]

        rankings[str(window)] = {
            'compare_date': prior_date, 'available': True,
            'gainers': records(gainers), 'decliners': records(decliners),
            'compared_count': int(len(changes)),
        }
    return rankings
