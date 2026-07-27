# PostgreSQL 地點變化追蹤（Plan 1：M1–M3 核心）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 PostgreSQL schema、把最新 Takeout 匯入成一份快照，並產生「本次 vs 上次」的新增/消失/清單變化報告。

**Architecture:** 新增 `mygmap/` Python 套件，以 psycopg 3 連本機 `mygooglemap`。每次匯入寫入 `imports` + `places`（維度）+ `list_memberships`（每次快照）。差異以參數化 SQL 計算，輸出 Markdown/CSV 報告。enrichment、歇業驗證、從 DB 匯出 `stores_data.js` 屬 Plan 2，本計畫不含。

**Tech Stack:** Python 3.11+、`uv`、`psycopg[binary]`（psycopg 3）、`pytest`、PostgreSQL 17（本機 `localhost:5432`，DB `mygooglemap`，role `mygmap_app`）。

## Global Constraints

- Python：`requires-python >= 3.11`（不變）。
- DB 連線只走 `localhost`；連線參數由 `.env` 的 `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` 提供。
- **安全：密碼永不寫入 log / stdout / repr**；日誌僅呈現 host/db/user。不得在程式中硬編任何密碼或 API 金鑰。
- 主控台為 cp950：所有 Python 輸出**不得含 emoji**；報告檔內容用 UTF-8 寫檔可含表情符號。
- `place_key`：有 Google CID（`!1s0x…:0x…`）用 CID；否則 `name:` + 正規化店名 `|` + 正規化地址。
- 清單 `圖片` 一律排除（收藏的圖片/迷因，非店家）。
- 唯一「未去過」清單為 `想去的地點`；其餘清單 `is_visited = true`。
- 測試以臨時 schema `mygmap_test` 隔離，跑在既有 `mygooglemap` DB 內；若 `.env` 無 `PGDATABASE` 則 skip DB 測試。
- 每個 commit 訊息以 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` 結尾。

---

## File Structure

- `pyproject.toml` — 加入 `psycopg[binary]`（runtime）、`pytest`（dev）。
- `mygmap/__init__.py` — 套件標記。
- `mygmap/config.py` — 讀 `.env`、`DbConfig`（conninfo 建構、密碼遮蔽）。
- `mygmap/db.py` — psycopg 連線、DDL、`init_schema()`。
- `mygmap/places.py` — `extract_cid`、`place_key` 推導。
- `mygmap/takeout.py` — 找最新 zip、解壓、讀 `已儲存/*.csv` → entries。
- `mygmap/ingest.py` — 建 import、upsert places、寫 memberships。
- `mygmap/report.py` — 差異查詢 + Markdown/CSV 報告輸出。
- `mygmap/cli.py` — Plan 1 進入點：init → ingest → report。
- `tests/conftest.py` — pytest fixtures（臨時 schema、DB 連線）。
- `tests/test_config.py`、`tests/test_places.py`、`tests/test_takeout.py`、`tests/test_db.py`、`tests/test_ingest.py`、`tests/test_report.py` — 單元/整合測試。
- `tests/fixtures/saved/*.csv` — 迷你 Takeout 清單樣本。

---

## Task 1: 專案骨架、相依套件、DB 設定

**Files:**
- Modify: `pyproject.toml`
- Create: `mygmap/__init__.py`
- Create: `mygmap/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 無。
- Produces: `mygmap.config.load_env(path='.env') -> dict`；`mygmap.config.DbConfig`，含 `.from_env(env=None, dbname_key='PGDATABASE') -> DbConfig`、`.conninfo() -> str`、`.safe_dict() -> dict`、`__repr__` 遮蔽密碼。

- [ ] **Step 1: 加入相依套件**

修改 `pyproject.toml`：`dependencies` 追加 `psycopg[binary]`，`dev` 追加 `pytest`。

```toml
dependencies = [
    "google-api-python-client>=2.196.0",
    "google-auth-oauthlib>=1.4.0",
    "psycopg[binary]>=3.2",
]

[dependency-groups]
dev = [
    "isort>=8.0.1",
    "pytest>=8.0",
]
```

Run: `uv sync`
Expected: 安裝 `psycopg`、`pytest` 成功。

- [ ] **Step 2: 建立套件標記**

Create `mygmap/__init__.py`：

```python
"""MyGoogleMap PostgreSQL 資料管線套件。"""
```

- [ ] **Step 3: 寫失敗測試**

Create `tests/test_config.py`：

```python
from mygmap.config import DbConfig


def test_from_env_reads_pg_vars():
    env = {
        'PGHOST': 'localhost', 'PGPORT': '5432',
        'PGDATABASE': 'mygooglemap', 'PGUSER': 'mygmap_app',
        'PGPASSWORD': 's3cret',
    }
    cfg = DbConfig.from_env(env=env)
    assert cfg.host == 'localhost'
    assert cfg.dbname == 'mygooglemap'
    assert cfg.user == 'mygmap_app'


def test_conninfo_contains_password_but_repr_hides_it():
    cfg = DbConfig.from_env(env={'PGDATABASE': 'd', 'PGUSER': 'u', 'PGPASSWORD': 's3cret'})
    assert 'password=s3cret' in cfg.conninfo()
    assert 's3cret' not in repr(cfg)
    assert 's3cret' not in str(cfg.safe_dict())
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.config'`）。

- [ ] **Step 5: 實作 config.py**

Create `mygmap/config.py`：

```python
import os


def load_env(path='.env'):
    env = {}
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class DbConfig:
    def __init__(self, host, port, dbname, user, password):
        self.host = host
        self.port = port
        self.dbname = dbname
        self.user = user
        self._password = password

    @classmethod
    def from_env(cls, env=None, dbname_key='PGDATABASE'):
        if env is None:
            env = {**load_env(), **os.environ}
        return cls(
            host=env.get('PGHOST', 'localhost'),
            port=env.get('PGPORT', '5432'),
            dbname=env.get(dbname_key, ''),
            user=env.get('PGUSER', ''),
            password=env.get('PGPASSWORD', ''),
        )

    def conninfo(self):
        return (f"host={self.host} port={self.port} dbname={self.dbname} "
                f"user={self.user} password={self._password}")

    def safe_dict(self):
        return {'host': self.host, 'port': self.port,
                'dbname': self.dbname, 'user': self.user}

    def __repr__(self):
        return f"DbConfig({self.safe_dict()}, password=***)"
```

- [ ] **Step 6: 執行測試確認通過**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock mygmap/__init__.py mygmap/config.py tests/test_config.py
git commit -m "feat: 新增 mygmap 套件骨架與 DB 連線設定（密碼遮蔽）"
```

---

## Task 2: place_key 推導

**Files:**
- Create: `mygmap/places.py`
- Test: `tests/test_places.py`

**Interfaces:**
- Consumes: 無。
- Produces: `mygmap.places.extract_cid(url) -> str|None`；`mygmap.places.place_key(url, title, address) -> str`。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_places.py`：

```python
from mygmap.places import extract_cid, place_key


def test_extract_cid_from_maps_url():
    url = ("https://www.google.com/maps/place/x/data=!4m2!3m1!1s"
           "0x3442a90e656a081f:0x713c3942e872dca2")
    assert extract_cid(url) == "0x3442a90e656a081f:0x713c3942e872dca2"


def test_extract_cid_none_when_absent():
    assert extract_cid("https://example.com") is None
    assert extract_cid("") is None


def test_place_key_uses_cid_when_present():
    url = "x/data=!1s0x1a:0x2b"
    assert place_key(url, "小吳牛肉麵", "台北市") == "0x1a:0x2b"


def test_place_key_falls_back_to_normalized_name_and_address():
    key = place_key("", "小吳 牛肉麵（總店）", "台北市 大安區")
    assert key == "name:小吳牛肉麵總店|台北市大安區"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_places.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.places'`）。

- [ ] **Step 3: 實作 places.py**

Create `mygmap/places.py`：

```python
import re

_CID_RE = re.compile(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', re.IGNORECASE)
_PUNCT_RE = re.compile(r'[（）()\s/,、\-．·　【】『』「」{}｛｝\[\]]')


def extract_cid(url):
    if not url:
        return None
    m = _CID_RE.search(url)
    return m.group(1) if m else None


def _normalize(s):
    return _PUNCT_RE.sub('', s or '')


def place_key(url, title, address):
    cid = extract_cid(url)
    if cid:
        return cid
    return f"name:{_normalize(title)}|{_normalize(address)}"
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_places.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: Commit**

```bash
git add mygmap/places.py tests/test_places.py
git commit -m "feat: 新增 place_key 推導（CID 優先、正規化名稱後備）"
```

---

## Task 3: DB schema 與 init_schema（含測試 fixtures）

**Files:**
- Create: `mygmap/db.py`
- Create: `tests/conftest.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `mygmap.config.DbConfig`。
- Produces: `mygmap.db.connect(config=None, dbname_key='PGDATABASE') -> psycopg.Connection`；`mygmap.db.init_schema(conn) -> None`（冪等）；`mygmap.db.SCHEMA_VERSION`。
- fixture `conn`：已建好 schema、search_path 指向臨時 `mygmap_test` 的連線；DB 不可用時 skip。

- [ ] **Step 1: 寫測試 fixtures**

Create `tests/conftest.py`：

```python
import psycopg
import pytest

from mygmap import db
from mygmap.config import DbConfig

TEST_SCHEMA = "mygmap_test"


@pytest.fixture()
def conn():
    cfg = DbConfig.from_env()
    if not cfg.dbname:
        pytest.skip("PGDATABASE 未設定，略過 DB 測試")
    try:
        admin = psycopg.connect(cfg.conninfo())
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"無法連線 PostgreSQL：{e}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")

    c = psycopg.connect(cfg.conninfo())
    with c.cursor() as cur:
        cur.execute(f"SET search_path TO {TEST_SCHEMA}")
    db.init_schema(c)

    yield c

    c.close()
    with admin.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
    admin.close()
```

- [ ] **Step 2: 寫失敗測試**

Create `tests/test_db.py`：

```python
def test_init_schema_creates_all_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'mygmap_test'
        """)
        tables = {r[0] for r in cur.fetchall()}
    assert {'imports', 'places', 'list_memberships',
            'closure_checks', 'api_cache', 'schema_meta'} <= tables


def test_init_schema_is_idempotent(conn):
    from mygmap import db
    db.init_schema(conn)  # 再跑一次不應報錯
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_meta")
        assert cur.fetchone()[0] == 1
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.db'`）。

- [ ] **Step 4: 實作 db.py**

Create `mygmap/db.py`：

```python
import psycopg

from .config import DbConfig

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS imports (
    id                   BIGSERIAL PRIMARY KEY,
    source_zip           TEXT,
    takeout_exported_at  TIMESTAMPTZ,
    imported_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    place_count          INTEGER,
    notes                TEXT
);

CREATE TABLE IF NOT EXISTS places (
    place_key            TEXT PRIMARY KEY,
    cid                  TEXT,
    title                TEXT NOT NULL,
    address              TEXT,
    url                  TEXT,
    lat                  DOUBLE PRECISION,
    lng                  DOUBLE PRECISION,
    cuisine_type         TEXT,
    avg_spending         INTEGER,
    hours                JSONB,
    hours_text           TEXT,
    distance_km          DOUBLE PRECISION,
    first_seen_import_id BIGINT REFERENCES imports(id),
    last_seen_import_id  BIGINT REFERENCES imports(id),
    enriched_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS list_memberships (
    id          BIGSERIAL PRIMARY KEY,
    import_id   BIGINT  NOT NULL REFERENCES imports(id),
    place_key   TEXT    NOT NULL REFERENCES places(place_key),
    list_name   TEXT    NOT NULL,
    is_visited  BOOLEAN NOT NULL,
    note        TEXT,
    tags        TEXT,
    raw_title   TEXT,
    UNIQUE (import_id, place_key, list_name)
);

CREATE TABLE IF NOT EXISTS closure_checks (
    id          BIGSERIAL PRIMARY KEY,
    import_id   BIGINT  NOT NULL REFERENCES imports(id),
    place_key   TEXT    NOT NULL REFERENCES places(place_key),
    status      TEXT    NOT NULL,
    is_closed   BOOLEAN NOT NULL,
    source      TEXT,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (import_id, place_key)
);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key   TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS schema_meta (
    version     INTEGER NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memberships_import ON list_memberships(import_id);
CREATE INDEX IF NOT EXISTS idx_memberships_place  ON list_memberships(place_key);
CREATE INDEX IF NOT EXISTS idx_closure_import     ON closure_checks(import_id);
CREATE INDEX IF NOT EXISTS idx_places_cid         ON places(cid);
"""


def connect(config=None, dbname_key='PGDATABASE'):
    config = config or DbConfig.from_env(dbname_key=dbname_key)
    return psycopg.connect(config.conninfo())


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("SELECT version FROM schema_meta ORDER BY version DESC LIMIT 1")
        if cur.fetchone() is None:
            cur.execute("INSERT INTO schema_meta (version) VALUES (%s)",
                        (SCHEMA_VERSION,))
    conn.commit()
```

- [ ] **Step 5: 執行測試確認通過**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS（2 passed；若本機 DB 未跑則 skipped）。

- [ ] **Step 6: Commit**

```bash
git add mygmap/db.py tests/conftest.py tests/test_db.py
git commit -m "feat: 新增 PostgreSQL schema 與冪等 init_schema、測試 fixtures"
```

---

## Task 4: Takeout 讀取（找最新 zip、解壓、讀清單）

**Files:**
- Create: `mygmap/takeout.py`
- Create: `tests/fixtures/saved/台北牛肉麵.csv`
- Create: `tests/fixtures/saved/想去的地點.csv`
- Create: `tests/fixtures/saved/圖片.csv`
- Test: `tests/test_takeout.py`

**Interfaces:**
- Consumes: 無。
- Produces：
  - `mygmap.takeout.read_all_from_dir(saved_dir) -> list[dict]`，每個 dict 含鍵 `title, note, url, address, tags, list_name, is_visited`。
  - `mygmap.takeout.find_latest_zip(takeout_dir='data/takeout') -> str|None`。
  - `mygmap.takeout.extract_and_read(zip_path, workdir=None) -> list[dict]`。
  - `mygmap.takeout.parse_export_time(zip_name) -> datetime|None`。
  - 常數 `EXCLUDE_LISTS = {'圖片'}`、`UNVISITED_LIST_NAME = '想去的地點'`。

- [ ] **Step 1: 建立測試樣本 CSV**

Create `tests/fixtures/saved/台北牛肉麵.csv`：

```csv
標題,筆記,網址,標籤,留言
小吳牛肉麵,,https://www.google.com/maps/place/x/data=!1s0x1a:0x2b,,
牛耳精緻麵館,紅燒,https://www.google.com/maps/place/y/data=!1s0x3c:0x4d,好吃,
```

Create `tests/fixtures/saved/想去的地點.csv`：

```csv
標題,筆記,網址,標籤,留言
小吳牛肉麵,,https://www.google.com/maps/place/x/data=!1s0x1a:0x2b,,
阿發滷味,,,,
```

Create `tests/fixtures/saved/圖片.csv`：

```csv
標題,筆記,網址,標籤,留言
某張迷因圖,,https://example.com/meme,,
```

- [ ] **Step 2: 寫失敗測試**

Create `tests/test_takeout.py`：

```python
import os

from mygmap.takeout import read_all_from_dir, parse_export_time

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'saved')


def test_read_all_excludes_image_list_and_sets_visited():
    entries = read_all_from_dir(FIX)
    lists = {e['list_name'] for e in entries}
    assert '圖片' not in lists                      # 排除圖片清單
    # 想去的地點 → 未去過；其餘 → 去過
    by_title = {(e['title'], e['list_name']): e for e in entries}
    assert by_title[('阿發滷味', '想去的地點')]['is_visited'] is False
    assert by_title[('牛耳精緻麵館', '台北牛肉麵')]['is_visited'] is True


def test_read_all_captures_note_and_tags():
    entries = read_all_from_dir(FIX)
    niu = next(e for e in entries if e['title'] == '牛耳精緻麵館')
    assert niu['note'] == '紅燒'
    assert niu['tags'] == '好吃'
    assert niu['url'].endswith('!1s0x3c:0x4d')


def test_parse_export_time_from_zip_name():
    dt = parse_export_time('takeout-20260524T120207Z-3-001.zip')
    assert dt is not None
    assert dt.year == 2026 and dt.month == 5 and dt.day == 24


def test_parse_export_time_none_on_unparseable():
    assert parse_export_time('random.zip') is None
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `uv run pytest tests/test_takeout.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.takeout'`）。

- [ ] **Step 4: 實作 takeout.py**

Create `mygmap/takeout.py`：

```python
import csv
import glob
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone

EXCLUDE_LISTS = {'圖片'}
UNVISITED_LIST_NAME = '想去的地點'

_ZIP_TS_RE = re.compile(r'(\d{8})T(\d{6})Z')


def find_latest_zip(takeout_dir='data/takeout'):
    zips = glob.glob(os.path.join(takeout_dir, '*.zip'))
    if not zips:
        return None
    return max(zips, key=os.path.getmtime)


def parse_export_time(zip_name):
    m = _ZIP_TS_RE.search(zip_name or '')
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S').replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _detect_headers(header_row):
    mapping = {'title': None, 'note': None, 'url': None, 'address': None, 'tags': None}
    for i, col in enumerate(header_row):
        c = col.strip().lower()
        if c in ('title', '標題', '名稱', 'name'):
            mapping['title'] = i
        elif c in ('note', '備註', '說明', '備忘錄', 'notes', '筆記'):
            mapping['note'] = i
        elif c in ('url', '網址', '連結', 'link'):
            mapping['url'] = i
        elif c in ('address', '地址'):
            mapping['address'] = i
        elif c in ('標籤', 'tags'):
            mapping['tags'] = i
    if mapping['title'] is None:
        mapping['title'] = 0
    return mapping


def read_saved_csv(path, list_name):
    entries = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return entries
        m = _detect_headers(headers)

        def cell(row, key):
            i = m[key]
            return row[i].strip() if i is not None and i < len(row) else ''

        for row in reader:
            if not row:
                continue
            title = cell(row, 'title')
            if not title:
                continue
            entries.append({
                'title': title,
                'note': cell(row, 'note'),
                'url': cell(row, 'url'),
                'address': cell(row, 'address'),
                'tags': cell(row, 'tags'),
                'list_name': list_name,
            })
    return entries


def read_all_from_dir(saved_dir):
    entries = []
    for fn in sorted(os.listdir(saved_dir)):
        if not fn.lower().endswith('.csv'):
            continue
        list_name = fn[:-4]
        if list_name in EXCLUDE_LISTS:
            continue
        for e in read_saved_csv(os.path.join(saved_dir, fn), list_name):
            e['is_visited'] = (list_name != UNVISITED_LIST_NAME)
            entries.append(e)
    return entries


def extract_and_read(zip_path, workdir=None):
    workdir = workdir or tempfile.mkdtemp(prefix='takeout_')
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(workdir)
    for root, _dirs, _files in os.walk(workdir):
        if os.path.basename(root) == '已儲存':
            return read_all_from_dir(root)
    return []
```

- [ ] **Step 5: 執行測試確認通過**

Run: `uv run pytest tests/test_takeout.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 6: Commit**

```bash
git add mygmap/takeout.py tests/test_takeout.py tests/fixtures/
git commit -m "feat: 新增 Takeout 讀取（最新 zip、解壓、清單解析、排除圖片）"
```

---

## Task 5: Ingest（建 import、upsert places、寫 memberships）

**Files:**
- Create: `mygmap/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `mygmap.places.place_key`、`mygmap.places.extract_cid`；Task 3 的 schema。
- Produces: `mygmap.ingest.ingest_entries(conn, entries, source_zip=None, takeout_exported_at=None) -> int`（回傳 `import_id`）。`entries` 為 Task 4 產出的 dict list。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_ingest.py`：

```python
from mygmap.ingest import ingest_entries


def _entry(title, list_name, url='', address='', note='', tags='', visited=True):
    return {'title': title, 'list_name': list_name, 'url': url,
            'address': address, 'note': note, 'tags': tags, 'is_visited': visited}


def test_ingest_creates_import_places_and_memberships(conn):
    entries = [
        _entry('小吳牛肉麵', '台北牛肉麵', url='x/data=!1s0x1a:0x2b'),
        _entry('小吳牛肉麵', '想去的地點', url='x/data=!1s0x1a:0x2b', visited=False),
        _entry('阿發滷味', '想去的地點', address='新竹市', visited=False),
    ]
    import_id = ingest_entries(conn, entries, source_zip='t.zip')

    with conn.cursor() as cur:
        cur.execute("SELECT place_count FROM imports WHERE id=%s", (import_id,))
        assert cur.fetchone()[0] == 2                      # 兩個不重複地點
        cur.execute("SELECT count(*) FROM places")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM list_memberships WHERE import_id=%s", (import_id,))
        assert cur.fetchone()[0] == 3                      # 三筆清單歸屬


def test_ingest_membership_unique_dedup(conn):
    e = _entry('小吳牛肉麵', '台北牛肉麵', url='x/data=!1s0x1a:0x2b')
    import_id = ingest_entries(conn, [e, dict(e)], source_zip='t.zip')
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM list_memberships WHERE import_id=%s", (import_id,))
        assert cur.fetchone()[0] == 1                      # 同 import 同店同清單去重


def test_ingest_second_import_updates_last_seen(conn):
    e = _entry('小吳牛肉麵', '台北牛肉麵', url='x/data=!1s0x1a:0x2b')
    ingest_entries(conn, [e], source_zip='t1.zip')
    second = ingest_entries(conn, [e], source_zip='t2.zip')
    with conn.cursor() as cur:
        cur.execute("SELECT first_seen_import_id, last_seen_import_id FROM places")
        first_seen, last_seen = cur.fetchone()
        assert first_seen != last_seen
        assert last_seen == second
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.ingest'`）。

- [ ] **Step 3: 實作 ingest.py**

Create `mygmap/ingest.py`：

```python
from .places import extract_cid, place_key


def ingest_entries(conn, entries, source_zip=None, takeout_exported_at=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO imports (source_zip, takeout_exported_at, place_count) "
            "VALUES (%s, %s, 0) RETURNING id",
            (source_zip, takeout_exported_at),
        )
        import_id = cur.fetchone()[0]

        # 以 place_key 去重（同店可出現在多清單）
        unique = {}
        for e in entries:
            pk = place_key(e.get('url', ''), e['title'], e.get('address', ''))
            e['_pk'] = pk
            unique.setdefault(pk, e)

        for pk, e in unique.items():
            cur.execute(
                """
                INSERT INTO places (place_key, cid, title, address, url,
                                    first_seen_import_id, last_seen_import_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (place_key) DO UPDATE SET
                    title   = EXCLUDED.title,
                    address = COALESCE(NULLIF(EXCLUDED.address, ''), places.address),
                    url     = COALESCE(NULLIF(EXCLUDED.url, ''), places.url),
                    last_seen_import_id = EXCLUDED.last_seen_import_id,
                    updated_at = now()
                """,
                (pk, extract_cid(e.get('url', '')), e['title'],
                 e.get('address', ''), e.get('url', ''), import_id, import_id),
            )

        for e in entries:
            cur.execute(
                """
                INSERT INTO list_memberships
                    (import_id, place_key, list_name, is_visited, note, tags, raw_title)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (import_id, place_key, list_name) DO NOTHING
                """,
                (import_id, e['_pk'], e['list_name'], bool(e['is_visited']),
                 e.get('note', ''), e.get('tags', ''), e['title']),
            )

        cur.execute("UPDATE imports SET place_count=%s WHERE id=%s",
                    (len(unique), import_id))
    conn.commit()
    return import_id
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add mygmap/ingest.py tests/test_ingest.py
git commit -m "feat: 新增 ingest（建立匯入、upsert 地點、寫入清單歸屬快照）"
```

---

## Task 6: 差異查詢與報告輸出

**Files:**
- Create: `mygmap/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: Task 3 schema、Task 5 `ingest_entries`。
- Produces：
  - `mygmap.report.latest_two_imports(conn) -> (prev_id|None, curr_id|None)`。
  - `mygmap.report.added_places(conn, prev, curr) -> list[dict]`（鍵 `place_key,title,url,lists`）。
  - `mygmap.report.removed_places(conn, prev, curr) -> list[dict]`。
  - `mygmap.report.list_changes(conn, prev, curr) -> list[dict]`（鍵 `place_key,title,added_lists,removed_lists`）。
  - `mygmap.report.closure_changes(conn, prev, curr) -> list[dict]`（鍵 `place_key,title,old_status,new_status`）。
  - `mygmap.report.render_markdown(conn, prev, curr, date_str) -> str`。
  - `mygmap.report.write_report(conn, out_dir='data/output', date_str=None) -> str|None`（回傳報告檔路徑；無資料回 None）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_report.py`：

```python
from mygmap.ingest import ingest_entries
from mygmap import report


def _e(title, list_name, url='', visited=True):
    return {'title': title, 'list_name': list_name, 'url': url,
            'address': '', 'note': '', 'tags': '', 'is_visited': visited}


def _two_imports(conn):
    prev = ingest_entries(conn, [
        _e('A店', '想去的地點', url='x/data=!1s0x1:0x1', visited=False),
        _e('B店', '台北牛肉麵', url='x/data=!1s0x2:0x2'),
    ], source_zip='t1.zip')
    curr = ingest_entries(conn, [
        _e('B店', '想去的地點', url='x/data=!1s0x2:0x2', visited=False),  # 換清單
        _e('C店', '消夜', url='x/data=!1s0x3:0x3'),                        # 新增
    ], source_zip='t2.zip')                                                # A店 消失
    return prev, curr


def test_added_and_removed(conn):
    prev, curr = _two_imports(conn)
    added = {p['title'] for p in report.added_places(conn, prev, curr)}
    removed = {p['title'] for p in report.removed_places(conn, prev, curr)}
    assert added == {'C店'}
    assert removed == {'A店'}


def test_list_changes(conn):
    prev, curr = _two_imports(conn)
    changes = {c['title']: c for c in report.list_changes(conn, prev, curr)}
    assert 'B店' in changes
    assert changes['B店']['added_lists'] == ['想去的地點']
    assert changes['B店']['removed_lists'] == ['台北牛肉麵']


def test_render_markdown_has_sections(conn):
    prev, curr = _two_imports(conn)
    md = report.render_markdown(conn, prev, curr, '2026-07-25')
    assert '新增店家' in md
    assert '消失店家' in md
    assert 'C店' in md and 'A店' in md


def test_write_report_creates_file(conn, tmp_path):
    _two_imports(conn)
    path = report.write_report(conn, out_dir=str(tmp_path), date_str='2026-07-25')
    assert path is not None
    assert path.endswith('changes_2026-07-25.md')
    with open(path, encoding='utf-8') as f:
        assert '新增店家' in f.read()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_report.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.report'`）。

- [ ] **Step 3: 實作 report.py**

Create `mygmap/report.py`：

```python
import csv
import os


def latest_two_imports(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM imports ORDER BY id DESC LIMIT 2")
        rows = [r[0] for r in cur.fetchall()]
    curr = rows[0] if rows else None
    prev = rows[1] if len(rows) > 1 else None
    return prev, curr


def _place_lists(conn, import_id):
    """回傳 {place_key: (title, url, [list_name,...])}。"""
    result = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.place_key, p.title, p.url, m.list_name
            FROM list_memberships m JOIN places p ON p.place_key = m.place_key
            WHERE m.import_id = %s
            ORDER BY p.title, m.list_name
            """,
            (import_id,),
        )
        for place_key, title, url, list_name in cur.fetchall():
            entry = result.setdefault(place_key, (title, url, []))
            entry[2].append(list_name)
    return result


def added_places(conn, prev, curr):
    curr_map = _place_lists(conn, curr)
    prev_map = _place_lists(conn, prev) if prev else {}
    out = []
    for pk, (title, url, lists) in curr_map.items():
        if pk not in prev_map:
            out.append({'place_key': pk, 'title': title, 'url': url, 'lists': lists})
    return sorted(out, key=lambda x: x['title'])


def removed_places(conn, prev, curr):
    if not prev:
        return []
    curr_map = _place_lists(conn, curr)
    prev_map = _place_lists(conn, prev)
    out = []
    for pk, (title, url, lists) in prev_map.items():
        if pk not in curr_map:
            out.append({'place_key': pk, 'title': title, 'url': url, 'lists': lists})
    return sorted(out, key=lambda x: x['title'])


def list_changes(conn, prev, curr):
    if not prev:
        return []
    curr_map = _place_lists(conn, curr)
    prev_map = _place_lists(conn, prev)
    out = []
    for pk in set(curr_map) & set(prev_map):
        title, _url, curr_lists = curr_map[pk]
        _t, _u, prev_lists = prev_map[pk]
        added = sorted(set(curr_lists) - set(prev_lists))
        removed = sorted(set(prev_lists) - set(curr_lists))
        if added or removed:
            out.append({'place_key': pk, 'title': title,
                        'added_lists': added, 'removed_lists': removed})
    return sorted(out, key=lambda x: x['title'])


def closure_changes(conn, prev, curr):
    if not prev:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.place_key, p.title, prev.status, c.status
            FROM closure_checks c
            JOIN places p ON p.place_key = c.place_key
            JOIN closure_checks prev
              ON prev.place_key = c.place_key AND prev.import_id = %s
            WHERE c.import_id = %s AND c.status <> prev.status
            ORDER BY p.title
            """,
            (prev, curr),
        )
        return [{'place_key': pk, 'title': t, 'old_status': o, 'new_status': n}
                for pk, t, o, n in cur.fetchall()]


def render_markdown(conn, prev, curr, date_str):
    added = added_places(conn, prev, curr)
    removed = removed_places(conn, prev, curr)
    lists = list_changes(conn, prev, curr)
    closures = closure_changes(conn, prev, curr)

    lines = [f"# 清單變化報告 {date_str}", ""]
    if prev is None:
        lines.append("> 初始快照，無上一次匯入可比對。")
        lines.append("")

    lines.append(f"## 新增店家（{len(added)}）")
    for p in added:
        lines.append(f"- {p['title']}（{', '.join(p['lists'])}）{p['url']}")
    lines.append("")

    lines.append(f"## 消失店家（{len(removed)}）")
    lines.append("> 可能是你自行移除，或本次 Takeout 未含。可拿去 Google Maps 手動確認。")
    for p in removed:
        lines.append(f"- {p['title']}（原清單：{', '.join(p['lists'])}）{p['url']}")
    lines.append("")

    lines.append(f"## 所屬清單變化（{len(lists)}）")
    for c in lists:
        parts = []
        if c['added_lists']:
            parts.append(f"加入 {', '.join(c['added_lists'])}")
        if c['removed_lists']:
            parts.append(f"移出 {', '.join(c['removed_lists'])}")
        lines.append(f"- {c['title']}：{'；'.join(parts)}")
    lines.append("")

    lines.append(f"## 歇業狀態變化（{len(closures)}）")
    for c in closures:
        lines.append(f"- {c['title']}：{c['old_status']} → {c['new_status']}")
    lines.append("")
    return "\n".join(lines)


def write_report(conn, out_dir='data/output', date_str=None):
    prev, curr = latest_two_imports(conn)
    if curr is None:
        return None
    if date_str is None:
        with conn.cursor() as cur:
            cur.execute("SELECT to_char(imported_at, 'YYYY-MM-DD') FROM imports WHERE id=%s",
                        (curr,))
            date_str = cur.fetchone()[0]
    os.makedirs(out_dir, exist_ok=True)

    md = render_markdown(conn, prev, curr, date_str)
    md_path = os.path.join(out_dir, f"changes_{date_str}.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)

    csv_path = os.path.join(out_dir, f"changes_{date_str}.csv")
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['變化類型', '店名', '清單/狀態', '連結'])
        for p in added_places(conn, prev, curr):
            w.writerow(['新增', p['title'], ', '.join(p['lists']), p['url']])
        for p in removed_places(conn, prev, curr):
            w.writerow(['消失', p['title'], ', '.join(p['lists']), p['url']])
        for c in list_changes(conn, prev, curr):
            detail = f"+{c['added_lists']} -{c['removed_lists']}"
            w.writerow(['清單變化', c['title'], detail, ''])
        for c in closure_changes(conn, prev, curr):
            w.writerow(['歇業變化', c['title'], f"{c['old_status']}→{c['new_status']}", ''])
    return md_path
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_report.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: Commit**

```bash
git add mygmap/report.py tests/test_report.py
git commit -m "feat: 新增差異查詢與變化報告（Markdown/CSV）"
```

---

## Task 7: CLI 端到端（init → ingest → report）

**Files:**
- Create: `mygmap/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `mygmap.db`、`mygmap.takeout`、`mygmap.ingest`、`mygmap.report`。
- Produces: `mygmap.cli.run(conn, takeout_dir='data/takeout', out_dir='data/output') -> dict`（含 `import_id`、`report_path`、`place_count`）；`mygmap.cli.main()`（讀 `.env` 連線、印摘要，無 emoji）。

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_cli.py`：

```python
import os
import shutil

from mygmap import cli

FIX_SAVED = os.path.join(os.path.dirname(__file__), 'fixtures', 'saved')


def _make_zip(tmp_path):
    import zipfile
    zdir = tmp_path / 'data' / 'takeout'
    zdir.mkdir(parents=True)
    zpath = zdir / 'takeout-20260524T120207Z-1-001.zip'
    with zipfile.ZipFile(zpath, 'w') as z:
        for fn in os.listdir(FIX_SAVED):
            z.write(os.path.join(FIX_SAVED, fn), arcname=f'Takeout/已儲存/{fn}')
    return str(zdir)


def test_run_ingests_and_writes_report(conn, tmp_path):
    takeout_dir = _make_zip(tmp_path)
    out_dir = str(tmp_path / 'out')
    result = cli.run(conn, takeout_dir=takeout_dir, out_dir=out_dir)
    assert result['import_id'] is not None
    assert result['place_count'] == 3          # 小吳、牛耳、阿發（圖片排除）
    assert os.path.exists(result['report_path'])
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'mygmap.cli'`）。

- [ ] **Step 3: 實作 cli.py**

Create `mygmap/cli.py`：

```python
import os

from . import db, report
from .ingest import ingest_entries
from .takeout import extract_and_read, find_latest_zip, parse_export_time


def run(conn, takeout_dir='data/takeout', out_dir='data/output'):
    db.init_schema(conn)
    zip_path = find_latest_zip(takeout_dir)
    entries = extract_and_read(zip_path) if zip_path else []
    source_zip = os.path.basename(zip_path) if zip_path else None
    exported_at = parse_export_time(source_zip) if source_zip else None
    import_id = ingest_entries(conn, entries, source_zip=source_zip,
                               takeout_exported_at=exported_at)
    report_path = report.write_report(conn, out_dir=out_dir)
    with conn.cursor() as cur:
        cur.execute("SELECT place_count FROM imports WHERE id=%s", (import_id,))
        place_count = cur.fetchone()[0]
    return {'import_id': import_id, 'report_path': report_path,
            'place_count': place_count}


def main():
    conn = db.connect()
    try:
        result = run(conn)
        print(f"[OK] import_id={result['import_id']} "
              f"place_count={result['place_count']}")
        if result['report_path']:
            print(f"[OK] report: {result['report_path']}")
        else:
            print("[INFO] 尚無可比對的上一次匯入，未產生報告。")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 5: 全套測試 + 提交**

Run: `uv run pytest -v`
Expected: 全部 PASS（DB 未跑時 DB 相關測試 skipped）。

```bash
git add mygmap/cli.py tests/test_cli.py
git commit -m "feat: 新增 CLI 端到端（匯入最新 Takeout 並產生變化報告）"
```

---

## Task 8: 真實資料煙霧測試與文件

**Files:**
- Modify: `README.md`
- Create: `docs/postgres-pipeline.md`

**Interfaces:**
- Consumes: 完整 `mygmap` 套件。
- Produces: 使用說明文件；一次對真實 `data/takeout/` 的手動驗證紀錄。

- [ ] **Step 1: 對真實資料跑一次（煙霧測試）**

Run: `uv run python -m mygmap.cli`
Expected: 印出 `import_id=…`、`place_count≈…`；`data/output/changes_<今天>.md` 產生（首次執行因無上一次匯入，報告標示「初始快照」）。

- [ ] **Step 2: 用 DBeaver 或 psql 抽查**

Run（於你自己終端機）: `psql -U mygmap_app -h localhost -d mygooglemap -c "SELECT id, source_zip, place_count, imported_at FROM imports ORDER BY id;"`
Expected: 至少一列，`place_count` 與清單店家數相符。

- [ ] **Step 3: 撰寫使用文件**

Create `docs/postgres-pipeline.md`：說明前置（`.env` 的 `PG*`、已建 `mygooglemap`/`mygmap_app`）、執行 `uv run python -m mygmap.cli`、報告位置 `data/output/changes_<日期>.md`、與 Plan 2 尚未涵蓋的部分（enrichment、歇業驗證、從 DB 產 `stores_data.js`）。

- [ ] **Step 4: 更新 README**

Modify `README.md`：新增「PostgreSQL 變化追蹤（Plan 1）」段落，連到 `docs/postgres-pipeline.md`。

- [ ] **Step 5: Commit**

```bash
git add README.md docs/postgres-pipeline.md
git commit -m "docs: 新增 PostgreSQL 變化追蹤使用說明與煙霧測試紀錄"
```

---

## Self-Review

**Spec coverage（對照設計文件 §1–§16）：**
- §3 place_key → Task 2 ✅
- §4 schema（imports/places/list_memberships/closure_checks/api_cache/schema_meta + 索引）→ Task 3 ✅（`closure_checks`/`api_cache` 建表於此，資料填入屬 Plan 2）
- §4 差異計算（新增/消失、清單、歇業）→ Task 6 ✅（歇業 diff 邏輯就緒，資料於 Plan 2 M5 填入）
- §5 模組 config/db/takeout/places/ingest/report/cli → Task 1–7 ✅（enrich/verify/export 屬 Plan 2）
- §6 資料流 init→ingest→report → Task 7 ✅（enrich/verify/export 屬 Plan 2）
- §8 差異報告（Markdown/CSV、消失＝手動清理待辦、初始快照標示）→ Task 6 ✅
- §10 安全（密碼不外露）→ Task 1（repr/ safe_dict 測試）✅
- §12 測試（place_key、差異四類、冪等、takeout 排除圖片）→ Task 2/4/5/6 ✅
- §13 相依（psycopg、pytest）→ Task 1 ✅
- **本計畫（Plan 1）不涵蓋**：§7 stores_data.js 匯出與 golden test、§9 歇業驗證、§11 backfill、enrichment ⇒ 皆歸 **Plan 2（M4–M7）**，將於 Plan 1 執行完成後另立計畫。

**Placeholder scan：** 無 TBD/TODO；每個程式步驟均含完整程式碼與可執行指令。

**Type consistency：** `place_key(url, title, address)` 於 Task 2 定義，Task 5 一致呼叫；`ingest_entries(conn, entries, source_zip, takeout_exported_at)` 於 Task 5 定義，Task 7 一致呼叫；`write_report(conn, out_dir, date_str)`、`latest_two_imports`、`added_places/removed_places/list_changes/closure_changes` 於 Task 6 定義，Task 7 一致使用；entries dict 鍵（`title/note/url/address/tags/list_name/is_visited`）於 Task 4 產出、Task 5 消費，一致。

**Scope check：** Plan 1 聚焦「可獨立運作、可測試」的變化追蹤核心；Plan 2 承接完整資料主體遷移。
