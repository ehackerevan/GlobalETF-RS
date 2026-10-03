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


def write_reports(result, excluded, output_dir, prices=None):
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    result.to_csv(folder / "rankings.csv", index=False, encoding="utf-8-sig")
    excluded.to_csv(folder / "excluded.csv", index=False, encoding="utf-8-sig")
    columns = ["ticker", "name", "category", "rs_score", "rs_rank", "category_rank",
               "outperforms_spy", "relative_63d_pct", "relative_126d_pct",
               "relative_189d_pct", "relative_252d_pct", "exposure", "structure"]
    display = result[columns].copy()
    display["outperforms_spy"] = display["outperforms_spy"].map({True: "是", False: "否"})
    display.loc[display["ticker"].eq("SPY"), "outperforms_spy"] = "基準"
    table = display.rename(columns=LABELS).to_html(
        index=False, border=0, table_id="rankings", na_rep="—", float_format=lambda value: f"{value:.2f}")
    options = ''.join(f'<option>{escape(category)}</option>' for category in sorted(result["category"].unique()) if category != "基準")
    exclusions = excluded.rename(columns=LABELS).to_html(index=False, border=0) if not excluded.empty else "<p>無排除標的。</p>"
    payload = {"rows": json.loads(result.to_json(orient="records")), "trend": _trend_payload(prices, result)}
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    values = {
        "PLOTLY": get_plotlyjs(), "DATA": data, "TABLE": table,
        "DATE": escape(str(result["data_date"].iloc[0])), "OPTIONS": options,
        "EXCLUSIONS": exclusions, "EXCLUDED_COUNT": str(len(excluded)),
        "UNIVERSE_COUNT": str(len(result) - 1),
    }
    template = Path(__file__).with_name("templates").joinpath("report.html").read_text(encoding="utf-8")
    page = re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: values[match.group(1)], template)
    (folder / "report.html").write_text(page, encoding="utf-8")
    return folder / "report.html"
