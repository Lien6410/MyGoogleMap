# 抽籤池限定四清單 + README 主流程改寫 設計

- 日期：2026-08-10
- 範圍：`mygmap/export.py`（產出層）、`tests/test_export.py`、`lottery.html` 提示字、`README.md`、`docs/postgres-pipeline.md`。不動匯入、變化報告、enrichment、歇業驗證。
- 相關記憶：[[project-mygooglemap]]、[[postgres-pipeline]]、[[lottery-ui]]、[[gh-pages-deploy]]

## 1. 背景與問題

抽籤池目前吃「最新匯入的**全部**清單」，共 29 個清單 781 家。裡面混了 YTer（127）、2022高雄美食（30）、各地旅遊清單等——這些是收藏／參考性質，不是「今天要去吃哪家」的候選。實際想抽的只有四個清單。

另一個問題：`是否曾去過` 目前由 `is_visited = (list_name != '想去的地點')` 推導（[mygmap/takeout.py:92](../../../mygmap/takeout.py#L92)），再於 export 端對同一家店的所有清單取 OR。結果是「只在想去的地點 + YTer」的店會被標成**已去過**。實測影響 1 家，但規則本身是錯的。

README 的「快速開始」仍以 `export_to_sheets.py` 為主流程，與「DB 已是抽籤資料唯一來源」矛盾，照著做會產出過時資料。

## 2. 目標 / 非目標

**目標**
1. 抽籤池限定為四個清單：想去的地點、回訪、常用早餐、常用晚餐。
2. `visited` 只由「回訪／常用早餐／常用晚餐」決定。
3. README 主流程改寫為 DB 管線，並寫清楚「更新抽籤池」的完整步驟與四清單規則。

**非目標**
- 不動 DB 匯入範圍：`list_memberships` 仍收全部清單，變化報告仍追蹤 29 個清單。
- 不動 enrichment／歇業驗證的涵蓋範圍（仍對全部店家跑，額度不變）。
- 不動 `window.STORES_DATA` 欄位契約、不動 `lottery.html` 篩選邏輯。
- 不刪除 `export_to_sheets.py` / `GoogleAppsScript.js` / `GDRIVE_SETUP.md`。

## 3. 抽籤池規則

池 = 最新匯入中、未被判定永久歇業、且屬於下列清單之一的店家：

| 清單 | 語意 |
|---|---|
| 想去的地點 | 沒去過 |
| 回訪 | 去過 |
| 常用早餐 | 去過 |
| 常用晚餐 | 去過 |

- `visited`：屬於「回訪／常用早餐／常用晚餐」任一 → `是`，否則 `否`。同時在「想去的地點」與這三者之一時算**去過**。
- `source_list`：只列出這四個清單，不再混入 YTer 等非池清單。
- `note`：仍從該店**任一**清單的條目取第一個非空值，避免遺失只寫在其他清單上的筆記。

**為什麼套在產出層而非匯入層**：DB 的價值是跨時間追蹤全部清單的變化（新增／消失／清單歸屬異動）。匯入層過濾會讓其他清單的歷史斷掉，且新舊快照的比對基準不一致。產出層過濾只影響抽籤資料，歷史完整保留。

**歇業 CSV 不套白名單**：`MyGoogleMap_Stores_closed.csv` 是拿去手動清理 Google Maps 用的維護報告，涵蓋全部清單較有用。因此 active + closed 兩份 CSV 不再互補，需在文件註明。

## 4. 實作

**[mygmap/export.py](../../../mygmap/export.py)**

新增模組常數：

```python
POOL_LISTS = ('想去的地點', '回訪', '常用早餐', '常用晚餐')
VISITED_LISTS = ('回訪', '常用早餐', '常用晚餐')
```

`active_stores()` 的 SQL 不變（仍撈全部清單，`note` 才能跨清單 fallback），改在 Python 分組時套規則：

- 累積 `_lists` 時只收白名單清單名。
- `_visited` 改為 `list_name in VISITED_LISTS` 的 OR。
- 分組結束後，丟棄 `_lists` 為空的店家（＝不屬於任何白名單清單）。

`closed_stores()`、`write_stores_csv()`、`write_stores_js()` 不改（自動繼承 `active_stores()` 的新行為）。

**[tests/test_export.py](../../../tests/test_export.py)**

既有 fixture 的 `營業店`（想去的地點 + 台北牛肉麵）正好是規則變更的案例，斷言改為 `visited == '否'`、`source_list == '想去的地點'`。新增：

- 只屬於非白名單清單的店 → 不進池。
- 屬於「常用晚餐」的店 → `visited == '是'`。
- 同時在「想去的地點」與「回訪」的店 → `visited == '是'`，`source_list` 兩者都列。
- 只寫在非白名單清單上的 `note` 仍保留。

**[lottery.html](../../../lottery.html)**：找不到資料時的 alert 由「請先執行 export_to_sheets.py」改為 `uv run python -m mygmap.cli`。

**[README.md](../../../README.md)**：快速開始改為 DB 管線（安裝 → `.env` → 放 zip → `uv run python -m mygmap.cli` → 產出 → gh-pages 發佈），新增「抽籤池包含哪些清單」規則表；`export_to_sheets.py` / Apps Script / Google Drive 上傳降為「舊版方案（已退役）」附錄。

**[docs/postgres-pipeline.md](../postgres-pipeline.md)**：在 Plan 3 段落補上「產出層只取四清單」與 active/closed 不互補的說明。

## 5. 驗證

- `uv run pytest tests/test_export.py`（需本機 PostgreSQL；無連線會 skip）。
- `uv run pytest` 全套不得退步。
- 以現有 `data/output/stores_data.js` 離線試算的預期值：781 → 435 家，已去過 157 → 156 家。實際重跑管線後數字會因 8/10 新 zip 而變動。
