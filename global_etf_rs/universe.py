"""載入可編輯的 ETF 對應清單，不宣稱涵蓋所有國家。"""
from pathlib import Path

import pandas as pd

BENCHMARK = "SPY"


def load_universe(path=None):
    path = Path(path) if path else Path(__file__).with_name("universe.csv")
    frame = pd.read_csv(path, dtype=str).fillna("")
    required = {"ticker", "name", "category", "exposure", "structure"}
    if not required.issubset(frame.columns):
        raise ValueError(f"清單缺少欄位：{sorted(required - set(frame.columns))}")
    for column in required:
        frame[column] = frame[column].str.strip()
        if frame[column].eq("").any():
            raise ValueError(f"清單欄位不得空白：{column}")
    frame["ticker"] = frame["ticker"].str.upper()
    if frame["ticker"].duplicated().any():
        raise ValueError("ETF 代碼不可重複，以免污染排名母體")
    if not frame["ticker"].str.fullmatch(r"[A-Z][A-Z0-9.-]*").all():
        raise ValueError("清單包含無效的美股代碼")
    if BENCHMARK not in set(frame["ticker"]):
        raise ValueError("清單必須包含 SPY 基準")
    return frame
