# MyGoogleMap — 儲存清單整理與美食抽籤工具

把 Google Maps 個人儲存清單匯入本機 PostgreSQL，追蹤跨時間的變化，並產出互動式抽籤網頁的資料。

線上抽籤頁：<https://Lien6410.github.io/MyGoogleMap/lottery.html>

---

## 專案特色

1. **變化追蹤**：每次 Takeout 匯入存成一份快照，自動產生「新增／消失店家、所屬清單變化、歇業狀態變化」報告。
2. **AI 自動補資料**：Gemini 判斷餐飲類型（支援複合類型，如 `中式,日式`）、預估人均消費、補地址與座標。
3. **營業時間與距離**：透過 Google Maps Places API 取得營業時間，並用 Haversine 公式算出與住家的直線距離。
4. **歇業驗證**：自動標記永久歇業店家，抽籤池不再抽到已倒閉的店。
5. **互動式抽籤網頁**：暗色毛玻璃風格，支援縣市、回訪狀態、餐飲類型、距離、消費、營業時段多維篩選，拉霸動畫與紙花特效。
6. **uv 套件管理**：一行 `uv sync` 完成 Python 版本與依賴設定。

**DB 是抽籤資料的唯一來源** —— `data/output/stores_data.js` 一律由 `mygmap` 管線產生，不要手改。

---

## 更新抽籤池

這是日常最常用的流程：拿到新的 Takeout 匯出後，四步更新線上抽籤頁。

### 步驟 1：下載 Google Takeout 匯出

1. 前往 [Google Takeout](https://takeout.google.com)。
2. 點「取消全選」，向下捲動只勾選「**已儲存**」。
3. 建立匯出作業，下載 ZIP。

### 步驟 2：把 zip 丟進 `data/takeout/`

**不必解壓縮、不必改檔名。** 管線會自動取 `data/takeout/` 內 **mtime 最新**的那顆 zip。

```
data/takeout/takeout-20260810T105338Z-1-001.zip
```

### 步驟 3：執行管線

```bash
uv run python -m mygmap.cli
```

流程：建立/確認 schema → 讀最新 zip → 寫入匯入快照 → enrichment（分類／消費／座標／營業時間）→ 歇業驗證 → 產生變化報告 → 由 DB 產出抽籤資料。

執行結束會印出：

```
[OK] import_id=7 place_count=812 enriched=31 verified=812
[OK] report: data/output/changes_2026-08-10.md
[OK] stores_data.js: data/output/stores_data.js
```

產出檔案：

| 檔案 | 用途 |
| --- | --- |
| `data/output/stores_data.js` | 抽籤網頁的資料庫（`window.STORES_DATA`） |
| `data/output/changes_<日期>.md` | 可讀的變化報告 |
| `data/output/changes_<日期>.csv` | 同上，可用 Excel 開，方便照著手動整理 Google Maps |
| `data/output/MyGoogleMap_Stores_active.csv` | 抽籤池的 CSV 版本 |
| `data/output/MyGoogleMap_Stores_closed.csv` | 判定永久歇業的店家（**涵蓋全部清單**，供手動清理用） |

> enrichment 只補「尚未 enrich」的店家，API 結果會進 `api_cache`，重跑不會重複計費。無 API 金鑰時優雅降級：只做本地啟發式分類，並跳過歇業驗證。

### 步驟 4：發佈到 gh-pages

`data/` 整個被 `.gitignore` 忽略，所以要用 `-f` 強制加入：

```bash
git add -f data/output/stores_data.js
git commit -m "data: 更新抽籤池（<日期> Takeout）"
git push origin gh-pages
```

推上去後線上抽籤頁即更新。本機測試不需要這步——直接雙擊 `lottery.html` 就會讀本地的 `data/output/stores_data.js`。

---

## 抽籤池包含哪些清單

抽籤池**只**取以下四個清單，其他清單（YTer、各地旅遊清單等）仍完整匯入 DB 並納入變化報告，但不會被抽到：

| 清單 | 是否曾去過 |
| --- | --- |
| 想去的地點 | 否 |
| 回訪 | 是 |
| 常用早餐 | 是 |
| 常用晚餐 | 是 |

規則細節：

- 同一家店同時在「想去的地點」與後三者之一 → 算**已去過**。
- 抽籤結果顯示的「來源清單」只列這四個，不會混入其他清單名稱。
- 「備註」仍可來自任一清單的條目，不會因為筆記寫在別的清單上就遺失。
- 永久歇業的店家一律排除（`CLOSED_TEMPORARILY`／查無結果／未驗證者保留）。

要調整名單，改 [mygmap/export.py](mygmap/export.py) 的 `POOL_LISTS` 與 `VISITED_LISTS`。

---

## 首次設定

### 步驟 1：安裝 uv

```bash
# Windows（PowerShell）
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 步驟 2：安裝依賴

```bash
uv sync
```

uv 會依 `pyproject.toml` / `uv.lock` 建立 `.venv` 並安裝完全一致的套件版本，Python 版本由 `.python-version` 鎖定（3.11）。

### 步驟 3：準備 PostgreSQL

本機 PostgreSQL 17，建立專用資料庫 `mygooglemap` 與最小權限帳號 `mygmap_app`（僅 localhost、僅此 DB）。詳見 [docs/postgres-pipeline.md](docs/postgres-pipeline.md)。

### 步驟 4：設定 `.env`

在專案根目錄建立 `.env`：

```dotenv
# PostgreSQL 連線
PGHOST=localhost
PGPORT=5432
PGDATABASE=mygooglemap
PGUSER=mygmap_app
PGPASSWORD=你的密碼

# 住家地址，用於計算各地點與住家的距離
HOME_ADDRESS="新竹市北區光華一街18號"

# Gemini API Key（分類、消費預估、地址補全）
# 取得方式：https://aistudio.google.com/app/apikey
GEMINI_API_KEY="你的_GEMINI_API_KEY"

# Google Maps API Key（營業時間、歇業驗證、地理編碼；未設定時退回用 GEMINI_API_KEY）
MAPS_API_KEY="你的_MAPS_API_KEY"

# 選用：節流設定
ENRICH_BATCH_DELAY=7      # enrich 每批間隔秒數，預設 7（壓在 Gemini 免費層 10 RPM 內）
VERIFY_REQUEST_DELAY=0    # 歇業驗證每次請求間隔秒數，預設 0
```

金鑰只從 `.env` 讀取，程式絕不印出。

---

## 抽籤網頁

直接**雙擊 `lottery.html`**（或開線上版）即可：

- 進階面板設定來源清單、縣市、餐飲類型、距離、消費、營業時段。
- 「符合目前篩選條件的店家數量」旁的**展開名單**可以直接看到這次會從哪些店裡抽，依距離近到遠排序，點一列開該店的 Google Maps。
- 點「✨ 開始抽籤」進行拉霸式隨機抽取。
- 抽到後可看店名、地址、來源清單、備註，並一鍵開啟 Google Maps。

**來源清單篩選**：四個抽籤池清單各一個勾選框（附目前家數），右側「只抽這個」可一鍵單獨鎖定某個清單——例如只從「常用早餐」抽。標題列另有「曾去過」（回訪＋常用早餐＋常用晚餐）與「未去過」（想去的地點）兩個複合快捷，它們只是幫忙勾選，不是額外的篩選維度。全不勾時視同全勾。

篩選與加權的純邏輯抽在 [lottery_logic.js](lottery_logic.js)，測試用 `node --test lottery_logic.test.js`。

### 營業時間篩選

「營業時間」分類（營業中／早餐／中餐／下午茶／晚餐／消夜／未知）以 Google Maps 的營業時間為基準，資料存在 `stores_data.js` 每筆的 `hours` 欄位。

- 需在 `.env` 設定 `MAPS_API_KEY` 並啟用 Places API，重跑管線才會抓到營業時間。
- 查不到營業時間的店家 `hours` 為 `null`，歸類為「未知」，預設不會被抽到，需手動勾選「未知」。
- 「營業中」依系統時間即時判斷；用餐時段界線：早餐 05:00–10:30、中餐 10:30–14:00、下午茶 14:00–17:00、晚餐 17:00–21:00、消夜 21:00–次日 05:00（依「今天」的營業時間判斷）。

---

## 檔案結構

```
MyGoogleMap/
├── mygmap/                   # PostgreSQL 管線套件
│   ├── cli.py                #   進入點：uv run python -m mygmap.cli
│   ├── takeout.py            #   找最新 zip、解壓、讀「已儲存」CSV
│   ├── ingest.py             #   寫入匯入快照
│   ├── enrich.py / gapi.py   #   Gemini／Maps 補資料
│   ├── verify.py             #   歇業驗證
│   ├── report.py             #   變化報告
│   ├── export.py             #   產出 stores_data.js／CSV（抽籤池白名單在此）
│   └── backfill*.py          #   歷史快照與缺漏欄位回填
├── data/
│   ├── takeout/              #   放 Takeout 匯出 zip（不必解壓）
│   ├── archive/              #   歷史「已儲存」快照（供 backfill）
│   └── output/               #   【自動產生】stores_data.js、變化報告、CSV
├── tests/                    # pytest（需 PostgreSQL，無連線會 skip）
├── lottery.html              # 互動式抽籤網頁
├── lottery_logic.js          # 抽籤篩選／加權純邏輯（node --test）
├── hours_logic.js            # 營業時間判斷純邏輯（node --test）
├── docs/postgres-pipeline.md # 管線細節、資料表、SQL 查詢範例
└── .env                      # 環境變數（DB 連線、API Key、住家地址）
```

### 抽籤資料欄位

`stores_data.js` 每筆的欄位（同時是 `MyGoogleMap_Stores_active.csv` 的欄位）：

| 欄位 | 說明 |
| --- | --- |
| `title` 店名 | 地點名稱 |
| `address` 地址 | 原始資料無地址時由 AI／Maps 補全 |
| `url` 網址 | Google Maps 連結 |
| `cuisine_type` 餐飲類型 | 複合分類，半角逗號分隔，例如 `中式,日式` |
| `source_list` 來源清單 | 所屬的抽籤池清單（僅四清單） |
| `visited` 是否曾去過 | 是 / 否 |
| `distance_km` 距離住家(公里) | 直線距離，未知為 `null` |
| `avg_spending` 人均消費預估(元) | 台幣預估，未知為 `0` |
| `note` 備註 | 原始清單中的筆記 |
| `hours` 營業時間 | 每日開關時間陣列，未知為 `null` |

---

## 進階

- **管線細節**：資料表結構、SQL 查詢範例、enrichment／歇業驗證／backfill 說明，見 [docs/postgres-pipeline.md](docs/postgres-pipeline.md)。
- **手動整理 Google Maps**：Google Maps 沒有寫回珍藏清單的 API，拿變化報告手動處理，見 [docs/雲端回寫指南.md](docs/%E9%9B%B2%E7%AB%AF%E5%9B%9E%E5%AF%AB%E6%8C%87%E5%8D%97.md)。

---

## 舊版方案（已退役）

以下是 PostgreSQL 管線之前的作法，**不再是抽籤資料的來源**，僅保留供參考與獨有功能（Google Drive 上傳）使用。照著跑會產出與 DB 不同步的資料。

- **`export_to_sheets.py`**：純 CSV 流程，掃 `input/` 內的 CSV 合併去重、AI 分類、產出 `MyGoogleMap_Stores.csv` 與 `stores_data.js`，並可自動上傳 Google Drive。設定方式見 [GDRIVE_SETUP.md](GDRIVE_SETUP.md)（Google Cloud Console 建立「桌面應用程式」OAuth 憑證 → `credentials.json` → `.env` 填 `GDRIVE_FOLDER_ID`）。
- **`GoogleAppsScript.js`**：完全不依賴本機 Python 的雲端方案。在 Google Drive 建立 `MyGoogleMap` 資料夾上傳 CSV，於試算表「擴充功能 > Apps Script」貼上腳本，執行 `main`。
- **`verify_stores.py`**：舊的獨立歇業驗證腳本，功能已併入 `mygmap.verify`。

---

## 常見問題

**Q：`lottery.html` 開啟後顯示「未偵測到 stores_data.js」**
先執行 `uv run python -m mygmap.cli` 產生 `data/output/stores_data.js`，再重新整理網頁。

**Q：某家店明明在清單裡，卻抽不到**
確認它屬於四個抽籤池清單之一（見上方「抽籤池包含哪些清單」）。若在池內仍抽不到，檢查是否被判定永久歇業（看 `MyGoogleMap_Stores_closed.csv`），或被目前的篩選條件排除（例如沒有營業時間資料而未勾「未知」）。

**Q：Gemini API 額度不足（429 錯誤）**
免費版有每分鐘請求次數限制。調高 `.env` 的 `ENRICH_BATCH_DELAY`，或稍等幾分鐘後重跑——已 enrich 的店家不會重複呼叫。

**Q：大量地址或距離顯示未知**
確認 `.env` 的 `GEMINI_API_KEY` / `MAPS_API_KEY` 正確且未受速率限制。既有店家的缺漏欄位可用 `mygmap.backfill_hours` 定向回填。

**Q：`data/takeout/` 沒有 zip 會怎樣**
程式不會建立空匯入，也不會誤報「全部店家消失」，直接跳過並提示。

**Q：換電腦或協作者如何快速還原環境**
執行 `uv sync`，uv 會依 `uv.lock` 安裝完全一致的套件版本，並使用 `.python-version` 指定的 Python 3.11。另需自行準備 PostgreSQL 與 `.env`。

---

## 隱私說明

- 抽籤網頁為純靜態頁面，資料存放於 `data/output/stores_data.js`，不會上傳至任何第三方伺服器。
- 資料庫、Takeout 檔案全在本機；`data/` 已被 `.gitignore` 忽略，只有 `stores_data.js` 是刻意 force-add 上 gh-pages 供線上抽籤頁使用。
- 地點資料會傳送至 Google（Gemini / Maps API）進行分析；API 金鑰只存在本機 `.env`。
