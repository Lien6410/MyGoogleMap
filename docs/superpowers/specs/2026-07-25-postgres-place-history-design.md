# 設計文件：PostgreSQL 作為地點資料主體與變化追蹤

> 產生日期：2026-07-25
> 狀態：待使用者複審
> 相關記憶：專案架構、資料管線工作流程、gh-pages 部署、`docs/雲端回寫指南.md`

## 1. 背景與目標

目前 MyGoogleMap 是**以 CSV 檔為資料主體**的批次管線：Google Takeout →（合併去重 / Gemini 分類 / Maps 補址 / 歇業驗證）→ `data/output/*.csv` + `stores_data.js` → `lottery.html` 抽籤。

使用者的核心需求是：**定期匯入 Takeout，了解「已儲存地點」跨時間的變化（哪些新增、哪些消失、歇業狀態與所屬清單的變動），據此回頭手動整理 Google Maps。**

本次決定**一次到位**，把 **PostgreSQL 17（本機 `mygooglemap` 資料庫）設為唯一資料主體**：所有地點、清單歸屬、歇業狀態、每次匯入的快照都存在 DB；`stores_data.js` 與 CSV 改為**從 DB 匯出**。`lottery.html` 與 gh-pages 部署流程不變。

### 目標
1. 每次 Takeout 匯入建立一份**完整快照**（append-only 歷史），可回看任一次、看長期趨勢。
2. 自動產生「本次 vs 上次」的**差異報告**（Markdown + CSV），涵蓋三類變化：
   - ➕ 新增 / ➖ 消失的店家
   - 🔁 歇業狀態變化
   - 🔁 所屬清單變化
3. DB 成為 enrichment（分類 / 座標 / 營業時間）與 API 快取的唯一儲存，退役 `export_cache.json` / `verify_cache.json` / 「CSV 當來源」的舊路徑。
4. 全程本機執行、單一使用者、`localhost` 連線、最小權限帳號。

## 2. 範圍

### 納入
- PostgreSQL schema（`imports` / `places` / `list_memberships` / `closure_checks` / `api_cache` / `schema_meta`）。
- 完整管線改寫成讀寫 DB：匯入 → enrichment → 歇業驗證 → 匯出 → 差異報告。
- 從 DB 產生 `data/output/stores_data.js`（保留現有 JS 契約）與既有 CSV。
- 差異報告產生器。
- 既有 Takeout 快照的 bootstrap / backfill。
- pytest 測試（含 `stores_data.js` 契約的 golden test）。

### 不納入（非目標）
- **自動寫回 Google Maps 珍藏清單**——Google 無此 API，永遠是使用者手動（見 `docs/雲端回寫指南.md`）。
- 雲端託管 DB；只用本機 Postgres。
- 追蹤 enrichment **欄位內容**的變化（地址 / 營業時間 / 分類的字面變動）——使用者本次未選；`places` 只保留最新值、覆蓋更新。
- `lottery.html` UI 改動、gh-pages 部署方式改動。

## 3. 唯一鍵（place_key）

以 Google Maps 網址內嵌的 **CID**（`!1s0x…:0x…`，例：`0x3442a90e656a081f:0x713c3942e872dca2`）為主鍵。此邏輯兩支腳本已在使用（`export_to_sheets.extract_cid_from_maps_url`、`verify_stores.extract_cid`）。

- 有 CID → `place_key = <cid>`（例 `0x3442...:0x713c...`）。
- 無 URL/CID（少數）→ `place_key = 'name:' + normalize(title) + '|' + normalize(address)`，`normalize` 去除空白與常見標點（沿用 `verify_stores.name_similarity` 的清洗規則）。

此鍵在「換清單、補地址」時仍能認出同一家店，是跨匯入比對的基礎。

## 4. 資料模型

採「**維度表 + 每次匯入快照**」模型（相對「只存變更事件」，快照模型的 SQL 差異查詢最直觀，且天然保有完整歷史）。

```sql
-- 每次 Takeout 匯入一列
CREATE TABLE imports (
  id                   BIGSERIAL PRIMARY KEY,
  source_zip           TEXT,                 -- 來源 zip 檔名
  takeout_exported_at  TIMESTAMPTZ,          -- 由 zip 檔名解析（可為 NULL）
  imported_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  place_count          INTEGER,
  notes                TEXT
);

-- 店家維度：穩定身分 + 最新 enrichment（取代 export_cache.json 的角色）
CREATE TABLE places (
  place_key            TEXT PRIMARY KEY,     -- CID 或 'name:...'
  cid                  TEXT,
  title                TEXT NOT NULL,
  address              TEXT,
  url                  TEXT,
  lat                  DOUBLE PRECISION,
  lng                  DOUBLE PRECISION,
  cuisine_type         TEXT,                 -- 複合值以半形逗號分隔
  avg_spending         INTEGER,              -- 未知以 NULL 表示
  hours                JSONB,                -- 營業時間結構（parse_place_details_response 產出）
  hours_text           TEXT,
  distance_km          DOUBLE PRECISION,
  first_seen_import_id BIGINT REFERENCES imports(id),
  last_seen_import_id  BIGINT REFERENCES imports(id),
  enriched_at          TIMESTAMPTZ,          -- 最近一次 Gemini/Maps enrichment 時間
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 每次匯入的清單歸屬快照（筆記/標籤屬於「清單條目」，故放這裡而非 places）
CREATE TABLE list_memberships (
  id          BIGSERIAL PRIMARY KEY,
  import_id   BIGINT  NOT NULL REFERENCES imports(id),
  place_key   TEXT    NOT NULL REFERENCES places(place_key),
  list_name   TEXT    NOT NULL,             -- CSV 檔名（去 .csv）
  is_visited  BOOLEAN NOT NULL,             -- 僅「想去的地點」為 false，其餘 true
  note        TEXT,                         -- 該清單條目的「筆記」
  tags        TEXT,                         -- 該清單條目的「標籤」
  raw_title   TEXT,                         -- 此 CSV 中呈現的原始標題
  UNIQUE (import_id, place_key, list_name)
);

-- 每次匯入的歇業驗證結果
CREATE TABLE closure_checks (
  id          BIGSERIAL PRIMARY KEY,
  import_id   BIGINT  NOT NULL REFERENCES imports(id),
  place_key   TEXT    NOT NULL REFERENCES places(place_key),
  status      TEXT    NOT NULL,             -- OPERATIONAL/CLOSED_TEMPORARILY/CLOSED_PERMANENTLY/CLOSED/NOT_FOUND/UNCERTAIN
  is_closed   BOOLEAN NOT NULL,             -- 派生：是否視為停業（沿用 verify_stores 判定）
  source      TEXT,                         -- maps / gemini / gemini+maps / manual
  checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (import_id, place_key)
);

-- API 呼叫快取（取代 export_cache.json / verify_cache.json）
CREATE TABLE api_cache (
  cache_key   TEXT PRIMARY KEY,             -- e.g. __maps_geo__<addr> / __cid_hours__<cid> / find_place<...>
  value       JSONB NOT NULL,
  fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- schema 版本（輕量遷移，無 alembic）
CREATE TABLE schema_meta (
  version     INTEGER NOT NULL,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

索引：`list_memberships(import_id)`、`list_memberships(place_key)`、`closure_checks(import_id)`、`places(cid)`。

### 差異如何計算
「某地點在某次匯入是否存在」= 該 `place_key` 在該 `import_id` 是否有任何 `list_memberships` 列。

- **新增/消失**：`place_key` 在本次匯入有 membership、上次沒有（反之為消失）。
- **所屬清單變化**：同一 `place_key` 在兩次匯入的 `list_name` 集合差異。
- **歇業狀態變化**：`closure_checks.status`（或 `is_closed`）兩次匯入之間的轉變。

差異查詢以**參數化 SQL 寫在 `report.py`**（非 DB stored function），便於單元測試與版本控管。

## 5. 元件與模組架構

新增 `mygmap/` 套件，把兩支既有腳本的**純函式**重構進來共用（CID 抽取、CSV 讀取、Gemini 分類、Maps 查詢、haversine、歇業判定），退役「CSV 當來源」的舊進入點。

| 模組 | 職責 | 依賴 |
|---|---|---|
| `mygmap/config.py` | 由 `.env` 讀取 `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` 與 API keys，組出連線設定。**永不記錄/印出密碼**（只印 host/db/user）。 | `.env` |
| `mygmap/db.py` | psycopg 連線；`init_schema()` 冪等建表；`schema_meta` 版本控管；小工具（upsert、api_cache 讀寫）。 | config |
| `mygmap/takeout.py` | 找 `data/takeout/*.zip` 中 mtime 最新者、解壓、讀 `已儲存/*.csv` → 原始條目（含 標籤/留言 欄）。沿用 `detect_headers`/`read_csv`。 | — |
| `mygmap/places.py` | `place_key` 推導（ingest 與 verify 共用）；`places` upsert。 | db |
| `mygmap/ingest.py` | 建 `imports` 列 → upsert `places` → 寫入該次 `list_memberships` 快照。 | takeout, places, db |
| `mygmap/enrich.py` | 對缺 enrichment 的 `places` 跑 Gemini/Maps（重用 export 函式），走 `api_cache`，回寫 `places`。 | db（api_cache）, 既有 API 函式 |
| `mygmap/verify.py` | 歇業驗證（重用 verify_stores 邏輯）→ 寫入本次 `closure_checks`。 | db, 既有 API 函式 |
| `mygmap/export.py` | 從 DB（最新匯入的 active 店家）產生 `data/output/stores_data.js` 與既有 CSV，**保留 JS 契約**。 | db |
| `mygmap/report.py` | 比對最新兩次匯入 → 產 `data/output/changes_<日期>.md` + `.csv`。 | db |
| `mygmap/cli.py` | 單一進入點，串起完整流程（見 §6）。 | 以上全部 |

執行方式：`uv run python -m mygmap.cli`（或 `uv run mygmap_run.py` 包一層）。

## 6. 端到端資料流（單一指令）

```
1. init_schema()                      # 冪等，確保表存在
2. ingest 最新 zip → 建立 import N     # upsert places、寫 list_memberships 快照
3. enrich(import N 的新/未 enrich 店家) # Gemini/Maps → 回寫 places（api_cache 去重）
4. verify(import N) → closure_checks   # 歇業狀態
5. export ← DB                         # 產 stores_data.js（+ CSV）
6. report(N vs N-1) → changes_<date>   # 差異報告
```

第 5 步產出的 `stores_data.js` 之後仍走**現有 gh-pages 部署**（`git add -f data/output/stores_data.js` → commit → push），此流程不變。

## 7. `stores_data.js` 契約（必須保留）

`lottery.html` 以 `<script src="data/output/stores_data.js">` 載入，期望全域 `window.STORES_DATA = [...]`。每個物件欄位與現行 `export_to_sheets.py`（L910–929）一致：

```js
{ title, address, url, cuisine_type, source_list, visited, distance_km, avg_spending, note, hours }
```

- `visited`：字串 `"是"` / `"否"`（沿用）。
- `distance_km`：數字或 `null`。
- `avg_spending`：數字（未知輸出 `0`，沿用現行 JS 端行為）。
- `hours`：陣列或 `null`。
- `cuisine_type`：半形逗號分隔字串。
- `source_list`：**改為該店在最新匯入所屬清單的逗號合併字串**。理由：`lottery.html` 的篩選只用 `cuisine_type/visited/distance_km/hours`，**未**用 `source_list` 做過濾（僅顯示），故合併更資訊完整且不影響行為。
- Active 定義：在最新匯入存在（有 membership）**且** 最新 `closure_checks.is_closed = false`（或無驗證結果時預設保留，比照現行「只自動移除確認停業者」）。

以 **golden test** 鎖住此契約：對同一份輸入，DB 匯出的 `stores_data.js` 物件集合需與現行腳本輸出等價（欄位齊備、型別一致）。

## 8. 差異報告

每次跑完產生 `data/output/changes_<YYYY-MM-DD>.md`（與對應 `.csv`），分段：

- **➕ 新增店家**：本次出現、上次無。列店名 / 清單 / 連結。
- **➖ 消失店家**：上次有、本次無（可能自行刪除或 Takeout 未含）。
- **🔁 歇業狀態變化**：`OPERATIONAL → CLOSED_*/NOT_FOUND` 等轉變。
- **🔁 所屬清單變化**：清單集合的加入/移除。
- **🧹 建議手動清理清單**：本次判定為永久停業（`CLOSED_PERMANENTLY`/`CLOSED`）或消失者，整理成可直接拿去 Google Maps 手動移除的待辦（呼應 `雲端回寫指南.md`）。

首次執行（無前一次匯入）時，報告標示「初始快照，無可比對基準」。

## 9. 歇業驗證整合

沿用 `verify_stores.py` 的雙重策略（Maps Find Place 為主、Gemini Search Grounding 備援）與判定規則（`CLOSED_PERMANENTLY`/`CLOSED`/`NOT_FOUND`/`CLOSED_TEMPORARILY` → 視為停業）。

- 結果寫入本次 `closure_checks`（每 `place_key` 一列，帶 `status`/`is_closed`/`source`）。
- API 結果進 `api_cache`。**注意**（沿用既有教訓）：Gemini key 失效造成大量 `UNCERTAIN` 污染時，需能重跑覆蓋而非永久吃快取——`verify.py` 對 `UNCERTAIN`/`ERROR` 不寫入長期快取或允許強制重查。
- 誤判率高（`CLOSED_TEMPORARILY`、`NOT_FOUND` 多為國外店/店名含括號），報告只把 `CLOSED_PERMANENTLY`/`CLOSED`/消失 列入「建議手動移除」，其餘標為「待人工複核」。

## 10. 安全

- `config.py` 只**引用** `.env` 的變數名稱組連線；DSN/密碼**永不**寫入 log 或 stdout（日誌只呈現 host/db/user）。
- 沿用先前承諾：開發過程不 `Read` `.env`、不執行會回顯環境變數/密碼的指令。
- DB 帳號為最小權限、僅 `localhost`（已於建立步驟完成）。
- `api_cache`、報告檔均不含任何秘密。

## 11. Bootstrap / Backfill

- **Import #1**：以目前 `data/raw/`（最新 Takeout 已解壓）建立第一次匯入，讓 DB 有基準狀態。
- **選用 backfill**：`data/archive/2026-06-20/`、`2026-06-21/` 內含較早的 `已儲存/*.csv` 與 input 快照，可回填為更早的 `imports`，使**第一次執行即可產出差異**。標為選用，失敗不阻斷主流程。
- 排除既知雜訊：`圖片.csv`（收藏的圖片/迷因，非店家）應排除（沿用既有規則）。

## 12. 測試策略（pytest）

- **單元**
  - `place_key` 推導：有 CID / 無 CID 兩路徑、正規化邊界。
  - 差異 SQL：以 seeded fixtures 造兩次匯入，驗證 新增/消失/清單變化/歇業變化 四類輸出正確。
  - `stores_data.js` golden test：DB 匯出 vs 現行腳本輸出等價。
  - `takeout.py`：標籤/留言欄位解析、`圖片.csv` 排除。
- **整合**：以小型 fixture Takeout zip 跑完整 `cli`，斷言 DB 列數與報告內容；重跑同一匯入具冪等性（不重複、`UNIQUE` 生效）。
- **DB 測試環境**：連 `.env` 的 `PGDATABASE_TEST`（例 `mygooglemap_test`），每個測試包在交易中最後 rollback；需本機 Postgres 執行。
- 主控台為 cp950，測試/腳本輸出避免 emoji 或設 `PYTHONIOENCODING=utf-8`（沿用既有教訓）。

## 13. 相依與環境

- 新增 runtime 相依：`psycopg[binary]`（psycopg 3）。
- 新增 dev 相依：`pytest`。
- 以 `uv` 管理（`pyproject.toml` / `uv.lock`）。`requires-python >=3.11` 不變。

## 14. 風險與緩解

| 風險 | 緩解 |
|---|---|
| 改寫破壞現有抽籤流程 | `stores_data.js` golden test；`lottery.html` 不動 |
| `place_key` 因 URL 缺失/變動而分裂 | CID 優先 + 正規化 name 後備；報告可揭露「疑似同店雙鍵」 |
| enrichment/verify API 費用與速率 | `api_cache` 去重、沿用 batch 控速與 429 重試 |
| Gemini key 失效污染 `UNCERTAIN` | 不長期快取 `UNCERTAIN`/`ERROR`；允許強制重查 |
| cp950 編碼錯誤 | `PYTHONIOENCODING=utf-8`、輸出避免 emoji |
| DB 遷移的資料遺失 | append-only 快照；舊 CSV/archive 保留為離線備份 |

## 15. 開放決策（已採預設）

1. `source_list` 匯出 = 最新匯入所屬清單的逗號合併（不影響 lottery 篩選）。
2. 差異邏輯以 Python 參數化 SQL 實作，不用 DB stored function。
3. schema 以 `CREATE TABLE IF NOT EXISTS` + `schema_meta` 版本輕量管理，不引入 alembic（個人專案 YAGNI）。
4. `avg_spending` DB 內以 `NULL` 表未知；匯出 JS 時未知輸出 `0`（保留現行前端行為）。

## 16. 交付里程碑（實作排序，供後續 writing-plans 展開）

1. **M1 基礎**：`pyproject` 加相依、`config.py`、`db.py`（schema + init）、`places.py`（place_key）。（含單元測試）
2. **M2 匯入與快照**：`takeout.py`、`ingest.py` → 能把最新 zip 灌成一次 import。（含冪等測試）
3. **M3 差異報告**：`report.py` → 產 `changes_<date>.md`/`.csv`。（含四類差異單元測試）
4. **M4 enrichment 上 DB**：`enrich.py` 重用 Gemini/Maps，`places` 取代 `export_cache.json`。
5. **M5 歇業驗證上 DB**：`verify.py` → `closure_checks`。
6. **M6 從 DB 匯出**：`export.py` → `stores_data.js`（+CSV），golden test 通過。
7. **M7 串接與 backfill**：`cli.py` 端到端、archive backfill、文件更新（README / 記憶）。
