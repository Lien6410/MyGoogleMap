# MyGoogleMap — 儲存清單整理與美食抽籤工具

將 Google Maps 個人儲存清單整理成結構化表格，結合 AI 估算消費與距離，並提供互動式抽籤網頁。

---

## 專案特色

1. **多清單合併去重**：掃描 `input/` 資料夾內的所有 CSV，自動合併並去除重複地點，標記「是否曾去過」與「來源清單」。
2. **AI 自動分類**：透過 Gemini 2.5 Flash API 批次判斷餐飲類型（支援複合類型，如 `中式,日式`）、預估人均消費、補足地址。
3. **距離計算**：自動定位住家地址座標，用 Haversine 公式計算各地點與住家的直線距離（公里）。
4. **自動上傳 Google Drive**：整理完成後自動將 CSV 上傳至你指定的 Google Drive 資料夾（需一次性授權設定）。
5. **互動式抽籤網頁**：精美暗色毛玻璃風格，支援回訪狀態、餐飲類型、距離、消費多維篩選，拉霸式動畫與紙花特效。
6. **uv 套件管理**：使用 [uv](https://docs.astral.sh/uv/) 管理 Python 版本與依賴套件，一行指令完成環境設定。
7. **PostgreSQL 變化追蹤**：把每次 Takeout 匯入存成快照，自動產生「新增／消失店家、所屬清單變化」報告，了解已儲存清單跨時間的變化。

---

## PostgreSQL 變化追蹤（Plan 1）

除了 CSV／抽籤流程，本專案可用本機 PostgreSQL 追蹤「已儲存清單跨時間的變化」。

- 執行：`uv run python -m mygmap.cli`（讀 `data/takeout/` 內 mtime 最新的 zip → 存入快照 → 產生報告）
- 報告：`data/output/changes_<日期>.md` 與 `.csv`（可拿去 Google Maps 手動整理）
- 抽籤資料：同一指令也會由 DB 產生 `data/output/stores_data.js`（供 `lottery.html`）與 active/closed CSV——**DB 已是抽籤資料的唯一來源**。
- 前置、資料表、查詢範例、enrichment／歇業驗證與 backfill 詳見 **[docs/postgres-pipeline.md](docs/postgres-pipeline.md)**

---

## 檔案結構

```
MyGoogleMap/
├── input/                    # 放置 Google Takeout 匯出的 CSV 清單
│   ├── 回訪.csv              # 已去過的地點（檔名含「回訪」即標記為已去過）
│   ├── 想去的地點.csv         # 尚未去過的地點
│   └── （更多清單...）        # 未來可直接加入更多 CSV
├── export_to_sheets.py       # 主要整理腳本
├── lottery.html              # 互動式抽籤網頁（雙擊即可開啟）
├── GoogleAppsScript.js       # Google Apps Script 雲端備用方案
├── pyproject.toml            # uv 專案設定與依賴套件清單
├── uv.lock                   # uv 鎖定檔（確保環境一致）
├── .python-version           # Python 版本鎖定（3.11）
├── MyGoogleMap_Stores.csv    # 【自動產生】整理結果
├── stores_data.js            # 【自動產生】抽籤資料庫（供 lottery.html 使用）
├── credentials.json          # 【選用】Google Drive API OAuth2 憑證
├── token.json                # 【自動產生】Google Drive 授權 Token
├── .env                      # 環境變數設定（API Key、住家地址等）
├── GDRIVE_SETUP.md           # Google Drive 上傳詳細設定指南
└── README.md                 # 本說明文件
```

---

## 快速開始

### 步驟 1：安裝 uv（若尚未安裝）

```bash
# Windows（PowerShell）
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 步驟 2：建立環境並安裝套件

```bash
# 進入專案資料夾後，uv 會自動讀取 pyproject.toml 建立 .venv 並安裝所有依賴
uv sync
```

### 步驟 3：取得 Google Maps 清單

1. 前往 [Google Takeout](https://takeout.google.com)。
2. 點選「取消全選」，向下捲動勾選「**已儲存**」。
3. 建立匯出作業，下載 ZIP 並解壓縮。
4. 將要整理的 CSV 檔案移入此專案的 `input/` 資料夾。

> **命名規則**：檔名含「回訪」的清單，其所有地點會被標記為「已去過」；其他 CSV 一律標記為「未去過」。可同時放入多份清單，腳本會自動合併。

### 步驟 4：設定 .env 環境變數

在專案根目錄建立（或編輯）`.env` 檔案：

```env
# 住家地址，用於計算各地點與住家的距離
HOME_ADDRESS="新竹市北區光華一街18號"

# Gemini API Key（用於 AI 分類與地址補全）
# 取得方式：https://aistudio.google.com/app/apikey
GEMINI_API_KEY="你的_GEMINI_API_KEY"

# Google Drive 目標資料夾 ID（選用，用於自動上傳）
# 取得方式：開啟 Google Drive 目標資料夾，複製網址中 /folders/ 後方的 ID 字串
GDRIVE_FOLDER_ID=""
```

### 步驟 5：執行整理腳本

```bash
uv run export_to_sheets.py
```

腳本執行完成後會產生：

- **`MyGoogleMap_Stores.csv`**：整理好的地點總表。
- **`stores_data.js`**：抽籤網頁的本地資料庫。
- 若已設定 Google Drive，CSV 會自動上傳至指定資料夾。

**輸出 CSV 欄位說明：**

| 欄位             | 說明                                       |
| ---------------- | ------------------------------------------ |
| 店名             | 地點名稱                                   |
| 地址             | 地址（若原始資料無地址，由 AI 補全）       |
| 網址             | Google Maps 連結                           |
| 餐飲類型         | 複合分類，以半角逗號分隔，例如 `中式,日式` |
| 來源清單         | 所屬的輸入 CSV 檔名（不含副檔名）          |
| 是否曾去過       | 是 / 否                                    |
| 距離住家(公里)   | 直線距離，未知時顯示「未知」               |
| 人均消費預估(元) | 台幣預估，非餐飲或免費景點顯示「未知」     |
| 備註             | 原始 CSV 中的筆記欄位                      |

### 步驟 6：開啟抽籤網頁

直接**雙擊 `lottery.html`** 在瀏覽器中開啟，即可：

- 透過左側篩選面板設定回訪狀態、餐飲類型、距離、消費範圍。
- 點擊「✨ 開始抽籤」進行拉霸式隨機抽取。
- 抽到結果後可查看地點名稱、地址、來源清單、備註，並一鍵開啟 Google Maps。

### 營業時間篩選

抽籤頁的「營業時間」分類（營業中／早餐／中餐／下午茶／晚餐／消夜／未知）
以 Google Maps 的營業時間為基準，資料存在 `stores_data.js` 每筆的 `hours` 欄位。

- 需在 `.env` 設定 `MAPS_API_KEY` 並啟用 Places API，重跑 `export_to_sheets.py` 才會抓到營業時間。
- 未設定金鑰或查不到營業時間的店家，`hours` 為 `null`，歸類為「未知」，
  預設不會被抽到，需手動勾選「未知」。
- 「營業中」依系統時間即時判斷；用餐時段界線：早餐 05:00–10:30、中餐 10:30–14:00、
  下午茶 14:00–17:00、晚餐 17:00–21:00、消夜 21:00–次日 05:00（依「今天」的營業時間判斷）。

---

## Google Drive 自動上傳設定

> 此步驟為**選用**功能，若不需要自動上傳可跳過。

詳細的逐步設定說明請參閱 **[GDRIVE_SETUP.md](GDRIVE_SETUP.md)**，包含 Google Cloud Console 操作步驟、OAuth 設定流程、常見錯誤排解。

快速摘要：

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 建立專案、啟用 Google Drive API、建立「**桌面應用程式**」類型的 OAuth 2.0 憑證，下載後重新命名為 `credentials.json` 放入專案根目錄。
2. 套件已透過 `uv sync` 一併安裝，**無需額外執行** `pip install`。
3. 開啟 Google Drive 目標資料夾，複製網址列 `/folders/` 後方的 ID，填入 `.env`：
   ```env
   GDRIVE_FOLDER_ID="你的資料夾ID"
   ```
4. 首次執行 `uv run export_to_sheets.py` 時，瀏覽器會自動開啟授權畫面；授權完成後產生 `token.json`，後續執行全自動，無需再次授權。

---

## Google Apps Script 雲端方案

如果希望完全不依賴本機 Python，可改用 Google Apps Script 直接在雲端執行：

1. 在 Google Drive 根目錄建立名為 `MyGoogleMap` 的資料夾。
2. 上傳 `input/` 內的所有 CSV 至該資料夾。
3. 建立新的 Google 試算表，選擇「**擴充功能 > Apps Script**」。
4. 將 `GoogleAppsScript.js` 的完整內容貼入並儲存。
5. 執行 `main` 函式，完成帳號授權後試算表將自動填入整理結果。

---

## 常見問題

**Q：Gemini API 額度不足（429 錯誤）**  
免費版 Gemini API 有每分鐘請求次數限制。稍等幾分鐘後重新執行即可。

**Q：lottery.html 開啟後顯示「未偵測到 stores_data.js」**  
請先執行 `uv run export_to_sheets.py` 產生 `stores_data.js`，再重新整理網頁。

**Q：CSV 中大量地址或距離顯示「未知」**  
請確認 `.env` 中的 `GEMINI_API_KEY` 已正確填寫，且 API 服務未受速率限制。

**Q：如何新增更多清單？**  
直接將新的 CSV 放入 `input/` 資料夾後重新執行腳本。檔名含「回訪」者標記為已去過，其他一律標記為未去過。

**Q：換電腦或協作者如何快速還原環境？**  
在專案資料夾執行 `uv sync`，uv 會依據 `uv.lock` 安裝完全一致的套件版本，並自動使用 `.python-version` 指定的 Python 3.11。

---

## 隱私說明

- 抽籤網頁 `lottery.html` 為純靜態頁面，資料存放於本地 `stores_data.js`，不會上傳至任何第三方伺服器。
- 地點資料透過 Gemini API 進行分析；如需上傳至 Google Drive，資料會傳輸至你自己的 Google 帳戶。
