# PostgreSQL 變化追蹤（Plan 1）

把每次 Google Takeout「已儲存」清單匯入本機 PostgreSQL，保存每次匯入的完整快照，並自動產生「本次 vs 上次」的變化報告（新增／消失店家、所屬清單變化、歇業狀態變化）。

> 設計文件：[docs/superpowers/specs/2026-07-25-postgres-place-history-design.md](superpowers/specs/2026-07-25-postgres-place-history-design.md)
> 實作計畫：[docs/superpowers/plans/2026-07-25-postgres-place-history-plan1-change-tracking.md](superpowers/plans/2026-07-25-postgres-place-history-plan1-change-tracking.md)

## 前置需求

1. 本機 PostgreSQL（17）執行中，已建立專用資料庫與最小權限帳號：
   - 資料庫 `mygooglemap`、角色 `mygmap_app`（僅 localhost、僅此 DB）。
2. `.env` 內含連線資訊（密碼由你自己填，程式從 `.env` 讀取、絕不外印）：
   ```dotenv
   PGHOST=localhost
   PGPORT=5432
   PGDATABASE=mygooglemap
   PGUSER=mygmap_app
   PGPASSWORD=你的密碼
   ```
3. 相依套件已安裝：`uv sync`（會裝 `psycopg`、`pytest`）。

## 使用方式

1. 把新的 Google Takeout「已儲存」匯出 zip 放進 `data/takeout/`（不必解壓）。
2. 執行：
   ```bash
   uv run python -m mygmap.cli
   ```
3. 流程：建立/確認 schema → 取 `data/takeout/` 內 **mtime 最新** 的 zip → 解壓讀清單 → 寫入一次匯入快照 → 產生變化報告。
4. 報告輸出：
   - `data/output/changes_<日期>.md`（可讀）
   - `data/output/changes_<日期>.csv`（可用 Excel 開，規劃 Google Maps 手動整理）

若 `data/takeout/` 沒有可匯入的 zip，程式不會建立空匯入，也不會誤報「全部店家消失」。
首次匯入（無上一次可比對）時，報告標示「初始快照」。

## 資料表

| 表 | 用途 |
|---|---|
| `imports` | 每次匯入一列（來源 zip、時間、店家數） |
| `places` | 每家店一列（穩定身分 `place_key` = Google CID 或正規化名稱＋地址） |
| `list_memberships` | 每次匯入的清單歸屬快照（含該清單條目的筆記／標籤） |
| `closure_checks` | 歇業驗證結果（Plan 1 尚未填入，見下方「尚未涵蓋」） |
| `api_cache` | API 呼叫快取（Plan 2 使用） |
| `schema_meta` | schema 版本 |

## 用 DBeaver / psql 查詢範例

```sql
-- 每次匯入概況
SELECT id, source_zip, place_count, imported_at FROM imports ORDER BY id;

-- 最新一次匯入中，某家店屬於哪些清單
SELECT p.title, m.list_name, m.is_visited
FROM list_memberships m JOIN places p ON p.place_key = m.place_key
WHERE m.import_id = (SELECT max(id) FROM imports)
ORDER BY p.title;

-- 本次比上次「消失」的店家（在上一次匯入有、最新匯入沒有）
WITH ids AS (SELECT id FROM imports ORDER BY id DESC LIMIT 2)
SELECT p.title, p.url
FROM places p
WHERE p.place_key IN (
        SELECT place_key FROM list_memberships WHERE import_id = (SELECT min(id) FROM ids))
  AND p.place_key NOT IN (
        SELECT place_key FROM list_memberships WHERE import_id = (SELECT max(id) FROM ids));
```

## 尚未涵蓋（Plan 2：M4–M7）

Plan 1 專注於「匯入快照 + 變化報告」。以下屬後續 Plan 2：

- enrichment（Gemini 分類、Maps 地址／座標／營業時間）寫入 `places`，取代 `export_cache.json`。
- 歇業驗證寫入 `closure_checks`（屆時「歇業狀態變化」才會有資料）。
- 從 DB 產生抽籤用的 `data/output/stores_data.js`（保留 `lottery.html` 契約），讓 DB 成為唯一資料主體。
- 自動 backfill `data/archive/` 內較早的快照。

## 備註

- 全程本機執行、單一使用者；Google Maps **沒有**寫回珍藏清單的 API，整理仍是拿報告手動處理（見 [雲端回寫指南.md](%E9%9B%B2%E7%AB%AF%E5%9B%9E%E5%AF%AB%E6%8C%87%E5%8D%97.md)）。
- 主控台為 cp950，若自行寫腳本印中文，設 `PYTHONIOENCODING=utf-8` 較保險。
