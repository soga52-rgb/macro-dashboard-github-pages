# Macro Dashboard GitHub Pages

正式前台：每日總經摘要靜態頁。

資料來源由 Google Sheets / Apps Script endpoint 產生；GitHub Actions 抓 JSON 後產生靜態 HTML，讓手機開啟更快。

## Repository Secrets

必要：

- `TODAY_DAILY_SOURCE_URL`
- `WEEKLY_MARKET_SERIES_URL`

選配：

- `WEEKLY_SOURCE_URL`

## 啟用

1. 上傳本檔案包內容到 repo 根目錄。
2. 到 Actions 手動執行 `Build daily macro dashboard`。
3. Settings → Pages → Source 選 `Deploy from a branch`，Branch 選 `main`，Folder 選 `/root`。
