# PostgreSQL 地點主體遷移（Plan 2：M4–M5 enrichment + 歇業驗證）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把 enrichment（Gemini 分類 / Maps 座標·地址·營業時間）與歇業驗證接進 DB：enrichment 寫入 `places`、歇業結果寫入 `closure_checks`，讓變化報告開始出現真實「歇業狀態變化」。

**Architecture:** 新增 `mygmap/gapi.py`（把 Google API 呼叫從舊腳本抽成**參數化**函式，`MODEL_NAME` 全域改為參數）、`mygmap/cache.py`（`api_cache` 讀寫）、`mygmap/enrich.py`、`mygmap/verify.py`。`enrich`/`verify` 以**可注入的 API callable** 設計，測試一律注入假函式、**不打真實網路**。`cli.run` 在 ingest 後、report 前串接 enrich + verify。

**Tech Stack:** Python 3.11+、`uv`、`psycopg[binary]`、`pytest`、PostgreSQL 17（本機 `mygooglemap` / `mygmap_app`）。沿用 Plan 1 的 `mygmap` 套件與 `conn` 測試 fixture。

## Global Constraints

- **測試不得發出真實網路請求。** `enrich`/`verify` 的 API 呼叫透過參數注入；測試傳入假 callable。真實 API 只在「選用煙霧測試」由使用者手動跑。
- API 金鑰來源：`.env` 的 `GEMINI_API_KEY` / `MAPS_API_KEY`（`config.load_env`）。**無金鑰時優雅降級**：enrich 用本地啟發式分類（無座標/營業時間）、verify 跳過（不寫 `closure_checks`）。金鑰絕不記錄/外印。
- `api_cache`：`UNCERTAIN`/`ERROR`/`None` 狀態**不寫入長期快取**（沿用既有教訓，避免污染後永遠吃快取）。
- 歇業判定沿用 `verify_stores.py`：`CLOSED_PERMANENTLY`/`CLOSED_TEMPORARILY`/`CLOSED`/`NOT_FOUND` → `is_closed=True`。
- `closure_checks` UNIQUE(import_id, place_key)：同一匯入同一店只一列（upsert）。
- **暫時重複**：`gapi.py` 是把舊 `export_to_sheets.py` / `verify_stores.py` 的 API 函式**參數化複製**過來；舊腳本本 Plan **不動**（維持現行 stores_data.js 流程可用），重複將於 **Plan 3（M6–M7）退役舊腳本時消除**。
- 主控台 cp950：Python stdout 不得含 emoji。Commit 訊息結尾 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

---

## File Structure

- `mygmap/gapi.py` — 參數化 Google API 函式 + 純輔助函式（自舊腳本移植；暫時與舊腳本重複）。
- `mygmap/cache.py` — `api_cache` 的 `cache_get` / `cache_set`。
- `mygmap/enrich.py` — 對缺 enrichment 的 `places` 批次補齊，寫回 `places`。
- `mygmap/verify.py` — 對某次匯入的店家做歇業驗證，寫入 `closure_checks`。
- `mygmap/ingest.py` — 補上 try/except → `conn.rollback()`（Plan 1 遺留項）。
- `mygmap/cli.py` — `run()` 串接 enrich + verify（依 `.env` 金鑰建真實 callable，無金鑰則降級）。
- tests：`test_gapi.py`、`test_cache.py`、`test_enrich.py`、`test_verify.py`、`test_cli.py`（擴充）、`test_ingest.py`（擴充 rollback）。

---

## Task 1: gapi.py — 參數化 Google API 函式與純輔助函式

**Files:**
- Create: `mygmap/gapi.py`
- Test: `tests/test_gapi.py`

**Interfaces (Produces):**
- 純輔助（無網路）：`heuristic_classify(title, note) -> (types_csv:str, avg_spending:int)`；`haversine_distance(lat1,lon1,lat2,lon2) -> float|None`；`name_similarity(orig, returned) -> float`；`extract_json_from_text(text) -> dict|None`。
- API（需金鑰，網路）：`geocode(address, maps_api_key) -> (lat,lng)|(None,None)`；`place_details(cid_hex, maps_api_key) -> {"address","hours","hours_text"}`；`find_place_status(name, address, maps_api_key) -> {"status","address","price_level","match"}`；`classify_batch(items, home_address, api_key, model_name) -> list[dict]`（每筆 `{types,avg_spending,lat,lng,address}`，與輸入等長）；`gemini_verify_batch(items, model_name, gemini_key) -> list[dict]`（每筆 `{status,address,price_tw}`）。`items` 為 `[{"title","address"}, ...]`。

- [ ] **Step 1: 寫純輔助函式的失敗測試**

Create `tests/test_gapi.py`：

```python
from mygmap.gapi import (heuristic_classify, haversine_distance,
                         name_similarity, extract_json_from_text)


def test_heuristic_classify_detects_japanese():
    types, spend = heuristic_classify("一蘭拉麵", "")
    assert "日式" in types
    assert spend > 0


def test_heuristic_classify_non_dining_is_other_zero():
    types, spend = heuristic_classify("大安森林公園", "")
    assert types == "其他" and spend == 0


def test_haversine_known_distance():
    # 台北車站 -> 新竹車站 約 65-75 km
    d = haversine_distance(25.0478, 121.5170, 24.8015, 120.9715)
    assert 60 < d < 80


def test_haversine_none_on_missing():
    assert haversine_distance(None, 1, 2, 3) is None


def test_name_similarity_exact_and_mismatch():
    assert name_similarity("小吳牛肉麵", "小吳牛肉麵") >= 0.7
    assert name_similarity("小吳牛肉麵", "麥當勞") < 0.4


def test_extract_json_from_text_handles_wrapping():
    assert extract_json_from_text('前綴 {"a": 1} 後綴') == {"a": 1}
    assert extract_json_from_text("no json") is None
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_gapi.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.gapi'`）。

- [ ] **Step 3: 建立 gapi.py（移植 + 參數化）**

Create `mygmap/gapi.py`。移植下列函式，**邏輯保持與原始碼一致**，僅做標註的參數化調整：

1. 純輔助（直接搬，內容不變）：
   - `heuristic_classify(title, note)` — 自 `export_to_sheets.py:306-381` 完整複製。
   - `haversine_distance(lat1, lon1, lat2, lon2)` — 自 `export_to_sheets.py:514-525` 複製。
   - `name_similarity(orig, returned)` — 自 `verify_stores.py:94-106` 複製。
   - `extract_json_from_text(text)` — 自 `verify_stores.py:191-206` 複製。
   - `_parse_retry_delay(http_error)` — 自 `export_to_sheets.py:500-510` 複製（供下方 API 函式重試用）。
2. API 函式（搬移並參數化）：
   - `geocode(address, maps_api_key)` — 同 `export_to_sheets.geocode_with_maps_api`（`export_to_sheets.py:144-158`），改名為 `geocode`，內容不變。
   - `place_details(cid_hex, maps_api_key)` — 同 `export_to_sheets.lookup_place_details_from_cid`（`export_to_sheets.py:252-278`），改名 `place_details`；把對 `parse_place_details_response` 的依賴改為 `from hours_normalize import parse_place_details_response`（本 repo 根層模組）。
   - `find_place_status(name, address, maps_api_key)` — 同 `verify_stores.query_find_place`（`verify_stores.py:122-186`），改名 `find_place_status`，內容不變（回傳 dict 含 `status/address/price_level/match`）。
   - `classify_batch(items, home_address, api_key, model_name)` — 移植 `export_to_sheets.classify_cuisine_and_details`（`export_to_sheets.py:385-497`），把函式內所有 `MODEL_NAME` 全域改為參數 `model_name`；其餘（Gemini 呼叫、responseSchema、429/500/503 重試、失敗退回 `heuristic_classify`）保持不變。`items` 每筆需有 `title`/`address` 鍵（原程式用 `item['title']`/`item['address']`）。
   - `gemini_verify_batch(items, model_name, gemini_key)` — 移植 `verify_stores.query_gemini_batch`（`verify_stores.py:209-278`），把讀取欄位由 `s['店名']`/`s['地址']` 改為 `s['title']`/`s['address']`；其餘不變（回傳每筆 `{status,address,price_tw}`）。

模組頂部 `import` 需含：`json, math, re, time, urllib.error, urllib.parse, urllib.request`，以及 `from hours_normalize import parse_place_details_response`。**不得**有 `MODEL_NAME` 全域或任何 `os.makedirs` 副作用。

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_gapi.py -v`
Expected: PASS（6 passed）。

- [ ] **Step 5: 確認舊腳本仍可匯入（未破壞）**

Run: `uv run python -c "import export_to_sheets, verify_stores, hours_normalize; print('import OK')"`
Expected: 印出 `import OK`（本 Plan 未改舊腳本，僅確認 gapi 不影響其匯入）。

- [ ] **Step 6: Commit**

```bash
git add mygmap/gapi.py tests/test_gapi.py
git commit -m "feat: 新增 gapi 參數化 Google API 函式（自舊腳本移植，暫時並存）"
```

---

## Task 2: api_cache 讀寫（cache.py）

**Files:**
- Create: `mygmap/cache.py`
- Test: `tests/test_cache.py`

**Interfaces (Produces):**
- `cache_get(conn, key) -> dict|list|None`（無則 None）。
- `cache_set(conn, key, value) -> None`（upsert，`value` 為可 JSON 序列化物件；更新 `fetched_at`）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_cache.py`：

```python
from mygmap import cache


def test_cache_set_then_get_roundtrip(conn):
    cache.cache_set(conn, "k1", {"status": "OPERATIONAL", "n": 3})
    assert cache.cache_get(conn, "k1") == {"status": "OPERATIONAL", "n": 3}


def test_cache_get_missing_returns_none(conn):
    assert cache.cache_get(conn, "nope") is None


def test_cache_set_overwrites(conn):
    cache.cache_set(conn, "k2", {"v": 1})
    cache.cache_set(conn, "k2", {"v": 2})
    assert cache.cache_get(conn, "k2") == {"v": 2}
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_cache.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.cache'`）。

- [ ] **Step 3: 實作 cache.py**

Create `mygmap/cache.py`：

```python
from psycopg.types.json import Json


def cache_get(conn, key):
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM api_cache WHERE cache_key=%s", (key,))
        row = cur.fetchone()
    return row[0] if row else None


def cache_set(conn, key, value):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO api_cache (cache_key, value) VALUES (%s, %s) "
            "ON CONFLICT (cache_key) DO UPDATE SET value=EXCLUDED.value, fetched_at=now()",
            (key, Json(value)),
        )
    conn.commit()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_cache.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add mygmap/cache.py tests/test_cache.py
git commit -m "feat: 新增 api_cache 讀寫（JSONB upsert）"
```

---

## Task 3: enrich.py — places enrichment（可注入 API）

**Files:**
- Create: `mygmap/enrich.py`
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: `mygmap.places.extract_cid`；`mygmap.gapi.haversine_distance`；Task 3 schema（`places`）。
- Produces: `mygmap.enrich.enrich_pending(conn, classify, *, place_details=None, home_lat=None, home_lng=None, batch_size=20, limit=None) -> int`（回傳被 enrich 的店家數）。
  - `classify(items) -> list[dict]`：`items=[{"title","address"}]`，回傳等長 list，每筆 `{types, avg_spending, lat, lng, address}`。
  - `place_details(cid_hex) -> {"address","hours","hours_text"}`（可選；有 url CID 且有提供時，用來覆蓋更精確的地址/營業時間）。
  - 只處理 `places.enriched_at IS NULL` 的店家；完成後設 `enriched_at=now()`、`cuisine_type/avg_spending/lat/lng/address/hours/hours_text/distance_km`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_enrich.py`：

```python
from mygmap.ingest import ingest_entries
from mygmap.enrich import enrich_pending


def _e(title, url='', address=''):
    return {'title': title, 'list_name': '想去的地點', 'url': url,
            'address': address, 'note': '', 'tags': '', 'is_visited': False}


def _fake_classify(items):
    return [{'types': '日式', 'avg_spending': 250, 'lat': 24.8, 'lng': 120.97,
             'address': it['address'] or '新竹市自動補齊'} for it in items]


def test_enrich_fills_places_and_sets_enriched_at(conn):
    ingest_entries(conn, [_e('拉麵店', url='x/data=!1s0x1:0x2')], source_zip='t.zip')
    n = enrich_pending(conn, _fake_classify, home_lat=24.80, home_lng=120.97)
    assert n == 1
    with conn.cursor() as cur:
        cur.execute("SELECT cuisine_type, avg_spending, lat, address, enriched_at, distance_km "
                    "FROM places WHERE title='拉麵店'")
        cuisine, spend, lat, addr, enriched_at, dist = cur.fetchone()
    assert cuisine == '日式' and spend == 250 and lat == 24.8
    assert addr == '新竹市自動補齊'
    assert enriched_at is not None
    assert dist == 0.0            # home == place coords -> 0 km


def test_enrich_skips_already_enriched(conn):
    ingest_entries(conn, [_e('已補齊店', url='x/data=!1s0x3:0x4')], source_zip='t.zip')
    assert enrich_pending(conn, _fake_classify) == 1
    # second run: nothing pending
    assert enrich_pending(conn, _fake_classify) == 0


def test_enrich_uses_place_details_for_address_and_hours(conn):
    ingest_entries(conn, [_e('有CID店', url='x/data=!1s0xaa:0xbb')], source_zip='t.zip')

    def fake_details(cid):
        return {'address': '精確地址', 'hours': [{'d': 1, 'o': '1100', 'c': '1400'}],
                'hours_text': '週一 11-14'}

    enrich_pending(conn, _fake_classify, place_details=fake_details)
    with conn.cursor() as cur:
        cur.execute("SELECT address, hours_text, hours FROM places WHERE title='有CID店'")
        addr, htext, hours = cur.fetchone()
    assert addr == '精確地址'
    assert htext == '週一 11-14'
    assert hours == [{'d': 1, 'o': '1100', 'c': '1400'}]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.enrich'`）。

- [ ] **Step 3: 實作 enrich.py**

Create `mygmap/enrich.py`：

```python
from psycopg.types.json import Json

from .gapi import haversine_distance
from .places import extract_cid


def _pending_places(conn, limit=None):
    sql = ("SELECT place_key, title, address, url FROM places "
           "WHERE enriched_at IS NULL ORDER BY place_key")
    params = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (int(limit),)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [{'place_key': r[0], 'title': r[1], 'address': r[2], 'url': r[3]}
                for r in cur.fetchall()]


def _update_place(conn, place_key, det, address, lat, lng, hours, hours_text, distance_km):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE places SET
                cuisine_type = %s,
                avg_spending = %s,
                lat = %s, lng = %s,
                address = COALESCE(NULLIF(%s, ''), address),
                hours = %s, hours_text = %s,
                distance_km = %s,
                enriched_at = now(), updated_at = now()
            WHERE place_key = %s
            """,
            (det.get('types'), det.get('avg_spending'), lat, lng,
             address, Json(hours) if hours is not None else None, hours_text,
             distance_km, place_key),
        )


def enrich_pending(conn, classify, *, place_details=None,
                   home_lat=None, home_lng=None, batch_size=20, limit=None):
    pending = _pending_places(conn, limit)
    done = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        items = [{'title': p['title'], 'address': p['address'] or ''} for p in batch]
        results = classify(items)
        for p, det in zip(batch, results):
            lat, lng = det.get('lat'), det.get('lng')
            address = p['address'] or det.get('address') or ''
            hours, hours_text = None, ''
            cid = extract_cid(p['url'] or '')
            if place_details and cid:
                pd = place_details(cid)
                if pd.get('address'):
                    address = pd['address']
                hours = pd.get('hours')
                hours_text = pd.get('hours_text', '')
            distance_km = (haversine_distance(home_lat, home_lng, lat, lng)
                           if home_lat is not None and home_lng is not None else None)
            _update_place(conn, p['place_key'], det, address, lat, lng,
                          hours, hours_text, distance_km)
            done += 1
    conn.commit()
    return done
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add mygmap/enrich.py tests/test_enrich.py
git commit -m "feat: 新增 enrich（依注入分類器補齊 places，含 CID 精確地址/營業時間）"
```

---

## Task 4: verify.py — 歇業驗證寫入 closure_checks（可注入 API）

**Files:**
- Create: `mygmap/verify.py`
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: `mygmap.cache`（api_cache）；Task 3 schema（`closure_checks`、`list_memberships`、`places`）。
- Produces: `mygmap.verify.verify_import(conn, import_id, find_place, *, gemini_verify=None, limit=None) -> int`（回傳寫入的 closure_checks 筆數）。
  - `find_place(name, address) -> {"status","address","price_level","match"}`。
  - 對「該 import 有出現（有 membership）」的每個 place 驗證；`status ∈ {CLOSED_PERMANENTLY,CLOSED_TEMPORARILY,CLOSED,NOT_FOUND}` → `is_closed=True`。
  - 快取鍵 `__closure__<place_key>`；`UNCERTAIN`/`ERROR`/`UNKNOWN`/None 不寫長期快取，也不視為停業。
  - 每個 place upsert 一列 `closure_checks`（UNIQUE(import_id,place_key)）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_verify.py`：

```python
from mygmap.ingest import ingest_entries
from mygmap.verify import verify_import
from mygmap import cache


def _e(title, url):
    return {'title': title, 'list_name': '想去的地點', 'url': url, 'address': '新竹市',
            'note': '', 'tags': '', 'is_visited': False}


def test_verify_writes_closure_rows_and_flags_closed(conn):
    iid = ingest_entries(conn, [
        _e('營業中店', 'x/data=!1s0x1:0x1'),
        _e('永久歇業店', 'x/data=!1s0x2:0x2'),
    ], source_zip='t.zip')

    def fake_find(name, address):
        status = 'CLOSED_PERMANENTLY' if name == '永久歇業店' else 'OPERATIONAL'
        return {'status': status, 'address': '', 'price_level': None, 'match': 'EXACT'}

    n = verify_import(conn, iid, fake_find)
    assert n == 2
    with conn.cursor() as cur:
        cur.execute("SELECT title, status, is_closed FROM closure_checks c "
                    "JOIN places p ON p.place_key=c.place_key ORDER BY title")
        rows = cur.fetchall()
    assert ('永久歇業店', 'CLOSED_PERMANENTLY', True) in rows
    assert ('營業中店', 'OPERATIONAL', False) in rows


def test_verify_uses_cache_second_run(conn):
    iid = ingest_entries(conn, [_e('快取店', 'x/data=!1s0x9:0x9')], source_zip='t.zip')
    calls = []

    def fake_find(name, address):
        calls.append(name)
        return {'status': 'OPERATIONAL', 'address': '', 'price_level': None, 'match': 'EXACT'}

    verify_import(conn, iid, fake_find)
    iid2 = ingest_entries(conn, [_e('快取店', 'x/data=!1s0x9:0x9')], source_zip='t2.zip')
    verify_import(conn, iid2, fake_find)
    assert len(calls) == 1          # second run served from api_cache


def test_verify_uncertain_not_cached(conn):
    iid = ingest_entries(conn, [_e('不確定店', 'x/data=!1s0x7:0x7')], source_zip='t.zip')

    def fake_find(name, address):
        return {'status': 'UNKNOWN', 'address': '', 'price_level': None, 'match': 'API_ERROR'}

    verify_import(conn, iid, fake_find)
    assert cache.cache_get(conn, '__closure__0x7:0x7') is None   # not long-term cached
    with conn.cursor() as cur:
        cur.execute("SELECT is_closed FROM closure_checks")
        assert cur.fetchone()[0] is False        # UNKNOWN is not 'closed'
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_verify.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.verify'`）。

- [ ] **Step 3: 實作 verify.py**

Create `mygmap/verify.py`：

```python
from . import cache

CLOSED_STATUSES = {'CLOSED_PERMANENTLY', 'CLOSED_TEMPORARILY', 'CLOSED', 'NOT_FOUND'}
_UNSURE = {'UNCERTAIN', 'ERROR', 'UNKNOWN', None}


def _places_in_import(conn, import_id, limit=None):
    sql = ("SELECT DISTINCT p.place_key, p.title, p.address "
           "FROM list_memberships m JOIN places p ON p.place_key=m.place_key "
           "WHERE m.import_id=%s ORDER BY p.place_key")
    params = [import_id]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [{'place_key': r[0], 'title': r[1], 'address': r[2]} for r in cur.fetchall()]


def _write_closure(conn, import_id, place_key, status, is_closed, source):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO closure_checks (import_id, place_key, status, is_closed, source)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (import_id, place_key) DO UPDATE SET
                status=EXCLUDED.status, is_closed=EXCLUDED.is_closed,
                source=EXCLUDED.source, checked_at=now()
            """,
            (import_id, place_key, status, is_closed, source),
        )


def verify_import(conn, import_id, find_place, *, gemini_verify=None, limit=None):
    written = 0
    for p in _places_in_import(conn, import_id, limit):
        ck = f"__closure__{p['place_key']}"
        cached = cache.cache_get(conn, ck)
        if cached and cached.get('status') not in _UNSURE:
            status, source = cached['status'], cached.get('source', 'cache')
        else:
            res = find_place(p['title'], p['address'] or '')
            status, source = res.get('status', 'UNKNOWN'), 'maps'
            if status not in _UNSURE:
                cache.cache_set(conn, ck, {'status': status, 'source': source})
        is_closed = status in CLOSED_STATUSES
        _write_closure(conn, import_id, p['place_key'], status, is_closed, source)
        written += 1
    conn.commit()
    return written
```

（`gemini_verify` 參數保留給 cli 串接時的備援；本任務先不接，Task 5 依 `.env` 金鑰決定是否傳入。）

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_verify.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add mygmap/verify.py tests/test_verify.py
git commit -m "feat: 新增 verify（歇業驗證寫入 closure_checks，UNCERTAIN 不快取）"
```

---

## Task 5: ingest rollback + cli 串接 enrich/verify

**Files:**
- Modify: `mygmap/ingest.py`
- Modify: `mygmap/cli.py`
- Modify: `mygmap/gapi.py`（新增兩個 factory helper）
- Test: `tests/test_ingest.py`（擴充）、`tests/test_cli.py`（擴充）

**Interfaces:**
- `mygmap.ingest.ingest_entries` 行為不變，但任何例外 → `conn.rollback()` 後 re-raise。
- `mygmap.gapi.make_classifier(api_key, model_name, home_address='') -> callable(items)->list` 與 `mygmap.gapi.make_find_place(maps_api_key) -> callable(name,address)->dict`：把金鑰/模型綁定成 enrich/verify 需要的注入介面。
- `mygmap.cli.run(...)` 新增：ingest 後、report 前，若 `.env` 有金鑰則 enrich pending + verify 本次 import；無金鑰則 enrich 用本地啟發式、跳過 verify。回傳 dict 新增 `enriched`、`verified` 兩鍵。

- [ ] **Step 1: 為 ingest rollback 寫失敗測試**

在 `tests/test_ingest.py` 追加：

```python
import pytest


def test_ingest_rolls_back_on_error(conn):
    bad = [{'title': '好店', 'list_name': 'A', 'url': 'x/data=!1s0x1:0x1',
            'address': '', 'note': '', 'tags': '', 'is_visited': True},
           {'title': None, 'list_name': 'A', 'url': '', 'address': '',
            'note': '', 'tags': '', 'is_visited': True}]   # title=None violates NOT NULL
    with pytest.raises(Exception):
        ingest_entries(conn, bad, source_zip='t.zip')
    # connection must be usable again (rolled back, not aborted)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM imports")
        assert cur.fetchone()[0] == 0
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_ingest.py::test_ingest_rolls_back_on_error -v`
Expected: FAIL（無 rollback 時，例外後連線處於 aborted transaction，`SELECT` 會拋 `InFailedSqlTransaction`）。

- [ ] **Step 3: 為 ingest_entries 加上 rollback**

在 `mygmap/ingest.py`，把 `with conn.cursor() as cur:` 整段包進 try/except：

```python
def ingest_entries(conn, entries, source_zip=None, takeout_exported_at=None):
    try:
        with conn.cursor() as cur:
            # ... 既有內容完全不變 ...
        conn.commit()
        return import_id
    except Exception:
        conn.rollback()
        raise
```

（僅新增 try/except 與 rollback；游標區塊內既有 SQL 不動。）

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: PASS（原有 3 + rollback 1 = 4 passed）。

- [ ] **Step 5: gapi 新增 factory helper**

在 `mygmap/gapi.py` 末端新增：

```python
def make_classifier(api_key, model_name, home_address=''):
    """回傳 enrich_pending 需要的 classify(items)->list。無 api_key 時退回本地啟發式。"""
    def classify(items):
        if not api_key:
            out = []
            for it in items:
                types, spend = heuristic_classify(it['title'], '')
                out.append({'types': types, 'avg_spending': spend,
                            'lat': None, 'lng': None, 'address': it.get('address', '')})
            return out
        return classify_batch(items, home_address, api_key, model_name)
    return classify


def make_find_place(maps_api_key):
    """回傳 verify_import 需要的 find_place(name,address)->dict；無金鑰回傳 ERROR。"""
    def find_place(name, address):
        if not maps_api_key:
            return {'status': 'ERROR', 'address': '', 'price_level': None, 'match': 'SKIP'}
        return find_place_status(name, address, maps_api_key)
    return find_place
```

- [ ] **Step 6: 為 cli 串接寫失敗測試**

在 `tests/test_cli.py` 追加（用 monkeypatch 注入假 enrich/verify，避免真實 API 與金鑰依賴）：

```python
def test_run_calls_enrich_and_verify(conn, tmp_path, monkeypatch):
    import mygmap.cli as climod
    calls = {'enrich': 0, 'verify': 0}

    def fake_enrich(conn_, classify, **kw):
        calls['enrich'] += 1
        return 0

    def fake_verify(conn_, import_id, find_place, **kw):
        calls['verify'] += 1
        return 0

    monkeypatch.setattr(climod, 'enrich_pending', fake_enrich)
    monkeypatch.setattr(climod, 'verify_import', fake_verify)

    takeout_dir = _make_zip(tmp_path)
    result = climod.run(conn, takeout_dir=takeout_dir, out_dir=str(tmp_path / 'out'))
    assert result['import_id'] is not None
    assert calls['enrich'] == 1 and calls['verify'] == 1
    assert 'enriched' in result and 'verified' in result
```

- [ ] **Step 7: 執行確認失敗**

Run: `uv run pytest tests/test_cli.py::test_run_calls_enrich_and_verify -v`
Expected: FAIL（`run` 尚未呼叫 enrich/verify，或 result 無 `enriched`/`verified`）。

- [ ] **Step 8: 更新 cli.run 串接 enrich + verify**

改寫 `mygmap/cli.py`（新增 import 與串接；保留 Plan 1 的無-zip guard）：

```python
import os

from . import config, db, gapi, report
from .enrich import enrich_pending
from .ingest import ingest_entries
from .takeout import extract_and_read, find_latest_zip, parse_export_time
from .verify import verify_import


def run(conn, takeout_dir='data/takeout', out_dir='data/output'):
    db.init_schema(conn)
    zip_path = find_latest_zip(takeout_dir)
    entries = extract_and_read(zip_path) if zip_path else []
    source_zip = os.path.basename(zip_path) if zip_path else None
    if not entries:
        return {'import_id': None, 'report_path': None, 'place_count': 0,
                'enriched': 0, 'verified': 0, 'zip': source_zip}

    exported_at = parse_export_time(source_zip) if source_zip else None
    import_id = ingest_entries(conn, entries, source_zip=source_zip,
                               takeout_exported_at=exported_at)

    env = config.load_env()
    api_key = env.get('GEMINI_API_KEY', '')
    maps_key = env.get('MAPS_API_KEY', '') or api_key
    model = env.get('GEMINI_MODEL', 'gemini-2.5-flash')
    home = env.get('HOME_ADDRESS', '')

    classify = gapi.make_classifier(api_key, model, home_address=home)
    enriched = enrich_pending(conn, classify)

    verified = 0
    if maps_key:
        verified = verify_import(conn, import_id, gapi.make_find_place(maps_key))

    report_path = report.write_report(conn, out_dir=out_dir)
    with conn.cursor() as cur:
        cur.execute("SELECT place_count FROM imports WHERE id=%s", (import_id,))
        place_count = cur.fetchone()[0]
    return {'import_id': import_id, 'report_path': report_path,
            'place_count': place_count, 'enriched': enriched,
            'verified': verified, 'zip': source_zip}


def main():
    conn = db.connect()
    try:
        result = run(conn)
        if result['import_id'] is None:
            print("[INFO] data/takeout/ 找不到可匯入的 zip 或清單，未進行匯入。")
            return
        print(f"[OK] import_id={result['import_id']} place_count={result['place_count']} "
              f"enriched={result['enriched']} verified={result['verified']}")
        print(f"[OK] report: {result['report_path']}")
    finally:
        conn.close()
```

- [ ] **Step 9: 執行確認通過（含全套）**

Run: `uv run pytest -v`
Expected: 全部 PASS，0 skipped（DB 可達）。

- [ ] **Step 10: Commit**

```bash
git add mygmap/ingest.py mygmap/cli.py mygmap/gapi.py tests/test_ingest.py tests/test_cli.py
git commit -m "feat: cli 串接 enrich+verify，ingest 例外時 rollback"
```

---

## Task 6: 文件 + 選用真實 API 煙霧測試

**Files:**
- Modify: `docs/postgres-pipeline.md`

**Interfaces:** 使用說明更新；一次選用的真實資料驗證（需 `.env` 金鑰）。

- [ ] **Step 1: 更新文件**

Modify `docs/postgres-pipeline.md`：把「尚未涵蓋」段落中 enrichment 與歇業驗證兩項移到「已支援」；補充：跑一次 `uv run python -m mygmap.cli` 現在會 enrich pending 店家並寫入 closure_checks，報告的「歇業狀態變化」自第二次匯入起會有資料；說明無金鑰時的降級行為（enrich 只做本地啟發式、verify 跳過）。標註 M6–M7（從 DB 產 stores_data.js、退役舊腳本、backfill）仍屬 Plan 3。

- [ ] **Step 2: 選用真實煙霧測試（需使用者確認金鑰）**

Run（僅在 `.env` 有有效 `GEMINI_API_KEY`/`MAPS_API_KEY` 時，由使用者執行）: `uv run python -m mygmap.cli`
Expected: 印出 `enriched=<N> verified=<M>`；DB 中 `places.enriched_at` 開始有值、`closure_checks` 有列。**此步驟會呼叫真實付費/限速 API，非必要不自動跑。**

- [ ] **Step 3: Commit**

```bash
git add docs/postgres-pipeline.md
git commit -m "docs: 更新 PostgreSQL 管線說明（enrichment 與歇業驗證已上 DB）"
```

---

## Self-Review

**Spec coverage（對照設計文件 §5–§9、§16）：**
- §5/§16 M4 enrichment（`enrich.py`，重用 Gemini/Maps，`places` 取代 export_cache）→ Task 1（gapi 抽取）+ Task 2（api_cache）+ Task 3（enrich）✅
- §5/§9/§16 M5 歇業驗證（`verify.py` → `closure_checks`，UNCERTAIN 不快取）→ Task 4 ✅
- §6 資料流串接（ingest → enrich → verify → report）→ Task 5 ✅
- §8 報告「歇業狀態變化」有資料 → Task 4/5 讓 `closure_checks` 有列，Plan 1 的 `closure_changes` 查詢自動生效 ✅
- Plan 1 遺留：ingest rollback → Task 5 ✅
- §10 安全：金鑰不外印、無金鑰降級 → Task 5（cli 只讀 env、不印金鑰）✅
- §13 測試不打真實網路 → 全任務以注入假 callable / monkeypatch ✅
- **不涵蓋（Plan 3 / M6–M7）**：從 DB 產 `stores_data.js` + golden test、退役舊腳本、archive backfill、re-ingest 同 zip 防呆、closure_changes 的兩-import 真資料測試。gapi 與舊腳本的暫時重複也於 Plan 3 消除。

**Placeholder scan：** 新模組（cache/enrich/verify/cli/gapi factory）均給完整程式碼；gapi 主體為「自指定 file:line 移植並參數化」的精確指示（非 TBD）。

**Type consistency：** `classify(items)->list[dict{types,avg_spending,lat,lng,address}]` 於 Task 1/3 一致；`find_place(name,address)->dict{status,...}` 於 Task 1/4/5 一致；`enrich_pending(conn, classify, *, place_details, home_lat, home_lng, ...)` 於 Task 3 定義、Task 5 cli 呼叫（只傳 classify，其餘用預設）一致；`verify_import(conn, import_id, find_place, ...)` 於 Task 4 定義、Task 5 呼叫一致；`make_classifier`/`make_find_place` 產出的 callable 形狀符合 enrich/verify 期望。

**Scope check：** Plan 2 專注 enrichment + 歇業驗證上 DB（可獨立運作、可測試、報告即獲益）；stores_data.js 從 DB 產出與退役舊路徑留給 Plan 3。
