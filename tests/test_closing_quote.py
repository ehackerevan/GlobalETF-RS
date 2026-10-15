from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from global_etf_rs import prices as module


def metadata():
    return {'currency': 'USD', 'regularMarketPrice': 47.04,
            'regularMarketTime': int(pd.Timestamp('2026-10-14T20:00:00Z').timestamp()),
            'currentTradingPeriod': {'regular': {'end': int(pd.Timestamp('2026-10-14T20:00:00Z').timestamp())}}}


def mock_quote(monkeypatch, value):
    monkeypatch.setattr(module.yf, 'Ticker', lambda _: SimpleNamespace(get_history_metadata=lambda: value))


def test_same_session_closing_quote_accepts_auction(monkeypatch):
    value=metadata();value['regularMarketTime']+=55;mock_quote(monkeypatch,value)
    price,stamp=module._closing_quote('INDA',pd.Timestamp('2026-10-14'),46.79,47.05)
    assert price==47.04 and stamp=='2026-10-14T20:00:55+00:00'


@pytest.mark.parametrize('field,value', [
    ('currency','TWD'),('regularMarketPrice',float('nan')),('regularMarketPrice',float('inf')),
    ('regularMarketPrice',0),('regularMarketPrice',500),
    ('regularMarketTime',1792007999),  # 收盤前，包含當日盤中末筆
    ('regularMarketTime',1792008301),  # 超過收盤五分鐘
    ('regularMarketTime',1791921600),  # 前一日
    ('regularMarketTime',1792094400),  # 下一日
])
def test_quote_rejects_wrong_currency_price_or_time(monkeypatch,field,value):
    data=metadata();data[field]=value;mock_quote(monkeypatch,data)
    assert module._closing_quote('INDA',pd.Timestamp('2026-10-14'),46.79,47.05) is None


def test_quote_rejects_wrong_period_missing_metadata_and_missing_bounds(monkeypatch):
    data=metadata();data['currentTradingPeriod']['regular']['end']+=86400;mock_quote(monkeypatch,data)
    assert module._closing_quote('INDA',pd.Timestamp('2026-10-14'),46.79,47.05) is None
    mock_quote(monkeypatch,{})
    assert module._closing_quote('INDA',pd.Timestamp('2026-10-14'),46.79,47.05) is None
    assert module._closing_quote('INDA',pd.Timestamp('2026-10-14'),np.nan,47.05) is None


def test_quote_endpoint_error_preserves_missing(monkeypatch):
    def fail(_): raise OSError('network unavailable')
    monkeypatch.setattr(module.yf,'Ticker',fail)
    assert module._closing_quote('INDA',pd.Timestamp('2026-10-14'),46.79,47.05) is None


def test_recovery_only_latest_missing_pair_and_keeps_history_and_volume(monkeypatch):
    dates=pd.to_datetime(['2026-10-12','2026-10-13','2026-10-14'])
    frame=pd.DataFrame([[45.,44.,100.,44.,46.],[np.nan,np.nan,200.,46.,48.],
                        [np.nan,np.nan,300.,46.79,47.05]],index=dates,
        columns=pd.MultiIndex.from_product([['Adj Close','Close','Volume','Low','High'],['INDA']]))
    monkeypatch.setattr(module.yf,'download',lambda *args,**kwargs:frame.copy())
    mock_quote(monkeypatch,metadata());log=[]
    adj,vol,raw=module.download_prices(['INDA'],pd.Timestamp('2026-10-14'),True,log)
    assert adj.at[dates[-1],'INDA']==raw.at[dates[-1],'INDA']==47.04
    assert pd.isna(adj.at[dates[-2],'INDA'])  # 絕不回填先前缺日
    assert adj.at[dates[0],'INDA']==45 and raw.at[dates[0],'INDA']==44
    assert vol.at[dates[-1],'INDA']==300
    assert len(log)==1 and log[0]['quote_time_utc']=='2026-10-14T20:00:00+00:00'
    assert log[0]['data_date']=='2026-10-14'


def test_recovery_does_not_replace_existing_adjusted_close(monkeypatch):
    date=pd.to_datetime(['2026-10-14'])
    frame=pd.DataFrame([[46.5,47.,300.,46.,48.]],index=date,
        columns=pd.MultiIndex.from_product([['Adj Close','Close','Volume','Low','High'],['INDA']]))
    monkeypatch.setattr(module.yf,'download',lambda *args,**kwargs:frame.copy())
    def no_quote(_): raise AssertionError('existing price must not query quote')
    monkeypatch.setattr(module.yf,'Ticker',no_quote)
    adj,_,raw=module.download_prices(['INDA'],date[0],True,[])
    assert adj.at[date[0],'INDA']==46.5 and raw.at[date[0],'INDA']==47.
