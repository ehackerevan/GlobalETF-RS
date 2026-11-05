"""以實際保存的 RS 快照分組，檢視後續相對 SPY 報酬。"""
import numpy as np
import pandas as pd


HORIZONS = (5, 21, 63)
BUCKETS = ((0, 20, '最低 20%'), (20, 40, '20–40%'), (40, 60, '40–60%'),
           (60, 80, '60–80%'), (80, 101, '最高 20%'))


def summarize_forward_returns(history, prices):
    """Only observed snapshots with matching constituents and complete forward prices qualify."""
    columns = ['觀察期間', 'RS排名組別', '平均相對SPY報酬 %', '中位數相對SPY報酬 %',
               '跑贏SPY比例 %', '樣本數', '快照日數']
    if history is None or history.empty or prices is None or prices.empty:
        return pd.DataFrame(columns=columns), {'observed_snapshot_dates': 0, 'evaluated_snapshot_dates': 0}

    close = prices.copy().sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.apply(pd.to_numeric, errors='coerce')
    close = close.loc[~close.index.duplicated(keep='last')]
    session_pos = {day.strftime('%Y-%m-%d'): i for i, day in enumerate(close.index)}
    observed = history[history.snapshot_kind.eq('observed')]
    observations = []
    evaluated_dates = set()
    for date, group in observed.groupby('data_date'):
        if date not in session_pos or 'SPY' not in close:
            continue
        start = session_pos[date]
        eligible = group[group.ticker.isin(close.columns)].copy()
        eligible = eligible[pd.to_numeric(eligible.rs_rank, errors='coerce').between(1, 99)]
        if eligible.empty:
            continue
        entry_spy = close['SPY'].iloc[start]
        for horizon in HORIZONS:
            end = start + horizon
            if end >= len(close.index) or not np.isfinite(entry_spy) or entry_spy <= 0:
                continue
            exit_spy = close['SPY'].iloc[end]
            if not np.isfinite(exit_spy) or exit_spy <= 0:
                continue
            valid = []
            for row in eligible.itertuples():
                entry, exit_ = close[row.ticker].iloc[start], close[row.ticker].iloc[end]
                if np.isfinite(entry) and np.isfinite(exit_) and entry > 0 and exit_ > 0:
                    excess = ((exit_ / entry - 1) - (exit_spy / entry_spy - 1)) * 100
                    rank = float(row.rs_rank)
                    bucket = next(label for low, high, label in BUCKETS if low < rank <= high)
                    valid.append({'horizon': horizon, 'bucket': bucket, 'excess': excess, 'date': date})
            if valid:
                evaluated_dates.add(date)
                observations.extend(valid)
    if not observations:
        return pd.DataFrame(columns=columns), {
            'observed_snapshot_dates': int(observed.data_date.nunique()), 'evaluated_snapshot_dates': 0}
    frame = pd.DataFrame(observations)
    rows = []
    for (horizon, bucket), group in frame.groupby(['horizon', 'bucket']):
        rows.append({'觀察期間': f'{horizon} 日', 'RS排名組別': bucket,
                     '平均相對SPY報酬 %': group.excess.mean(),
                     '中位數相對SPY報酬 %': group.excess.median(),
                     '跑贏SPY比例 %': 100 * group.excess.gt(0).mean(),
                     '樣本數': len(group),
                     '快照日數': int(group.date.nunique())})
    summary = pd.DataFrame(rows, columns=columns)
    return summary, {'observed_snapshot_dates': int(observed.data_date.nunique()),
                     'evaluated_snapshot_dates': len(evaluated_dates)}
