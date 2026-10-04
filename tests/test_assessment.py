import numpy as np
import pandas as pd
import pytest
import exchange_calendars as xcals

from global_etf_rs.assessment import enrich_assessment, coverage_summary
from global_etf_rs.calculator import calculate
from global_etf_rs.universe import load_universe
from global_etf_rs.cli import main


def fixture(spy_end=2., etf_end=1.5):
    calendar = xcals.get_calendar('XNYS')
    dates = calendar.sessions_in_range(calendar.session_offset('2026-09-30', -252), '2026-09-30')
    prices = pd.DataFrame({'SPY': 100 * spy_end ** (np.arange(253)/252),
                           'DBA': 100 * etf_end ** (np.arange(253)/252)}, index=dates)
    universe = load_universe().query("ticker in ['SPY', 'DBA']")
    result, _ = calculate(prices, universe, dates[-1])
    return prices, universe, result


@pytest.mark.parametrize('spy_end,etf_end,state',[
    (2.,3.,'相對強・絕對上漲'),(2.,1.5,'相對非強・絕對上漲'),
    (.5,.8,'相對強・絕對非上漲'),(2.,.8,'相對非強・絕對非上漲'),
    (1.,1.,'相對非強・絕對非上漲')])
def test_four_states_include_relative_strength_while_losing_money(spy_end, etf_end, state):
    prices, _, result = fixture(spy_end, etf_end)
    enriched = enrich_assessment(result, prices).set_index('ticker')
    assert enriched.loc['DBA', 'trade_state'] == state
    assert enriched.loc['SPY', 'trade_state'] == '基準'
    assert bool(enriched.loc['DBA', 'above_ma200']) == (etf_end>1)
    if etf_end<1:
        assert enriched.loc['DBA', 'max_drawdown_1y_pct'] == pytest.approx((etf_end-1)*100)
    assert enriched.loc['DBA', 'data_completeness_pct'] == 100


def test_volatility_downside_and_drawdown_match_daily_price_path():
    prices, universe, _ = fixture()
    prices['DBA'] = 100.
    prices.iloc[-3:, prices.columns.get_loc('DBA')] = [200., 100., 150.]
    result,_ = calculate(prices,universe,prices.index[-1])
    row = enrich_assessment(result,prices).set_index('ticker').loc['DBA']
    returns = np.r_[np.zeros(249),1.,-.5,.5]
    assert row.volatility_1y_pct == pytest.approx(np.std(returns,ddof=1)*np.sqrt(252)*100)
    assert row.downside_risk_1y_pct == pytest.approx(50.)
    assert row.max_drawdown_1y_pct == pytest.approx(-50.)
    assert row.current_drawdown_1y_pct == pytest.approx(-25.)


def test_liquidity_uses_raw_price_and_missing_data_is_unknown():
    prices,_,result=fixture()
    raw = pd.DataFrame(100.,index=prices.index,columns=prices.columns)
    volumes = pd.DataFrame(15000.,index=prices.index,columns=prices.columns)
    row=enrich_assessment(result,prices,volumes,raw).set_index('ticker').loc['DBA']
    assert row.avg_dollar_volume_20d == 1500000.
    assert row.liquidity_status == '成交額達門檻'
    volumes.loc[prices.index[-1],'DBA']=np.nan
    row=enrich_assessment(result,prices,volumes,raw).set_index('ticker').loc['DBA']
    assert pd.isna(row.avg_dollar_volume_20d) and row.liquidity_status == '未知'
    row=enrich_assessment(result,prices,volumes,None).set_index('ticker').loc['SPY']
    assert row.liquidity_status == '未知'
    volumes[:]=0.
    assert enrich_assessment(result,prices,volumes,raw).iloc[0].liquidity_status=='低成交額'


def test_category_failure_is_not_hidden_by_high_total_coverage():
    universe=pd.DataFrame({'ticker':['SPY']+[f'A{i}' for i in range(10)]+['B1','B2'],
                           'category':['基準']+['A']*10+['B']*2})
    result=universe[universe.ticker.ne('B2')]
    quality=coverage_summary(universe,result)
    assert quality['coverage_pct']>90
    assert not quality['publishable']
    assert next(x for x in quality['categories'] if x['category']=='B')['coverage_pct']==50


def test_coverage_threshold_boundary_and_empty_category():
    universe=pd.DataFrame({'ticker':['SPY']+[f'{g}{i}' for g in 'ABC' for i in range(10)],
                           'category':['基準']+[g for g in 'ABC' for _ in range(10)]})
    result=universe[~universe.ticker.isin(['C7','C8','C9'])]
    quality=coverage_summary(universe,result)
    assert quality['coverage_pct']==90 and quality['publishable']
    assert not coverage_summary(universe,result[result.category.ne('B')])['publishable']


def test_failed_coverage_does_not_overwrite_previous_report(tmp_path):
    prices,universe,_=fixture()
    universe=load_universe().query("ticker in ['SPY','DBA','CORN']")
    universe.to_csv(tmp_path/'universe.csv',index=False)
    prices.to_csv(tmp_path/'prices.csv')
    output=tmp_path/'site';output.mkdir();(output/'report.html').write_text('之前的有效報表')
    assert main(['--universe',str(tmp_path/'universe.csv'),'--prices',str(tmp_path/'prices.csv'),
                 '--as-of','2026-09-30','--output',str(output)])==1
    assert (output/'report.html').read_text()=='之前的有效報表'


def test_full_history_newer_than_asof_does_not_change_assessment():
    prices,_,result=fixture()
    expected=enrich_assessment(result,prices)
    prices.loc[prices.index[-1]+pd.Timedelta(days=1)]=1e9
    pd.testing.assert_frame_equal(enrich_assessment(result,prices),expected)
