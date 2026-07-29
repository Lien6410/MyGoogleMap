# PostgreSQL 地點主體遷移（Plan 3：M6–M7 從 DB 產出 + backfill + 退役舊路徑）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 讓 PostgreSQL 成為抽籤資料的唯一來源：從 DB 產生 `stores_data.js`（保留 `lottery.html` 契約）與 CSV、補齊 enrichment 的營業時間/距離、支援 archive backfill，並把舊 CSV 來源路徑標記退役。

**Architecture:** 新增 `mygmap/export.py`（`active_stores` + `write_stores_js` + `write_stores_csv`，從最新匯入的 `places`/`list_memberships`/`closure_checks` 組出抽籤資料）。`cli.run` 末端產出 `stores_data.js`（+CSV）。`gapi` 增 `make_place_details`，`cli` 補住家定位並把 `place_details`/`home` 傳入 `enrich_pending`，使 `hours`/`distance_km` 有值。新增 `backfill.py` 由 `data/archive/` 回填較早匯入。舊 `export_to_sheets.py`/`verify_stores.py` 標記退役（不刪，保留 GDrive 上傳等）。

**Tech Stack:** Python 3.11+、`uv`、`psycopg[binary]`、`pytest`、PostgreSQL 17。沿用 Plan 1/2 的 `mygmap` 套件、`conn` fixture、注入假 API 的測試風格。

## Global Constraints

- **`stores_data.js` 契約（必須逐欄一致）**：檔案內容 `// 註解\nwindow.STORES_DATA = [...]（json，indent=2, ensure_ascii=False）;\n`。每個物件欄位與順序：`title, address, url, cuisine_type, source_list, visited, distance_km, avg_spending, note, hours`。`visited` 為字串 `"是"`/`"否"`；`cuisine_type` 未知→`"其他"`；`avg_spending` 未知→`0`；`distance_km` 未知→`null`；`hours` 為陣列或 `null`。
- **Active 定義**：在最新匯入有 `list_memberships`，且該匯入的 `closure_checks.status` **不在** `{CLOSED_PERMANENTLY, CLOSED}`（沿用既有教訓：只自動移除永久歇業；`CLOSED_TEMPORARILY`/`NOT_FOUND`/`UNCERTAIN`/無驗證 一律保留）。
- `visited = "是"` 若該店在此匯入任一 membership `is_visited=true`，否則 `"否"`。`source_list` = 此匯入所屬 `list_name` 去重排序後以 `, ` 合併。`note` = 第一個非空的 membership note。
- 測試不得打真實網路（注入假 API）。金鑰由 `.env` 讀、**絕不印**。
- 舊腳本**不刪除**（保留 Google Drive 上傳等獨有功能），只加退役註記；`gapi` 與舊腳本的函式重複本 Plan 仍暫留，完全移除列為未來選用清理。
- 主控台 cp950：Python stdout 無 emoji（`stores_data.js` 檔案內容可含中文/表情，屬檔案不屬 stdout）。Commit 訊息結尾 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

---

## File Structure

- `mygmap/export.py` — `active_stores` / `closed_stores` / `write_stores_js` / `write_stores_csv`。
- `mygmap/gapi.py` — 新增 `make_place_details(maps_api_key)` factory。
- `mygmap/cli.py` — enrich 傳入 `place_details`/home 座標；run 末端呼叫 export。
- `mygmap/backfill.py` — `backfill_archive(conn, archive_dir)`。
- tests：`test_export.py`、`test_gapi.py`（擴充）、`test_cli.py`（擴充）、`test_backfill.py`。
- `docs/postgres-pipeline.md`、`export_to_sheets.py`/`verify_stores.py`（退役註記）、`README.md`。

---

## Task 1: export.py — active_stores 與 write_stores_js（契約核心）

**Files:**
- Create: `mygmap/export.py`
- Test: `tests/test_export.py`

**Interfaces (Produces):**
- `mygmap.export.latest_import_id(conn) -> int|None`。
- `mygmap.export.active_stores(conn, import_id=None) -> list[dict]`（每個 dict 具契約 10 欄，依 title 排序）。
- `mygmap.export.write_stores_js(conn, path='data/output/stores_data.js', import_id=None) -> str|None`（回傳路徑；無匯入回 None）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_export.py`：

```python
import json

from mygmap.ingest import ingest_entries
from mygmap.enrich import enrich_pending
from mygmap.verify import verify_import
from mygmap import export


def _e(title, list_name, url='', visited=True, note=''):
    return {'title': title, 'list_name': list_name, 'url': url, 'address': '新竹市',
            'note': note, 'tags': '', 'is_visited': visited}


def _fake_classify(items):
    return [{'types': '日式', 'avg_spending': 250, 'lat': 24.8, 'lng': 120.97,
             'address': '新竹市光復路'} for _ in items]


def _seed(conn):
    iid = ingest_entries(conn, [
        _e('營業店', '台北牛肉麵', url='x/data=!1s0x1:0x1', note='紅燒'),
        _e('營業店', '想去的地點', url='x/data=!1s0x1:0x1'),      # same place, 2 lists
        _e('只想去店', '想去的地點', url='x/data=!1s0x2:0x2', visited=False),
        _e('歇業店', '台北牛肉麵', url='x/data=!1s0x3:0x3'),
    ], source_zip='t.zip')
    enrich_pending(conn, _fake_classify, home_lat=24.80, home_lng=120.97)

    def fake_find(name, address):
        status = 'CLOSED_PERMANENTLY' if name == '歇業店' else 'OPERATIONAL'
        return {'status': status, 'address': '', 'price_level': None, 'match': 'EXACT'}

    verify_import(conn, iid, fake_find)
    return iid


def test_active_stores_fields_and_rules(conn):
    _seed(conn)
    stores = {s['title']: s for s in export.active_stores(conn)}
    assert '歇業店' not in stores                      # CLOSED_PERMANENTLY excluded
    assert set(stores) == {'營業店', '只想去店'}
    a = stores['營業店']
    assert a['visited'] == '是'                         # in a non-想去 list
    assert a['source_list'] == '想去的地點, 台北牛肉麵'   # sorted, comma-joined
    assert a['note'] == '紅燒'                          # first non-empty note
    assert a['cuisine_type'] == '日式' and a['avg_spending'] == 250
    assert a['distance_km'] == 0.0
    assert stores['只想去店']['visited'] == '否'         # only in 想去的地點


def test_write_stores_js_matches_contract(conn):
    _seed(conn)
    path = export.write_stores_js(conn, path=str(__import__('pathlib').Path(
        conn.info.dbname and '.') / 'x') and 'data/output/_test_stores.js')
    text = open(path, encoding='utf-8').read()
    assert text.startswith('// ')
    assert 'window.STORES_DATA = ' in text
    body = text[text.index('['):text.rindex(']') + 1]
    data = json.loads(body)
    keys = list(data[0].keys())
    assert keys == ['title', 'address', 'url', 'cuisine_type', 'source_list',
                    'visited', 'distance_km', 'avg_spending', 'note', 'hours']
    import os
    os.remove(path)
```

> 注意：`write_stores_js` 的 `path` 測試請直接傳一個檔案路徑（例如 `str(tmp_path/'s.js')`），上面第二個測試用 `tmp_path` 更乾淨——實作測試時以 `tmp_path` fixture 傳入 `path=str(tmp_path/'stores.js')` 並斷言內容，勿在 repo 寫檔。

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_export.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.export'`）。

- [ ] **Step 3: 實作 export.py**

Create `mygmap/export.py`：

```python
import json
import os

_PERM_CLOSED = ('CLOSED_PERMANENTLY', 'CLOSED')
_FIELD_ORDER = ['title', 'address', 'url', 'cuisine_type', 'source_list',
                'visited', 'distance_km', 'avg_spending', 'note', 'hours']


def latest_import_id(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM imports ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return row[0] if row else None


def _perm_closed_keys(conn, import_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT place_key FROM closure_checks "
            "WHERE import_id=%s AND status IN %s",
            (import_id, _PERM_CLOSED),
        )
        return {r[0] for r in cur.fetchall()}


def active_stores(conn, import_id=None):
    if import_id is None:
        import_id = latest_import_id(conn)
    if import_id is None:
        return []
    closed = _perm_closed_keys(conn, import_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.place_key, p.title, p.address, p.url, p.cuisine_type,
                   p.avg_spending, p.distance_km, p.hours,
                   m.is_visited, m.list_name, m.note
            FROM list_memberships m JOIN places p ON p.place_key = m.place_key
            WHERE m.import_id = %s
            ORDER BY p.title, m.list_name
            """,
            (import_id,),
        )
        rows = cur.fetchall()

    grouped = {}
    for (pk, title, address, url, cuisine, avg, dist, hours,
         is_visited, list_name, note) in rows:
        if pk in closed:
            continue
        g = grouped.get(pk)
        if g is None:
            g = {'title': title, 'address': address or '', 'url': url or '',
                 'cuisine_type': cuisine or '其他',
                 'avg_spending': avg if avg is not None else 0,
                 'distance_km': dist, 'hours': hours,
                 '_visited': False, '_lists': set(), '_note': ''}
            grouped[pk] = g
        g['_visited'] = g['_visited'] or bool(is_visited)
        g['_lists'].add(list_name)
        if not g['_note'] and note:
            g['_note'] = note

    stores = []
    for g in grouped.values():
        stores.append({
            'title':        g['title'],
            'address':      g['address'],
            'url':          g['url'],
            'cuisine_type': g['cuisine_type'],
            'source_list':  ', '.join(sorted(g['_lists'])),
            'visited':      '是' if g['_visited'] else '否',
            'distance_km':  g['distance_km'],
            'avg_spending': g['avg_spending'],
            'note':         g['_note'],
            'hours':        g['hours'],
        })
    stores.sort(key=lambda s: s['title'])
    return stores


def write_stores_js(conn, path='data/output/stores_data.js', import_id=None):
    if latest_import_id(conn) is None:
        return None
    stores = active_stores(conn, import_id)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write("// 自動產生的店家資料檔，請勿手動修改。\n")
        f.write("window.STORES_DATA = ")
        json.dump(stores, f, ensure_ascii=False, indent=2)
        f.write(";\n")
    return path
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_export.py -v`
Expected: PASS（2 passed）。（實作時第二個測試改用 `tmp_path`，見 Step 1 注意事項。）

- [ ] **Step 5: Commit**

```bash
git add mygmap/export.py tests/test_export.py
git commit -m "feat: 從 DB 產生 stores_data.js（保留 window.STORES_DATA 契約）"
```

---

## Task 2: export.py — 從 DB 產生 CSV（active / closed）

**Files:**
- Modify: `mygmap/export.py`
- Test: `tests/test_export.py`（擴充）

**Interfaces (Produces):**
- `mygmap.export.closed_stores(conn, import_id=None) -> list[dict]`（永久歇業店家，含 `停業狀態`）。
- `mygmap.export.write_stores_csv(conn, active_path, closed_path, import_id=None) -> tuple[str, str]`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_export.py` 追加：

```python
import csv


def test_write_stores_csv_active_and_closed(conn, tmp_path):
    _seed(conn)
    ap = str(tmp_path / 'active.csv')
    cp = str(tmp_path / 'closed.csv')
    export.write_stores_csv(conn, ap, cp)
    with open(ap, encoding='utf-8-sig', newline='') as f:
        active = list(csv.DictReader(f))
    with open(cp, encoding='utf-8-sig', newline='') as f:
        closed = list(csv.DictReader(f))
    active_names = {r['店名'] for r in active}
    assert active_names == {'營業店', '只想去店'}
    assert active[0].__contains__('餐飲類型') and active[0].__contains__('是否曾去過')
    assert {r['店名'] for r in closed} == {'歇業店'}
    assert closed[0]['停業狀態'] == 'CLOSED_PERMANENTLY'
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_export.py::test_write_stores_csv_active_and_closed -v`
Expected: FAIL（`AttributeError: module 'mygmap.export' has no attribute 'write_stores_csv'`）。

- [ ] **Step 3: 實作 closed_stores + write_stores_csv（加到 export.py）**

在 `mygmap/export.py` 追加：

```python
import csv as _csv

_CSV_HEADER = ['店名', '地址', '網址', '餐飲類型', '來源清單',
               '是否曾去過', '距離住家(公里)', '人均消費預估(元)', '備註', '營業時間']


def closed_stores(conn, import_id=None):
    if import_id is None:
        import_id = latest_import_id(conn)
    if import_id is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT p.title, p.address, p.url, p.cuisine_type,
                   p.avg_spending, c.status
            FROM closure_checks c JOIN places p ON p.place_key = c.place_key
            WHERE c.import_id = %s AND c.status IN %s
            ORDER BY p.title
            """,
            (import_id, _PERM_CLOSED),
        )
        return [{'店名': t, '地址': a or '', '網址': u or '',
                 '餐飲類型': cu or '其他',
                 '人均消費預估(元)': av if av else '未知', '停業狀態': st}
                for (t, a, u, cu, av, st) in cur.fetchall()]


def _hours_text(hours):
    return '' if not hours else ';'.join(f"{h.get('d')}:{h.get('o')}-{h.get('c')}" for h in hours)


def write_stores_csv(conn, active_path, closed_path, import_id=None):
    os.makedirs(os.path.dirname(active_path) or '.', exist_ok=True)
    with open(active_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = _csv.writer(f)
        w.writerow(_CSV_HEADER)
        for s in active_stores(conn, import_id):
            w.writerow([s['title'], s['address'], s['url'], s['cuisine_type'],
                        s['source_list'], s['visited'],
                        s['distance_km'] if s['distance_km'] is not None else '未知',
                        s['avg_spending'] if s['avg_spending'] else '未知',
                        s['note'], _hours_text(s['hours'])])
    with open(closed_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = _csv.DictWriter(f, fieldnames=['店名', '地址', '網址', '餐飲類型',
                                           '人均消費預估(元)', '停業狀態'])
        w.writeheader()
        w.writerows(closed_stores(conn, import_id))
    return active_path, closed_path
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_export.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add mygmap/export.py tests/test_export.py
git commit -m "feat: 從 DB 產生 active/closed CSV"
```

---

## Task 3: enrich 補齊營業時間與住家距離（gapi factory + cli wiring）

**Files:**
- Modify: `mygmap/gapi.py`
- Modify: `mygmap/cli.py`
- Test: `tests/test_gapi.py`（擴充）、`tests/test_cli.py`（擴充）

**Interfaces (Produces):**
- `mygmap.gapi.make_place_details(maps_api_key) -> callable(cid_hex)->{"address","hours","hours_text"}`（無金鑰回傳空 dict `{"address":"","hours":None,"hours_text":""}`）。
- `cli.run` 在有 `maps_key` 時：以 `gapi.geocode(home_address, maps_key)` 取得 `home_lat/lng`，並把 `place_details=gapi.make_place_details(maps_key)`、`home_lat/home_lng` 傳入 `enrich_pending`。

- [ ] **Step 1: gapi factory 失敗測試**

在 `tests/test_gapi.py` 追加：

```python
from mygmap.gapi import make_place_details


def test_make_place_details_no_key_returns_empty():
    pd = make_place_details('')
    assert pd('0x1:0x2') == {'address': '', 'hours': None, 'hours_text': ''}
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_gapi.py::test_make_place_details_no_key_returns_empty -v`
Expected: FAIL（`ImportError` / `AttributeError`）。

- [ ] **Step 3: 實作 make_place_details（加到 gapi.py 末端）**

```python
def make_place_details(maps_api_key):
    """回傳 enrich_pending 需要的 place_details(cid)->dict；無金鑰回空結果。"""
    def _place_details(cid_hex):
        if not maps_api_key:
            return {'address': '', 'hours': None, 'hours_text': ''}
        return place_details(cid_hex, maps_api_key)
    return _place_details
```

- [ ] **Step 4: cli wiring 失敗測試**

在 `tests/test_cli.py` 追加（monkeypatch 注入金鑰與捕捉 enrich 參數，不打網路）：

```python
def test_run_passes_place_details_and_home_to_enrich(conn, tmp_path, monkeypatch):
    import mygmap.cli as climod
    captured = {}

    def fake_enrich(conn_, classify, *, place_details=None, home_lat=None,
                    home_lng=None, mark_enriched=True, **kw):
        captured['has_place_details'] = place_details is not None
        captured['home_lat'] = home_lat
        return 0

    monkeypatch.setattr(climod, 'enrich_pending', fake_enrich)
    monkeypatch.setattr(climod, 'verify_import', lambda *a, **k: 0)
    monkeypatch.setattr(climod.config, 'load_env',
                        lambda *a, **k: {'MAPS_API_KEY': 'x', 'HOME_ADDRESS': '新竹'})
    monkeypatch.setattr(climod.gapi, 'geocode', lambda addr, key: (24.8, 120.97))

    takeout_dir = _make_zip(tmp_path)
    climod.run(conn, takeout_dir=takeout_dir, out_dir=str(tmp_path / 'out'))
    assert captured['has_place_details'] is True
    assert captured['home_lat'] == 24.8
```

- [ ] **Step 5: 執行確認失敗**

Run: `uv run pytest tests/test_cli.py::test_run_passes_place_details_and_home_to_enrich -v`
Expected: FAIL（目前 cli 未傳 place_details/home）。

- [ ] **Step 6: 更新 cli.run 的 enrich 呼叫**

在 `mygmap/cli.py` 的 enrich 段落，改為（維持無金鑰降級）：

```python
    env = config.load_env()
    api_key = env.get('GEMINI_API_KEY', '')
    maps_key = env.get('MAPS_API_KEY', '') or api_key
    model = env.get('GEMINI_MODEL', 'gemini-2.5-flash')
    home = env.get('HOME_ADDRESS', '')

    home_lat = home_lng = None
    place_details = None
    if maps_key:
        if home:
            home_lat, home_lng = gapi.geocode(home, maps_key)
        place_details = gapi.make_place_details(maps_key)

    classify = gapi.make_classifier(api_key, model, home_address=home)
    enriched = enrich_pending(conn, classify, place_details=place_details,
                              home_lat=home_lat, home_lng=home_lng,
                              mark_enriched=bool(api_key))
```

- [ ] **Step 7: 執行全套確認通過**

Run: `uv run pytest -v`
Expected: 全部 PASS，0 skipped。

- [ ] **Step 8: Commit**

```bash
git add mygmap/gapi.py mygmap/cli.py tests/test_gapi.py tests/test_cli.py
git commit -m "feat: enrich 接上營業時間(place_details)與住家距離"
```

---

## Task 4: cli 末端從 DB 產出 stores_data.js（+CSV）

**Files:**
- Modify: `mygmap/cli.py`
- Test: `tests/test_cli.py`（擴充）

**Interfaces:**
- `cli.run` 在 report 之後呼叫 `export.write_stores_js(conn, out_dir/stores_data.js)` 與 `export.write_stores_csv(...)`，回傳 dict 增 `stores_js` 路徑。`main` 印出該路徑。

- [ ] **Step 1: 失敗測試**

在 `tests/test_cli.py` 追加：

```python
def test_run_writes_stores_js(conn, tmp_path, monkeypatch):
    import mygmap.cli as climod
    monkeypatch.setattr(climod, 'enrich_pending', lambda *a, **k: 0)
    monkeypatch.setattr(climod, 'verify_import', lambda *a, **k: 0)
    monkeypatch.setattr(climod.config, 'load_env', lambda *a, **k: {})
    out_dir = str(tmp_path / 'out')
    result = climod.run(conn, takeout_dir=_make_zip(tmp_path), out_dir=out_dir)
    import os
    assert result['stores_js'] is not None
    assert os.path.exists(result['stores_js'])
    assert os.path.basename(result['stores_js']) == 'stores_data.js'
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_cli.py::test_run_writes_stores_js -v`
Expected: FAIL（result 無 `stores_js`）。

- [ ] **Step 3: cli.run 加 export 段**

在 `mygmap/cli.py`：頂部 import 增 `from . import export`；`run` 於 `report_path = report.write_report(...)` 之後、`return` 之前加：

```python
    stores_js = export.write_stores_js(conn, path=os.path.join(out_dir, 'stores_data.js'))
    export.write_stores_csv(
        conn,
        os.path.join(out_dir, 'MyGoogleMap_Stores_active.csv'),
        os.path.join(out_dir, 'MyGoogleMap_Stores_closed.csv'),
    )
```

並在回傳 dict 加 `'stores_js': stores_js`；無-zip 早退 dict 也加 `'stores_js': None`。`main` 於成功分支加 `print(f"[OK] stores_data.js: {result['stores_js']}")`。

- [ ] **Step 4: 執行全套確認通過**

Run: `uv run pytest -v`
Expected: 全部 PASS，0 skipped。

- [ ] **Step 5: Commit**

```bash
git add mygmap/cli.py tests/test_cli.py
git commit -m "feat: cli 末端從 DB 產出 stores_data.js 與 CSV"
```

---

## Task 5: 從 data/archive 回填較早匯入

**Files:**
- Create: `mygmap/backfill.py`
- Test: `tests/test_backfill.py`

**Interfaces (Produces):**
- `mygmap.backfill.find_saved_dirs(archive_dir) -> list[str]`（archive 內所有名為 `已儲存` 的資料夾路徑）。
- `mygmap.backfill.backfill_archive(conn, archive_dir) -> list[int]`（依路徑排序，逐一 `read_all_from_dir` → `ingest_entries`，回傳 import_id 清單）。

- [ ] **Step 1: 失敗測試**

Create `tests/test_backfill.py`：

```python
import os

from mygmap.backfill import backfill_archive

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'saved')


def test_backfill_archive_ingests_each_saved_dir(conn, tmp_path):
    # 造兩個含「已儲存」的 archive 快照
    for day in ('2026-06-20', '2026-06-21'):
        d = tmp_path / day / 'Takeout' / '已儲存'
        d.mkdir(parents=True)
        for fn in os.listdir(FIX):
            (d / fn).write_bytes(open(os.path.join(FIX, fn), 'rb').read())
    ids = backfill_archive(conn, str(tmp_path))
    assert len(ids) == 2
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM imports")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(DISTINCT place_key) FROM places")
        assert cur.fetchone()[0] >= 1
```

- [ ] **Step 2: 執行確認失敗**

Run: `uv run pytest tests/test_backfill.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.backfill'`）。

- [ ] **Step 3: 實作 backfill.py**

Create `mygmap/backfill.py`：

```python
import os

from .ingest import ingest_entries
from .takeout import read_all_from_dir


def find_saved_dirs(archive_dir):
    found = []
    for root, dirs, _files in os.walk(archive_dir):
        if os.path.basename(root) == '已儲存':
            found.append(root)
    return sorted(found)


def backfill_archive(conn, archive_dir):
    ids = []
    for saved_dir in find_saved_dirs(archive_dir):
        entries = read_all_from_dir(saved_dir)
        if not entries:
            continue
        ids.append(ingest_entries(conn, entries, source_zip=f"archive:{saved_dir}"))
    return ids
```

- [ ] **Step 4: 執行確認通過**

Run: `uv run pytest tests/test_backfill.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 5: Commit**

```bash
git add mygmap/backfill.py tests/test_backfill.py
git commit -m "feat: 從 data/archive 回填較早匯入（backfill）"
```

---

## Task 6: 文件更新與舊腳本退役註記

**Files:**
- Modify: `docs/postgres-pipeline.md`
- Modify: `export_to_sheets.py`、`verify_stores.py`（檔頭退役註記）
- Modify: `README.md`

**Interfaces:** 使用說明反映 DB 產出 `stores_data.js`；舊腳本標記退役。

- [ ] **Step 1: 更新 docs**

Modify `docs/postgres-pipeline.md`：把「尚未涵蓋（Plan 3）」段落中的 stores_data.js/backfill 移到「已支援」；新增說明：`uv run python -m mygmap.cli` 現在會產出 `data/output/stores_data.js`（+active/closed CSV），gh-pages 部署沿用既有 `git add -f data/output/stores_data.js` 流程但**來源改為 DB**；`backfill` 用法（`python -c "from mygmap import db,backfill; ..."` 或簡短說明）。

- [ ] **Step 2: 舊腳本退役註記**

在 `export_to_sheets.py` 與 `verify_stores.py` 檔頭 docstring 最前面各加一段：

```
# [退役中] 抽籤資料主體已改為 PostgreSQL 管線（mygmap 套件，見 docs/postgres-pipeline.md）。
# 本腳本保留供：Google Drive 上傳、以及不使用 DB 的手動 CSV 流程；
# stores_data.js 請改由 `uv run python -m mygmap.cli` 從 DB 產生。
```

（僅加註解，不改動任何程式邏輯。）

- [ ] **Step 3: 更新 README**

Modify `README.md`：PostgreSQL 段落補一句「`stores_data.js` 現由 DB 產出（Plan 3 完成）」，並指向 `docs/postgres-pipeline.md`。

- [ ] **Step 4: 全套測試 + Commit**

Run: `uv run pytest -q`
Expected: 全部 PASS。

```bash
git add docs/postgres-pipeline.md export_to_sheets.py verify_stores.py README.md
git commit -m "docs: Plan 3 完成，stores_data.js 改由 DB 產出，舊腳本標記退役"
```

---

## Self-Review

**Spec coverage（設計文件 §7、§11、§16 M6–M7）：**
- §7 從 DB 產 `stores_data.js`、保留 `window.STORES_DATA` 契約、active 定義、source_list 合併 → Task 1 ✅（golden/結構測試鎖欄位順序）
- §7 CSV 產出 → Task 2 ✅
- enrichment 完整化（hours/distance）→ Task 3 ✅（補 Plan 2 未接線的部分）
- §6 資料流末端接 export → Task 4 ✅
- §11 archive backfill → Task 5 ✅
- 退役舊 CSV 來源路徑 → Task 6（deprecate 註記；完全刪除/移除 gapi 重複列為未來選用）✅
- **未涵蓋（選用未來清理）**：完全刪除 `export_to_sheets.py`/`verify_stores.py` 並消除 `gapi.py` 重複、把 `hours_normalize` 移入套件、「同一 zip 不重複匯入」防呆。

**Placeholder scan：** 各新模組給完整程式碼；Task 1 第二測試已註記改用 `tmp_path`（實作時據此）。

**Type consistency：** `active_stores`/`closed_stores`/`write_stores_js`/`write_stores_csv` 於 Task 1/2 定義、Task 4 cli 使用一致；`make_place_details(maps_api_key)->callable(cid)->{address,hours,hours_text}` 於 Task 3 定義、cli 傳入 `enrich_pending(place_details=...)`（Plan 2 Task 3 既有簽名）一致；`backfill_archive(conn, archive_dir)` 於 Task 5 定義。契約 10 欄順序在 Task 1 實作與測試中一致。

**Scope check：** Plan 3 交付「DB 產出抽籤資料 + 完整 enrichment + backfill + 退役註記」，可獨立運作、可測試；完全刪除舊腳本屬低價值高風險，列為選用未來清理。
