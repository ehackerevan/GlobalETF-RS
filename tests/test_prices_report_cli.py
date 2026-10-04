import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from global_etf_rs.cli import main
from global_etf_rs.prices import extract_close, latest_closed_session
from global_etf_rs.report import write_reports
from global_etf_rs.calculator import calculate
from global_etf_rs.universe import load_universe


@pytest.mark.parametrize("now,expected", [
    ("2026-10-03T01:30:00Z", "2026-10-02"),
    ("2026-10-02T18:00:00Z", "2026-10-01"),
    ("2026-10-02T20:30:00Z", "2026-10-01"),
    ("2026-09-07T22:00:00Z", "2026-09-04"),
    ("2025-11-28T19:05:00Z", "2025-11-28"),
])
def test_calendar_handles_intraday_weekend_holiday_and_half_day(now, expected):
    assert latest_closed_session(now) == pd.Timestamp(expected)


@pytest.mark.parametrize("swapped", [False, True])
def test_yahoo_multiindex_formats(swapped):
    frame = pd.DataFrame([[100, 200]], index=pd.to_datetime(["2026-09-30"]),
                         columns=pd.MultiIndex.from_product([["Close"], ["SPY", "GLD"]]))
    if swapped:
        frame = frame.swaplevel(axis=1)
    result = extract_close(frame)
    assert result.loc["2026-09-30", "SPY"] == 100


def test_offline_cli_and_html(tmp_path):
    dates = xcals.get_calendar("XNYS").sessions_in_range(
        xcals.get_calendar("XNYS").session_offset("2026-09-30", -252), "2026-09-30")
    prices = pd.DataFrame({"SPY": 100.0, "DBA": np.linspace(100, 120, 253)}, index=dates)
    universe = load_universe().query("ticker in ['SPY', 'DBA', 'CORN']").copy()
    universe.loc[universe.ticker.eq("DBA"), "name"] = '<script>alert(1)</script>'
    universe.to_csv(tmp_path / "universe.csv", index=False)
    prices.to_csv(tmp_path / "prices.csv", index_label="Date")
    code = main(["--allow-partial", "--universe", str(tmp_path / "universe.csv"), "--prices", str(tmp_path / "prices.csv"),
                 "--as-of", "2026-09-30", "--output", str(tmp_path / "report")])
    assert code == 0
    page = (tmp_path / "report/report.html").read_text()
    assert '&lt;script&gt;' in page
    assert '<script>alert(1)</script>' not in page
    assert "農產品" in page and "2026-09-30" in page
    exclusions = pd.read_csv(tmp_path / "report/excluded.csv")
    assert exclusions.iloc[0].ticker == "CORN"
    assert (tmp_path / "report/adjusted_close.csv").exists()


def test_cli_stale_csv_cannot_be_labeled_today(tmp_path):
    pd.DataFrame({"SPY": [100]}, index=pd.to_datetime(["2026-09-01"])).to_csv(tmp_path / "prices.csv")
    assert main(["--prices", str(tmp_path / "prices.csv"), "--as-of", "2026-09-30", "--output", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out/report.html").exists()


def test_download_adjusted_prices_and_recovery(monkeypatch):
    from global_etf_rs.prices import download_prices
    from global_etf_rs import prices as module
    calls = []
    dates = pd.to_datetime(["2026-09-29", "2026-09-30"])

    def fake_download(tickers, **kwargs):
        calls.append((tickers, kwargs))
        assert kwargs['auto_adjust'] is True
        assert kwargs['end'] == '2026-10-01'
        if len(tickers) == 2:
            return pd.DataFrame([[100, np.nan], [101, 20]], index=dates,
                columns=pd.MultiIndex.from_product([['Close'], ['SPY', 'DBA']]))
        # 回補來源缺少原本有效的最後價格，不能清空它。
        return pd.DataFrame([[19], [np.nan]], index=dates,
                columns=pd.MultiIndex.from_product([['Close'], ['DBA']]))

    monkeypatch.setattr(module.yf, 'download', fake_download)
    result = download_prices(['SPY', 'DBA'], pd.Timestamp('2026-09-30'))
    assert result.loc['2026-09-29', 'DBA'] == 19
    assert result.loc['2026-09-30', 'DBA'] == 20
    assert len(calls) == 2


def test_embedded_chart_data_matches_rankings_and_trend(tmp_path):
    import json
    import re
    from global_etf_rs.report import _trend_payload
    calendar = xcals.get_calendar('XNYS')
    dates = calendar.sessions_in_range(calendar.session_offset('2026-09-30', -252), '2026-09-30')
    prices = pd.DataFrame({'SPY': 100 * 1.001 ** np.arange(253),
                           'DBA': 100 * 1.002 ** np.arange(253)}, index=dates)
    universe = load_universe().query("ticker in ['SPY', 'DBA']")
    result, excluded = calculate(prices, universe, dates[-1])
    html = write_reports(result, excluded, tmp_path, prices=prices).read_text()
    payload = json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    trend = payload['trend']
    assert len(trend['dates']) == 253
    assert trend['dates'][-1] == '2026-09-30'
    assert trend['series']['DBA'][0] == pytest.approx(100)
    assert trend['series']['DBA'][-1] == pytest.approx(result.set_index('ticker').loc['DBA', 'rs_line_1y'])
    assert payload['rows'][0]['rs_score'] == pytest.approx(result.iloc[0].rs_score)
    for chart in ['ranking-chart', 'category-chart', 'heatmap-chart', 'trend-chart']:
        assert f'id="{chart}"' in html
    assert 'cdn.plot.ly' not in html.split('<script>')[0]
    assert 'Plotly.react' in html


def test_chart_payload_escapes_script_termination(tmp_path):
    from global_etf_rs.report import _trend_payload
    universe = load_universe().query("ticker == 'SPY'").copy()
    universe['name'] = '</script><img src=x onerror=alert(1)>'
    result = universe.assign(data_date='2026-09-30', adjusted_close=100., rs_score=0.,
        rs_rank=pd.NA, category_rank=pd.NA, outperforms_spy=False, rs_line_1y=100.,
        **{f'relative_{n}d_pct': 0. for n in [63, 126, 189, 252]})
    excluded = pd.DataFrame(columns=list(universe.columns)+['reason'])
    html = write_reports(result, excluded, tmp_path).read_text()
    assert '</script><img src=x onerror=alert(1)>' not in html
    assert '\\u003c/script\\u003e' in html


def test_public_metadata_does_not_expose_local_input_path(tmp_path):
    import json
    calendar = xcals.get_calendar('XNYS')
    dates = calendar.sessions_in_range(calendar.session_offset('2026-09-30', -252), '2026-09-30')
    input_file = tmp_path / 'private-user-folder' / 'personal-file.csv'
    input_file.parent.mkdir()
    pd.DataFrame({'SPY': 100., 'DBA': np.linspace(100., 120., 253)}, index=dates).to_csv(input_file)
    folder = tmp_path / 'public'
    assert main(['--allow-partial', '--prices', str(input_file), '--as-of', '2026-09-30', '--output', str(folder)]) == 0
    text = (folder / 'run_metadata.json').read_text()
    assert 'private-user-folder' not in text and 'personal-file.csv' not in text
    assert json.loads(text)['source'] == '離線美元調整收盤 CSV'


def test_market_data_download_separates_adjusted_raw_and_volume(monkeypatch):
    from global_etf_rs import prices as module
    dates=pd.to_datetime(['2026-09-29','2026-09-30'])
    def download(tickers,**kwargs):
        assert kwargs['auto_adjust'] is False
        return pd.DataFrame([[90.,100.,123.],[91.,101.,456.]],index=dates,
            columns=pd.MultiIndex.from_tuples([('Adj Close','SPY'),('Close','SPY'),('Volume','SPY')]))
    monkeypatch.setattr(module.yf,'download',download)
    adjusted,volumes,raw=module.download_prices(['SPY'],pd.Timestamp('2026-09-30'),with_market_data=True)
    assert adjusted.loc['2026-09-30','SPY']==91
    assert raw.loc['2026-09-30','SPY']==101
    assert volumes.loc['2026-09-30','SPY']==456
