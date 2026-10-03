# 全球 ETF RS 開發計畫

- [x] 確认獨立專案，RSNotify 僅參考加權 RS 計算概念。
- [x] 建立各國／區域、商品與農產品、債券、風格及市值 ETF 對應清單。
- [x] 實作配息調整行情、完整收盤日驗證及 SPY 相對強度。
- [x] 提供全母體／分類 PR、缺資料清單、CSV 與可篩選 HTML 報表。
- [x] 測試基準缺失、報酬公式、最新價缺失、歷史不足、下載格式及報表。
- [x] 實際行情驗證與使用說明。

驗證：22 項離線測試通過；2026-10-02 實際 Yahoo 行情 90 檔完整（89 檔排名與 SPY 基準），0 檔排除。

## HTML 圖表報表

- [x] 新增 RS 排名、分類中位數、期間熱力圖與標的 RS 線。
- [x] 圖表、表格與摘要同步篩選；內嵌圖表程式支援離線。
- [x] 使用實際資料驗證圖表、手機版與互動，更新封裝及說明。

HTML 驗證：24 項測試通過；Chromium 桌面 1440px／手機 390px 檢查四種圖表、分類／搜尋／正分數篩選、最弱排序、空結果及恢復。走勢終值與一年 RS 線相符；瀏覽器無 JavaScript 錯誤、無外部網路資源請求。

## GitHub Actions／Pages 部署

- [x] 移除公開來源紀錄的完整本機路徑並驗證。
- [x] 固定 Actions 版本，以美股收盤後排程執行測試、掃描與 Pages 發布。
- [x] 確認獨立公開 repository 可存取，並推送程式。
- [ ] 帳號端啟用 Pages（Source：GitHub Actions）。
- [ ] 驗證第一次 Actions 與公開網站。

部署阻擋：GitHub gh 已確認登入 ehackerevan；新建 ehackerevan/GlobalETF-RS 被 GitHub 回覆 `Resource not accessible by integration (createRepository)`。尚未建立遠端、未推送、未啟用 Pages；等待使用者建立並授權空白 repository。25 項測試與 diff 檢查通過。

接續部署：已確認 ehackerevan/GlobalETF-RS 為空白公開 repository，透過 GitHub API 推送。第一次 Actions run 37091172258：25 項測試通過，2026-10-02 行情 89 檔排名、0 檔排除；Pages 啟用被 API 與 workflow 回覆 403。等待帳號端設定 Pages Source，再重跑發布。
