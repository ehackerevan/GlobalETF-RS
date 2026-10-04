"""命令列入口：僅產出本地報表，不發送通知。"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .calculator import calculate
from .assessment import enrich_assessment, coverage_summary
from .prices import download_prices, latest_closed_session
from .report import write_reports
from .universe import load_universe


def main(argv=None):
    parser = argparse.ArgumentParser(description="全球 ETF 相對 SPY 強度掃描")
    parser.add_argument("--universe", help="自訂 ETF 清單 CSV")
    parser.add_argument("--prices", help="離線調整收盤 CSV：Date 索引、各 ETF 為欄位")
    parser.add_argument("--as-of", help="計算指定完整美股收盤日（YYYY-MM-DD）")
    parser.add_argument("--output", default="output", help="報表輸出資料夾")
    parser.add_argument("--volumes", help="離線成交股數 CSV，配合 --raw-prices")
    parser.add_argument("--raw-prices", help="離線未調整收盤 CSV，計算成交金額")
    parser.add_argument("--allow-partial", action="store_true", help="僅供人工檢視，允許不足發布門檻的報表")
    args = parser.parse_args(argv)
    try:
        universe = load_universe(args.universe)
        latest = latest_closed_session()
        session = pd.Timestamp(args.as_of).normalize() if args.as_of else latest
        if session > latest:
            raise ValueError("指定日期尚未完成收盤，拒絕使用盤中行情")
        volumes = raw_prices = None
        if bool(args.volumes) != bool(args.raw_prices) or ((args.volumes or args.raw_prices) and not args.prices):
            raise ValueError("離線成交量及未調整價格需同時提供，且須指定 --prices")
        if args.prices:
            prices = pd.read_csv(args.prices, index_col=0, parse_dates=True)
            if args.volumes:
                volumes = pd.read_csv(args.volumes, index_col=0, parse_dates=True)
                raw_prices = pd.read_csv(args.raw_prices, index_col=0, parse_dates=True)
        else:
            print(f"下載 {len(universe)} 檔 ETF 的美元調整行情，資料日 {session.date()}…", flush=True)
            prices, volumes, raw_prices = download_prices(universe["ticker"].tolist(), session, with_market_data=True)
        result, excluded = calculate(prices, universe, session)
        if len(result) == 1:
            raise ValueError("除 SPY 外沒有合格 ETF，拒絕產出空排名")
        quality = coverage_summary(universe, result)
        if not quality['publishable'] and not args.allow_partial:
            raise ValueError(f"資料完整率不足發布門檻：整體 {quality['coverage_pct']:.1f}%，需 >=90% 且每類 >=70%；拒絕覆寫報表")
        result = enrich_assessment(result, prices, volumes, raw_prices)
        path = write_reports(result, excluded, args.output, prices=prices, quality=quality)
        Path(args.output).mkdir(parents=True, exist_ok=True)
        prices.reindex(columns=universe.ticker).loc[:session].to_csv(Path(args.output) / "adjusted_close.csv", index_label="Date")
        for filename, frame in [('volume.csv', volumes), ('unadjusted_close.csv', raw_prices)]:
            if frame is not None:
                frame.reindex(columns=universe.ticker).loc[:session].to_csv(Path(args.output) / filename, index_label="Date")
            else:
                (Path(args.output) / filename).unlink(missing_ok=True)
        universe.to_csv(Path(args.output) / "universe.csv", index=False, encoding="utf-8-sig")
        metadata = {
            "benchmark": "SPY", "data_date": session.date().isoformat(),
            "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "source": "離線美元調整收盤 CSV" if args.prices else "Yahoo Finance / yfinance auto_adjust=False / Adj Close, Close, Volume",
            "price_basis": "美元配息與拆分調整收盤（離線輸入由使用者確保）",
            "weights": {"63": 0.4, "126": 0.2, "189": 0.2, "252": 0.2},
            "universe_count": len(universe), "ranked_count": len(result) - 1,
            "excluded_count": len(excluded),
            "data_quality": quality,
            "assessment": {"volatility_window": 252, "moving_averages": [50, 200],
                           "liquidity_window": 20, "minimum_dollar_volume": 1000000,
                           "liquidity_basis": "未調整收盤價乘成交股數，非實際成交金額或價差"},
        }
        (Path(args.output) / "run_metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"完成：{len(result)-1} 檔參與排名，{len(excluded)} 檔排除；報表：{path.resolve()}")
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"掃描失敗：{exc}", file=sys.stderr)
        return 1
