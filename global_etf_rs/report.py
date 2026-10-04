"""輸出可離線檢視及分類篩選的繁體中文報表。"""
from html import escape
import json
import re

import pandas as pd
import exchange_calendars as xcals
from plotly.offline import get_plotlyjs
from pathlib import Path

LABELS = {
    "ticker": "代碼", "name": "名稱", "category": "分類", "exposure": "曝險說明",
    "structure": "結構", "data_date": "資料日", "adjusted_close": "調整後價格",
    "rs_score": "加權 RS 分數", "rs_rank": "全母體 PR", "category_rank": "分類 PR",
    "outperforms_spy": "加權跑贏 SPY", "rs_line_1y": "一年 RS 線（起點100）",
    "reason": "排除原因",
    "valid_price_rows": "253日內有效價格筆數", "trade_state": "強弱狀態", "absolute_momentum_pct": "加權絕對動能 %",
    "volatility_1y_pct": "一年年化波動 %", "downside_risk_1y_pct": "一年下行風險 %",
    "max_drawdown_1y_pct": "一年最大回撤 %", "current_drawdown_1y_pct": "距一年高點 %",
    "ma50_gap_pct": "50日均線乖離 %", "ma200_gap_pct": "200日均線乖離 %",
    "above_ma50": "站上50日均線", "above_ma200": "站上200日均線",
    "avg_dollar_volume_20d": "20日近似日均成交額 USD", "liquidity_status": "流動性標記",
    "data_completeness_pct": "標的歷史完整率 %",
}
for window in [63, 126, 189, 252]:
    LABELS[f"return_{window}d_pct"] = f"{window}日報酬 %"
    LABELS[f"relative_{window}d_pct"] = f"{window}日相對 SPY %"


def _trend_payload(prices, result):
    """保留同一資料日的最近一年相對價格，錨點正規化為 100。"""
    if prices is None or prices.empty:
        return {"dates": [], "series": {}}
    end = pd.Timestamp(result["data_date"].iloc[0])
    frame = prices.copy().sort_index()
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(calendar.session_offset(end, -252), end).tz_localize(None)
    frame = frame.reindex(sessions)
    series = {}
    for ticker in result["ticker"]:
        if ticker == "SPY" or ticker not in frame:
            continue
        relative = frame[ticker] / frame["SPY"]
        series[ticker] = (100 * relative / relative.iloc[0]).tolist()
    return {"dates": frame.index.strftime("%Y-%m-%d").tolist(), "series": series}


def write_reports(result, excluded, output_dir, prices=None, quality=None):
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    result.to_csv(folder / "rankings.csv", index=False, encoding="utf-8-sig")
    excluded.to_csv(folder / "excluded.csv", index=False, encoding="utf-8-sig")
    columns = ["ticker", "name", "category", "rs_score", "rs_rank", "category_rank",
               "outperforms_spy", "relative_63d_pct", "relative_126d_pct",
               "relative_189d_pct", "relative_252d_pct", "exposure", "structure"]
    columns += ['trade_state', 'absolute_momentum_pct', 'volatility_1y_pct', 'max_drawdown_1y_pct', 'liquidity_status']
    display = result.reindex(columns=columns).copy()
    display["outperforms_spy"] = display["outperforms_spy"].map({True: "是", False: "否"})
    display.loc[display["ticker"].eq("SPY"), "outperforms_spy"] = "基準"
    table = display.rename(columns=LABELS).to_html(
        index=False, border=0, table_id="rankings", na_rep="—", float_format=lambda value: f"{value:.2f}")
    assessment_columns = ['ticker', 'name', 'trade_state', 'absolute_momentum_pct', 'above_ma50', 'above_ma200',
        'ma50_gap_pct', 'ma200_gap_pct', 'volatility_1y_pct', 'downside_risk_1y_pct',
        'max_drawdown_1y_pct', 'current_drawdown_1y_pct', 'avg_dollar_volume_20d', 'liquidity_status', 'data_completeness_pct']
    assessment = result.reindex(columns=assessment_columns).copy()
    for column in ['above_ma50', 'above_ma200']:
        assessment[column] = assessment[column].map({True: '是', False: '否'})
    assessment_table = assessment.rename(columns=LABELS).to_html(index=False, border=0, table_id='assessment', na_rep='未知', float_format=lambda value: f'{value:,.2f}')
    states = ''.join(f'<option>{escape(str(state))}</option>' for state in sorted(result.get('trade_state', pd.Series(dtype=str)).dropna().unique()) if state != '基準')
    quality = quality or {'status': '未提供完整母體', 'coverage_pct': 100 * (len(result)-1) / max(1,len(result)+len(excluded)-1), 'publishable': False, 'categories': []}
    quality_label = f"{quality['status']} · 可計算 {quality['coverage_pct']:.1f}% · " + ('達發布門檻' if quality['publishable'] else '未達發布門檻／人工檢視')
    quality_table = pd.DataFrame(quality['categories']).rename(columns={'category':'分類','expected':'清單檔數','eligible':'合格檔數','coverage_pct':'完整率 %'}).to_html(index=False,border=0,float_format=lambda value:f'{value:.1f}')
    options = ''.join(f'<option>{escape(category)}</option>' for category in sorted(result["category"].unique()) if category != "基準")
    exclusions = excluded.rename(columns=LABELS).to_html(index=False, border=0) if not excluded.empty else "<p>無排除標的。</p>"
    payload = {"rows": json.loads(result.to_json(orient="records")), "trend": _trend_payload(prices, result), "quality": quality}
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    values = {
        "PLOTLY": get_plotlyjs(), "DATA": data, "TABLE": table,
        "DATE": escape(str(result["data_date"].iloc[0])), "OPTIONS": options,
        "EXCLUSIONS": exclusions, "EXCLUDED_COUNT": str(len(excluded)),
        "UNIVERSE_COUNT": str(len(result) - 1), "ASSESSMENT_TABLE": assessment_table,
        "STATES": states, "QUALITY_LABEL": escape(quality_label), "QUALITY_TABLE": quality_table,
        "QUALITY_CLASS": 'note' if quality['status'] == '完整' else 'quality-warning',
        "CREATED_AT": pd.Timestamp.now(tz='Asia/Taipei').strftime('%Y-%m-%d %H:%M 台灣時間'),
    }
    template = Path(__file__).with_name("templates").joinpath("report.html").read_text(encoding="utf-8")
    page = re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: values[match.group(1)], template)
    (folder / "report.html").write_text(page, encoding="utf-8")
    return folder / "report.html"
