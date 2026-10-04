"""保存首次觀測快照；歷史重建與實際觀測分開標示。"""
import argparse
import hashlib
import json
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .assessment import coverage_summary
from .calculator import calculate

METHOD_ID = 'relative-rs-v1-63-126-189-252-40-20-20-20'
COLUMNS = ['data_date', 'ticker', 'name', 'category', 'rs_score', 'rs_rank',
           'universe_id', 'eligible_id', 'method_id', 'snapshot_kind', 'recorded_at_utc']


def fingerprint(values):
    return hashlib.sha256(json.dumps(sorted(values), ensure_ascii=False).encode()).hexdigest()[:16]


def load_history(path):
    if path is None or (not hasattr(path, 'read') and not Path(path).exists()):
        return pd.DataFrame(columns=COLUMNS)
    frame = pd.read_csv(path, dtype={'ticker': str, 'universe_id': str, 'eligible_id': str})
    if not set(COLUMNS).issubset(frame.columns):
        raise ValueError('歷史快照格式不完整，拒絕覆寫')
    frame = frame[COLUMNS]
    if frame.isna().any().any() or frame.duplicated(['data_date', 'ticker']).any():
        raise ValueError('歷史快照缺欄位或日期／標的重複')
    dates = pd.to_datetime(frame.data_date, errors='coerce')
    if dates.isna().any() or not frame.data_date.eq(dates.dt.strftime('%Y-%m-%d')).all():
        raise ValueError('歷史快照日期無效')
    scores = pd.to_numeric(frame.rs_score, errors='coerce')
    ranks = pd.to_numeric(frame.rs_rank, errors='coerce')
    if not np.isfinite(scores).all() or not ranks.between(1, 99).all():
        raise ValueError('歷史快照數值無效')
    if not frame.snapshot_kind.isin(['observed', 'reconstructed']).all():
        raise ValueError('歷史快照來源狀態無效')
    for _, group in frame.groupby('data_date'):
        if any(group[column].nunique() != 1 for column in ['universe_id','eligible_id','method_id','snapshot_kind']):
            raise ValueError('同日快照母體或來源不一致')
        if fingerprint(group.ticker.tolist()) != group.eligible_id.iloc[0]:
            raise ValueError('歷史快照合格母體簽章不一致')
    frame['rs_score'], frame['rs_rank'] = scores, ranks
    return frame


def make_snapshot(result, universe, kind):
    frame = result[result.ticker.ne('SPY')][['data_date','ticker','name','category','rs_score','rs_rank']].copy()
    frame['universe_id'] = fingerprint([(str(row.ticker), str(row.category)) for row in universe.itertuples()])
    frame['eligible_id'] = fingerprint(frame.ticker.tolist())
    frame['method_id'], frame['snapshot_kind'] = METHOD_ID, kind
    frame['recorded_at_utc'] = pd.Timestamp.now(tz='UTC').isoformat()
    return frame[COLUMNS]


def update_history(result, universe, prices, history_path=None):
    history = load_history(history_path)
    end = pd.Timestamp(result.data_date.iloc[0])
    if history.data_date.gt(end.date().isoformat()).any():
        raise ValueError('執行日期早於已保存快照，請使用獨立輸出資料夾以保留歷史')
    calendar = xcals.get_calendar('XNYS')
    targets = calendar.sessions_in_range(end - pd.DateOffset(months=3), end).tz_localize(None)
    # 只向既有歷史之前延伸，不回填中間缺日或覆寫實際快照。
    earliest = history.data_date.min() if not history.empty else end.date().isoformat()
    if len(targets):
        for date in targets[:-1]:
            if date.date().isoformat() >= earliest:
                continue
            try:
                prior, _ = calculate(prices, universe, date)
                if coverage_summary(universe, prior)['publishable']:
                    snapshot = make_snapshot(prior, universe, 'reconstructed')
                    history = snapshot if history.empty else pd.concat([history, snapshot], ignore_index=True)
            except ValueError:
                # 未滿完整一年或缺少基準時保留空缺，不以前後日填補。
                continue
    today = make_snapshot(result, universe, 'observed')
    date_text = end.date().isoformat()
    existing = history[history.data_date.eq(date_text)]
    if existing.empty or existing.snapshot_kind.eq('reconstructed').all():
        remaining = history[history.data_date.ne(date_text)]
        history = today if remaining.empty else pd.concat([remaining, today], ignore_index=True)
    cutoff = calendar.session_offset(end, -259).date().isoformat()
    history = history[history.data_date.ge(cutoff)].sort_values(['data_date','ticker']).reset_index(drop=True)
    enriched = result.copy()
    for column in ['rs_change_5d', 'rs_change_21d', 'pr_change_5d', 'pr_change_21d', 'pr_std_21d']:
        enriched[column] = np.nan
    for window in [5, 21]:
        enriched[f'history_basis_{window}d'] = '資料不足'
    enriched['history_days_21d'] = 0
    enriched['stability_basis'] = '資料不足或母體變更'
    today_meta = today.iloc[0]
    for index, row in enriched[enriched.ticker.ne('SPY')].iterrows():
        ticker = row.ticker
        for window in [5, 21]:
            date = calendar.session_offset(end, -window).date().isoformat()
            prior = history[(history.data_date.eq(date)) & history.ticker.eq(ticker) & history.method_id.eq(METHOD_ID)]
            if not prior.empty:
                old = prior.iloc[0]
                enriched.loc[index, f'rs_change_{window}d'] = row.rs_score - old.rs_score
                same_pool = old.universe_id == today_meta.universe_id and old.eligible_id == today_meta.eligible_id
                if same_pool:
                    enriched.loc[index, f'pr_change_{window}d'] = row.rs_rank - old.rs_rank
                enriched.loc[index, f'history_basis_{window}d'] = ('重建歷史' if old.snapshot_kind == 'reconstructed' else '實際快照') + ('・母體變更（PR不比較）' if not same_pool else '')
        dates = targets[-21:].strftime('%Y-%m-%d')
        trail = history[history.ticker.eq(ticker) & history.data_date.isin(dates) & history.method_id.eq(METHOD_ID)]
        same_pool = trail.universe_id.eq(today_meta.universe_id) & trail.eligible_id.eq(today_meta.eligible_id)
        comparable = trail[same_pool]
        enriched.loc[index, 'history_days_21d'] = len(comparable)
        if len(comparable) == 21 and set(comparable.data_date) == set(dates):
            # 當日重跑用當次結果；保留的歷史原件不被修改。
            ranks = comparable.rs_rank.copy()
            ranks.loc[comparable.data_date.eq(date_text)] = row.rs_rank
            enriched.loc[index, 'pr_std_21d'] = ranks.std(ddof=0)
            enriched.loc[index, 'stability_basis'] = '含重建歷史' if comparable.snapshot_kind.eq('reconstructed').any() else '實際快照'
    summary = {'snapshot_dates': int(history.data_date.nunique()),
               'observed_dates': int(history[history.snapshot_kind.eq('observed')].data_date.nunique()),
               'reconstructed_dates': int(history[history.snapshot_kind.eq('reconstructed')].data_date.nunique()),
               'method_id': METHOD_ID, 'retention_sessions': 260}
    return enriched, history, summary


def restore_history(url, destination):
    try:
        with urlopen(url, timeout=30) as response:
            text = response.read().decode('utf-8-sig')
    except HTTPError as exc:
        if exc.code != 404:
            raise
        metadata_url = url.rsplit('/', 1)[0] + '/run_metadata.json'
        with urlopen(metadata_url, timeout=30) as response:
            metadata = json.loads(response.read())
        if metadata.get('history', {}).get('snapshot_dates', 0):
            raise ValueError('已發布歷史缺失，拒絕靜默重建')
        print('首次啟用歷史：網站尚無快照，將明確標示重建資料')
        return
    load_history(StringIO(text))
    path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    print('已恢復前次發布的 RS 歷史')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='恢復已發布的 RS 歷史')
    parser.add_argument('--url', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    restore_history(args.url, args.destination)
