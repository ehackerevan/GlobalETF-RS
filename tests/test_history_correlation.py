from io import StringIO

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from global_etf_rs.calculator import calculate
from global_etf_rs.correlation import calculate_correlation
from global_etf_rs.history import update_history, load_history, restore_history
from global_etf_rs.universe import load_universe


def sample():
    cal=xcals.get_calendar('XNYS')
    dates=cal.sessions_in_range(cal.session_offset('2026-10-02',-299),'2026-10-02')
    rng=np.random.default_rng(42)
    moves=rng.normal(.0005,.01,len(dates)-1)
    prices=pd.DataFrame({'SPY':np.r_[100,100*np.cumprod(1+moves)],
        'DBA':np.r_[100,100*np.cumprod(1+moves*.5+.0003)],
        'CORN':np.r_[100,100*np.cumprod(1-moves*.4)]},index=dates)
    universe=load_universe().query("ticker in ['SPY','DBA','CORN']")
    result,_=calculate(prices,universe,dates[-1])
    return prices,universe,result


def test_bootstrap_is_labeled_and_exact_anchor_changes_match():
    prices,u,r=sample();enriched,h,m=update_history(r,u,prices)
    assert m['snapshot_dates']==22 and m['observed_dates']==1 and m['reconstructed_dates']==21
    cal=xcals.get_calendar('XNYS');date=cal.session_offset(r.data_date.iloc[0],-5)
    prior,_=calculate(prices,u,date)
    expected=r.set_index('ticker').loc['DBA','rs_score']-prior.set_index('ticker').loc['DBA','rs_score']
    row=enriched.set_index('ticker').loc['DBA']
    assert row.rs_change_5d==pytest.approx(expected)
    assert row.history_basis_5d=='重建歷史'
    assert row.history_days_21d==21 and np.isfinite(row.pr_std_21d)
    load_history(StringIO(h.to_csv(index=False)))


def test_same_day_replay_preserves_first_observed_snapshot(tmp_path):
    prices,u,r=sample();_,h,_=update_history(r,u,prices)
    path=tmp_path/'history.csv';h.to_csv(path,index=False)
    changed=r.copy();changed.loc[changed.ticker.eq('DBA'),'rs_score']+=10
    _,new,_=update_history(changed,u,prices,path)
    before=h[h.data_date.eq('2026-10-02')].reset_index(drop=True)
    after=new[new.data_date.eq('2026-10-02')].reset_index(drop=True)
    pd.testing.assert_frame_equal(before,after,check_dtype=False)


def test_changed_pool_keeps_score_change_but_blocks_pr_and_stability(tmp_path):
    prices,u,r=sample();small=u[u.ticker.ne('CORN')]
    before=prices.index[-2];old,_=calculate(prices,small,before)
    _,h,_=update_history(old,small,prices)
    path=tmp_path/'history.csv';h.to_csv(path,index=False)
    enriched,new,m=update_history(r,u,prices,path)
    row=enriched.set_index('ticker').loc['DBA']
    assert np.isfinite(row.rs_change_5d) and pd.isna(row.pr_change_5d)
    assert '母體變更' in row.history_basis_5d
    assert pd.isna(row.pr_std_21d) and row.history_days_21d==1
    assert m['observed_dates']==2


def test_missing_exact_comparison_date_is_not_nearest_day(tmp_path):
    prices,u,r=sample();_,h,_=update_history(r,u,prices)
    date=xcals.get_calendar('XNYS').session_offset('2026-10-02',-5).date().isoformat()
    h=h[h.data_date.ne(date)]
    path=tmp_path/'history.csv';h.to_csv(path,index=False)
    enriched,_,_=update_history(r,u,prices,path)
    assert pd.isna(enriched.set_index('ticker').loc['DBA','rs_change_5d'])
    assert enriched.set_index('ticker').loc['DBA','history_basis_5d']=='資料不足'


def test_corrupt_snapshot_and_past_replay_are_rejected(tmp_path):
    prices,u,r=sample();_,h,_=update_history(r,u,prices)
    with pytest.raises(ValueError,match='重複'):
        load_history(StringIO(pd.concat([h,h.tail(1)]).to_csv(index=False)))
    bad=h.copy();bad.loc[bad.data_date.eq(bad.iloc[0].data_date),'eligible_id']='broken'
    with pytest.raises(ValueError,match='簽章'):
        load_history(StringIO(bad.to_csv(index=False)))
    path=tmp_path/'history.csv';h.to_csv(path,index=False)
    prior,_=calculate(prices,u,prices.index[-2])
    with pytest.raises(ValueError,match='早於'):
        update_history(prior,u,prices,path)


def test_restore_corruption_does_not_write_destination(monkeypatch,tmp_path):
    from global_etf_rs import history as module
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'data_date,ticker\nwrong,SPY\n'
    monkeypatch.setattr(module,'urlopen',lambda *args,**kwargs:Response())
    with pytest.raises(ValueError): restore_history('https://example.test/rs_history.csv',tmp_path/'dest.csv')
    assert not (tmp_path/'dest.csv').exists()


def test_restored_archive_prevents_reconstruction_and_accumulates_next_day(tmp_path):
    prices,u,r=sample();prior,_=calculate(prices,u,prices.index[-2]);_,h,m=update_history(prior,u,prices)
    path=tmp_path/'history.csv';h.to_csv(path,index=False)
    _,new,summary=update_history(r,u,prices,path)
    assert summary['snapshot_dates']==23 and summary['observed_dates']==2
    assert summary['reconstructed_dates']==21
    old=new[new.data_date.lt('2026-10-02')].reset_index(drop=True)
    pd.testing.assert_frame_equal(h.reset_index(drop=True),old,check_dtype=False)


def test_correlations_signed_samples_and_self_excluded():
    prices,u,r=sample();enriched,corr,counts,payload=calculate_correlation(prices,r)
    assert corr.loc['DBA','SPY']==pytest.approx(1.)
    assert corr.loc['CORN','SPY']==pytest.approx(-1.)
    assert counts.loc['DBA','CORN']==63
    row=enriched.set_index('ticker').loc['DBA']
    assert row.most_correlated_ticker=='CORN'
    assert row.peer_correlation_samples==63
    assert payload['end_date']=='2026-10-02'


def test_missing_prices_no_fill_and_constant_returns_are_unknown():
    prices,u,r=sample();prices.loc[prices.index[-10:-7],'DBA']=np.nan
    _,corr,counts,_=calculate_correlation(prices,r)
    assert counts.loc['DBA','SPY']==59 and pd.isna(corr.loc['DBA','SPY'])
    prices['CORN']=100.
    _,corr,counts,payload=calculate_correlation(prices,r)
    assert pd.isna(corr.loc['CORN','CORN']) and counts.loc['CORN','SPY']==63
    i=payload['tickers'].index('CORN');assert payload['matrix'][i][i] is None


def test_future_prices_do_not_change_correlation():
    prices,u,r=sample();_,expected,_,_=calculate_correlation(prices,r)
    prices.loc[prices.index[-1]+pd.Timedelta(days=1)]=1e9
    _,actual,_,_=calculate_correlation(prices,r)
    pd.testing.assert_frame_equal(expected,actual)


def test_missing_published_archive_is_not_silently_rebuilt(monkeypatch,tmp_path):
    from urllib.error import HTTPError
    from global_etf_rs import history as module
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'{"history":{"snapshot_dates":22}}'
    def open_url(url,**kwargs):
        if url.endswith('rs_history.csv'):
            raise HTTPError(url,404,'Not Found',None,None)
        return Response()
    monkeypatch.setattr(module,'urlopen',open_url)
    with pytest.raises(ValueError,match='已發布歷史缺失'):
        restore_history('https://example.test/rs_history.csv',tmp_path/'history.csv')
    assert not (tmp_path/'history.csv').exists()
