# GlobalETF-RS：全球跨資產 ETF 相對強度

這是獨立的 Python 專案；RSNotify 只提供 IBD 類型加權期間的參考，未匯入其程式碼，也不依賴其台股、Telegram、GCP 或籌碼功能。

固定以 **SPY** 為 benchmark，透過美股掛牌 ETF 比較各國／區域股市、大宗商品、農產品、債券、投資風格、市值規模及市值與風格組合。預設清單有 90 檔，包含 SPY；可修改 `global_etf_rs/universe.csv`。

## 安裝與執行

需要 Python 3.10 以上。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install -e '.[dev]' --no-deps
python -m global_etf_rs
```

Windows 啟用虛擬環境使用 `.venv\Scripts\Activate.ps1`。也可執行安裝後的 `global-etf-rs` 命令。

產出於 `output/`：

- `report.html`：瀏覽器直接開啟，內含互動圖表，可依分類、關鍵字與是否跑贏 SPY 篩選。
- `rankings.csv`：所有合格標的、各期間報酬、相對 SPY 報酬與 PR。
- `excluded.csv`：缺行情／歷史不足／缺收盤的標的及原因。
- `adjusted_close.csv`：本次使用的美元調整收盤，可供重跑。
- `run_metadata.json`：來源、計算日期、執行時間、納入／排除數量。
- `universe.csv`：本次 ETF 清單快照。

## HTML 圖表

報表內嵌 Plotly 程式及行情資料，不需要外部 CDN，可離線閱讀。圖表支援游標提示、縮放及工具列 PNG 匯出。

- **加權 RS 排名**：正負長條及 SPY 零基準，可選最強／最弱優先與 15／30／全部檔數。
- **分類強度**：目前篩選結果的 RS 中位數及每類檔數，不代表指數或投資組合報酬。
- **期間熱力圖**：63／126／189／252 日相對 SPY 報酬，以全母體固定的對稱色階比較。
- **一年 RS 走勢**：選擇 ETF，顯示 ETF／SPY 價格比，第一日設為 100；SPY 基準為水平 100。

分類、搜尋與跑贏 SPY 篩選同步更新摘要、圖表及表格。圖表檔數只限制排名圖與熱力圖，表格仍顯示所有符合篩選的標的；PR 保持原母體，不因篩選重新計算。桌面與手機皆可閱讀；寬表格可左右捲動。

## 計算方式

對每個期間 `N = 63、126、189、252` 個美股交易日：

```text
標的報酬 = ETF_t / ETF_(t-N) - 1
SPY 報酬 = SPY_t / SPY_(t-N) - 1
相對報酬 = (1 + 標的報酬) / (1 + SPY 報酬) - 1
RS 分數 = 100 × (0.4 × 相對63日 + 0.2 × 相對126日
                 + 0.2 × 相對189日 + 0.2 × 相對252日)
```

這是相對 SPY 報酬的加權分數，不是 RSI，也不是 RSNotify 原本的台股絕對報酬原始分數。保留原計算的 2:1:1:1 相對權重，但將其正規化為 40%／20%／20%／20%。

分數大於零代表加權期間相對 SPY 較強，不保證每個期間都跑贏 SPY。各期間的相對報酬會另外顯示。

- 全母體 PR：合格 ETF（排除 SPY）的 RS 分數百分位，`ceil(rank(pct=True) × 99)`，限制為 1–99。
- 分類 PR：相同規則，但僅使用同分類合格 ETF。分類數量小時 PR 會跳動；僅一檔時為 99。
- 同分採平均名次，不以代碼決定強弱；報表同分時按代碼排序。
- 一年 RS 線：`100 × (1 + 相對252日報酬)`，一年期錨點設為 100。
- SPY 分數固定為零，呈現為參考列，不參與 PR 母體。

## 行情與日期規則

使用 Yahoo Finance／yfinance 的 `auto_adjust=True` 日線 Close（配息與拆分調整後的報酬代理），不是實際可成交報價。

美股交易所 XNYS 日曆決定期間錨點，包含假日及半日交易。收盤後等待一小時再視為可取用；盤中不使用未完成日線。最新收盤缺價不沿用前日冒充今日。SPY 最近 253 個交易日缺任一日或價格無效，即停止整次計算；其他 ETF 不完整則排除並記錄原因。每次重新下載完整調整歷史，避免配息後混用新舊價格基準。Yahoo 來源的歷史調整可能修訂，重跑應保留原始輸出。

預設使用最新完整收盤日。可指定歷史日期：

```bash
python -m global_etf_rs --as-of 2026-09-30 --output output/20260930
```

可離線重跑，價格 CSV 第一欄為 Date、其餘欄位為 ETF 代碼，內容必須是美元調整收盤價格。程式不會將未調整價格自動轉成含息價格：

```bash
python -m global_etf_rs --prices output/adjusted_close.csv \
  --universe output/universe.csv --as-of 2026-09-30 --output output/replay
```

離線重跑的 `--as-of` 應與檔案資料日一致。下載失敗會回傳非零結束碼；不將來源失敗永久標記為下市。自訂清單必須含 SPY，代碼不可重複。

## ETF 對應與覆蓋限制

清單是可交易代理的起始母體，非世界所有國家完整覆蓋。各國 ETF 通常追蹤 MSCI 或其他市場組合，不一定複製當地新聞常用指數（例如 EWJ 不等於日經 225，EWT 不等於台灣加權指數）。國家 ETF 的美元表現同時包含股票及匯率影響；ARGT 等可能包含境外上市企業，詳細指數、持倉及可交易狀態應以發行商最新資料確認。

農產品包含 **DBA、CORN、WEAT、SOYB、CANE**。USO、UNG、CPER、DBC 與這些農產品 ETF 主要透過期貨取得曝險，報酬包括期貨轉倉及基金費用影響，並非現貨價格報酬。GLD、SLV、PPLT、PALL 為實物金屬曝險；不使用礦業公司股票代替金屬本身。債券類型區分存續期間、信用品質、通膨與國際市場；BNDX 為美元避險策略。預設不含槓桿／反向產品。

## 測試

```bash
python -m pytest -q
```

測試使用離線資料，涵蓋公式、基準缺價、無效價格、ETF 缺價、排名母體、交易日假日、半日交易、Yahoo 欄位格式、下載回補、CLI、HTML 跳脫與過期 CSV 防護。

本階段僅本地計算與輸出報表；沒有設定自動排程或 Telegram 推播。

## GitHub Actions 與 Pages

`.github/workflows/pages.yml` 在推送 main、手動觸發及週一至週五 UTC 22:30（台灣隔日 06:30）執行。美股假日會依交易所日曆使用最近完整收盤日，報表會顯示實際行情日期。GitHub 排程可能延遲，非保證準時。

流程先跑測試，再下載最新完整行情，將 `report.html` 複製為網站入口 `index.html`，並發布報表、CSV 與來源紀錄到 Pages。程式無需 API 金鑰。行情失敗時最多重試三次；全失敗不發布，原網站保留前次資料與日期。

repository 設定的 **Settings → Pages → Build and deployment → Source** 使用 **GitHub Actions**。公開網站與輸出行情皆可供任何人查看；來源紀錄不包含離線輸入的本機路徑。部署只發布 `public/` 成品，不發布開發環境、快取或 `.env`。

Actions 使用固定 commit 的官方 action；建置只有讀取 repository 權限，部署 job 才取得 Pages 發布及 OIDC 權限。不要把私人持倉或個資放入自訂清單或報表。
