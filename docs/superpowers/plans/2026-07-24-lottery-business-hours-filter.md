# 抽籤頁「營業時間」篩選 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在抽籤頁新增以 Google Maps 真實營業時間為基準的「營業時間」篩選（營業中／早餐／中餐／下午茶／晚餐／消夜／未知）。

**Architecture:** 資料管線（Python）在既有 CID Place Details 查詢多抓 `opening_hours`，正規化後寫入 `stores_data.js` 的新 `hours` 欄位；純判斷邏輯抽成獨立、可測試的模組（Python `hours_normalize.py`、瀏覽器/Node 共用的 `hours_logic.js`），前端 `lottery.html` 依系統時間即時計算並篩選。

**Tech Stack:** Python 3.11（stdlib `unittest`，零新依賴）、原生 JS（Node 22 內建 `node --test`，無 npm 依賴）、既有 Google Places API（legacy Place Details）。

## Global Constraints

- 純判斷函式必須接受傳入的「現在」時間參數，不得直接呼叫 `Date.now()`／`datetime.now()`，以利決定性測試。
- `hours` 欄位語意：`null` = 未知；陣列 `[{d,o,c}]`，`d`=營業起始星期（0=日..6=六），`o`/`c`=`"HHMM"`（`"0000"`–`"2400"`）；`c` 數值 ≤ `o` 表示跨午夜到隔天；24 小時營業正規化為 7 筆 `{d:i,o:"0000",c:"2400"}`。
- 用餐時段界線（分鐘，自午夜起算）：早餐 300–630、中餐 630–840、下午茶 840–1020、晚餐 1020–1260、消夜 1260–1740（>1440 表示延伸到隔天）。
- 時段標籤依「今天」（傳入時間當天）判斷；`hours` 為 null 的店家只有勾「未知」才可能被抽到。
- 前端預設勾選：**只有「營業中」勾選**，其餘不勾。
- checkbox `value`：`open-now / breakfast / lunch / tea / dinner / latenight / unknown`。
- 不修改既有其他篩選、動畫與「零符合→從全部抽」的 fallback 行為。

---

### Task 1: Python 營業時間正規化純函式

**Files:**
- Create: `hours_normalize.py`
- Test: `test_hours_normalize.py`

**Interfaces:**
- Produces:
  - `normalize_opening_hours(periods) -> list[dict] | None`：`periods` 為 Google Place Details `opening_hours.periods`（或 None/空）。回傳 `[{"d":int,"o":"HHMM","c":"HHMM"}, ...]` 或 `None`。
  - `parse_place_details_response(data) -> dict`：`data` 為 Place Details API 解析後的 JSON dict。回傳 `{"address": str, "hours": list|None, "hours_text": str}`。

- [ ] **Step 1: Write the failing tests**

Create `test_hours_normalize.py`:

```python
import unittest
from hours_normalize import normalize_opening_hours, parse_place_details_response


class NormalizeOpeningHours(unittest.TestCase):
    def test_none_or_empty_returns_none(self):
        self.assertIsNone(normalize_opening_hours(None))
        self.assertIsNone(normalize_opening_hours([]))

    def test_open_24_7_expands_to_seven_full_days(self):
        periods = [{"open": {"day": 0, "time": "0000"}}]
        result = normalize_opening_hours(periods)
        self.assertEqual(len(result), 7)
        self.assertEqual(result[0], {"d": 0, "o": "0000", "c": "2400"})
        self.assertEqual(result[6], {"d": 6, "o": "0000", "c": "2400"})

    def test_two_shifts_same_day(self):
        periods = [
            {"open": {"day": 1, "time": "1100"}, "close": {"day": 1, "time": "1430"}},
            {"open": {"day": 1, "time": "1700"}, "close": {"day": 1, "time": "2100"}},
        ]
        self.assertEqual(
            normalize_opening_hours(periods),
            [{"d": 1, "o": "1100", "c": "1430"}, {"d": 1, "o": "1700", "c": "2100"}],
        )

    def test_cross_midnight_keeps_close_time(self):
        periods = [{"open": {"day": 5, "time": "1800"}, "close": {"day": 6, "time": "0200"}}]
        self.assertEqual(normalize_opening_hours(periods), [{"d": 5, "o": "1800", "c": "0200"}])

    def test_malformed_period_is_skipped(self):
        periods = [
            {"open": {"day": 2, "time": "0900"}, "close": {"day": 2, "time": "1700"}},
            {"open": {"day": 3}},  # 缺 time/close
        ]
        self.assertEqual(normalize_opening_hours(periods), [{"d": 2, "o": "0900", "c": "1700"}])

    def test_all_malformed_returns_none(self):
        self.assertIsNone(normalize_opening_hours([{"open": {"day": 3}}]))


class ParsePlaceDetails(unittest.TestCase):
    def test_full_response(self):
        data = {"result": {
            "formatted_address": "台北市大安區信義路二段194號",
            "opening_hours": {
                "periods": [{"open": {"day": 1, "time": "1100"}, "close": {"day": 1, "time": "1430"}}],
                "weekday_text": ["星期一: 11:00 – 14:30", "星期二: 休息"],
            },
        }}
        out = parse_place_details_response(data)
        self.assertEqual(out["address"], "台北市大安區信義路二段194號")
        self.assertEqual(out["hours"], [{"d": 1, "o": "1100", "c": "1430"}])
        self.assertEqual(out["hours_text"], "星期一: 11:00 – 14:30 / 星期二: 休息")

    def test_no_opening_hours(self):
        data = {"result": {"formatted_address": "某地址"}}
        out = parse_place_details_response(data)
        self.assertEqual(out["address"], "某地址")
        self.assertIsNone(out["hours"])
        self.assertEqual(out["hours_text"], "")

    def test_empty_data(self):
        out = parse_place_details_response({})
        self.assertEqual(out["address"], "")
        self.assertIsNone(out["hours"])
        self.assertEqual(out["hours_text"], "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest -v test_hours_normalize`
Expected: FAIL — `ModuleNotFoundError: No module named 'hours_normalize'`

- [ ] **Step 3: Write minimal implementation**

Create `hours_normalize.py`:

```python
"""將 Google Places Place Details 的營業時間轉為抽籤頁使用的精簡格式。

僅用標準庫，無外部依賴，方便單元測試與被 export_to_sheets.py 匯入。
"""


def normalize_opening_hours(periods):
    """periods = Google opening_hours.periods（或 None/空）。

    回傳 [{"d":int,"o":"HHMM","c":"HHMM"}, ...] 或 None（未知）。
    - 24 小時營業（單一 period、無 close、open 為 0000）→ 展開為 7 天全日。
    - 跨午夜的時段保留原始 open/close 時間（前端以 c<=o 判定跨天）。
    - 格式不完整的 period 略過；全部略過則回傳 None。
    """
    if not periods:
        return None

    if len(periods) == 1 and "close" not in periods[0]:
        if (periods[0].get("open") or {}).get("time") == "0000":
            return [{"d": i, "o": "0000", "c": "2400"} for i in range(7)]
        return None

    out = []
    for p in periods:
        op = p.get("open") or {}
        cl = p.get("close") or {}
        day = op.get("day")
        o = op.get("time")
        c = cl.get("time")
        if day is None or o is None or c is None:
            continue
        out.append({"d": day, "o": o, "c": c})
    return out or None


def parse_place_details_response(data):
    """data = Place Details API 回傳並解析後的 dict。

    回傳 {"address": str, "hours": list|None, "hours_text": str}。
    """
    result = data.get("result", {}) if isinstance(data, dict) else {}
    address = result.get("formatted_address", "") or ""
    oh = result.get("opening_hours") or {}
    hours = normalize_opening_hours(oh.get("periods"))
    hours_text = " / ".join(oh.get("weekday_text") or [])
    return {"address": address, "hours": hours, "hours_text": hours_text}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest -v test_hours_normalize`
Expected: PASS — `Ran 9 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add hours_normalize.py test_hours_normalize.py
git commit -m "feat: 新增營業時間正規化純函式與單元測試"
```

---

### Task 2: 資料管線抓取並輸出營業時間

**Files:**
- Modify: `export_to_sheets.py`（`lookup_address_from_cid` 附近約 223–247；CID 地址查詢迴圈約 680–729；CSV 輸出約 818–835；JS 輸出約 839–860；import 區頂端）

**Interfaces:**
- Consumes: `hours_normalize.parse_place_details_response`（Task 1）
- Produces:
  - `lookup_place_details_from_cid(cid_hex, maps_api_key) -> dict`：呼叫 Place Details（`fields=formatted_address,name,opening_hours`），回傳 `{"address","hours","hours_text"}`；失敗回傳三者為空/None。
  - `stores_data.js` 每筆多出 `hours`（list|None）欄位；CSV 多一欄「營業時間」。

- [ ] **Step 1: 加入 import**

在 `export_to_sheets.py` 頂端 import 區（現有 `import ...` 之後）加入：

```python
from hours_normalize import parse_place_details_response
```

- [ ] **Step 2: 新增 Place Details 查詢函式（含營業時間）**

在 `lookup_address_from_cid`（約第 247 行結束）之後新增：

```python
def lookup_place_details_from_cid(cid_hex, maps_api_key):
    """用 CID（0xA:0xB）呼叫 Place Details API，取回地址與營業時間。
    需要 MAPS_API_KEY 且已啟用 Places API。
    回傳 {"address": str, "hours": list|None, "hours_text": str}。"""
    empty = {"address": "", "hours": None, "hours_text": ""}
    if not cid_hex or not maps_api_key:
        return empty
    try:
        params = urllib.parse.urlencode({
            'place_id': cid_hex,
            'fields':   'formatted_address,name,opening_hours',
            'language': 'zh-TW',
            'key':      maps_api_key,
        })
        api_url = f"https://maps.googleapis.com/maps/api/place/details/json?{params}"
        with urllib.request.urlopen(api_url, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        status = data.get('status', '')
        if status == 'OK':
            return parse_place_details_response(data)
        if status == 'REQUEST_DENIED':
            raise RuntimeError('Places API 未啟用，請在 Google Cloud Console 開啟 Places API')
    except RuntimeError:
        raise
    except Exception as e:
        print(f"  [Place Details] 查詢失敗: {e}")
    return empty
```

- [ ] **Step 3: 新增營業時間抓取迴圈**

在既有「使用 Place Details / Find Place 預先填入缺少地址」區塊之後、`--- 使用 Gemini ... ---` 分析開始之前（約第 730 行），插入以下迴圈。它對所有含 CID 的店家補上 `hours`，並用快取避免重複計費；無 CID 或 API 不可用者 `hours=None`：

```python
    # --- 抓取營業時間（所有含 CID 的店家；快取避免重複計費）---
    if maps_api_key and places_api_available is not False:
        hours_cache = load_cache()
        hours_denied = False
        looked = 0
        for p in total_places:
            cid_hex = extract_cid_from_maps_url(p.get('url', ''))
            if not cid_hex:
                p['hours'] = None
                continue
            ck = f"__cid_hours__{cid_hex}"
            if ck in hours_cache:
                p['hours'] = hours_cache[ck].get('hours')
                p['hours_text'] = hours_cache[ck].get('hours_text', '')
                continue
            if hours_denied:
                p['hours'] = None
                continue
            try:
                details = lookup_place_details_from_cid(cid_hex, maps_api_key)
            except RuntimeError as e:
                print(f"\n  [警告] {e}；營業時間將全部標記為未知。")
                hours_denied = True
                p['hours'] = None
                continue
            p['hours'] = details['hours']
            p['hours_text'] = details['hours_text']
            hours_cache[ck] = {'hours': details['hours'], 'hours_text': details['hours_text']}
            save_cache(hours_cache)
            looked += 1
        if looked:
            print(f"\n營業時間查詢完成，本次新查 {looked} 筆（其餘來自快取）。")
    else:
        for p in total_places:
            p['hours'] = None
```

- [ ] **Step 4: 確保每筆都有 hours 欄位（降級保險）**

在既有 `p.setdefault('lng', None)` / `p.setdefault('distance_km', None)` 附近（約第 815 行）加入：

```python
            p.setdefault('hours', None)
```

- [ ] **Step 5: CSV 加「營業時間」欄**

在 CSV 標頭（約第 822 行）末端加入 `'營業時間'`：

```python
            writer.writerow(['店名', '地址', '網址', '餐飲類型', '來源清單', '是否曾去過', '距離住家(公里)', '人均消費預估(元)', '備註', '營業時間'])
```

並在資料列（約第 824–834 行的 `writer.writerow([...])`）末端 `p['note']` 之後加入：

```python
                    p.get('hours_text', ''),
```

- [ ] **Step 6: JS 輸出加 hours 欄**

在 `js_data` 的 dict（約第 851 行 `'note': p['note']` 之後）加入：

```python
                'note':         p['note'],
                'hours':        p.get('hours'),
```

（將原本 `'note': p['note']` 結尾的逗號補上，如上所示。）

- [ ] **Step 7: 語法檢查**

Run: `python -c "import ast; ast.parse(open('export_to_sheets.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 8: 匯入健全性檢查（確認新函式與 import 可用）**

Run: `python -c "import export_to_sheets as m; print(hasattr(m, 'lookup_place_details_from_cid'), m.parse_place_details_response({}))"`
Expected: `True {'address': '', 'hours': None, 'hours_text': ''}`
（若因缺 google 套件無法 import，改在 `.venv` 執行：`.venv/Scripts/python -c "..."`。）

- [ ] **Step 9: Commit**

```bash
git add export_to_sheets.py
git commit -m "feat: 資料管線抓取 Google 營業時間並輸出 hours 欄位"
```

> 註：實際重跑 `export_to_sheets.py` 打 Places API 需 `MAPS_API_KEY` 與網路（屬使用者部署步驟，見 Task 5）。本任務以純函式單元測試（Task 1）與語法／匯入檢查驗證程式正確性。

---

### Task 3: 前端營業時間判斷純函式（Node 可測）

**Files:**
- Create: `hours_logic.js`
- Test: `hours_logic.test.js`

**Interfaces:**
- Produces（瀏覽器掛在 `window.HoursLogic`，Node 為 `module.exports`）：
  - `MEAL_WINDOWS`、`MEAL_KEYS`
  - `toMin(hhmm) -> number`
  - `expandIntervals(hours) -> Array<[startAbs, endAbs]>`
  - `isOpenNow(hours, now) -> boolean`
  - `servesMeal(hours, now, mealKey) -> boolean`
  - `matchesHoursFilter(store, now, checkedSet) -> boolean`
  - `now` 為具 `getDay()/getHours()/getMinutes()` 的物件（`Date` 或測試 stub）。

- [ ] **Step 1: Write the failing tests**

Create `hours_logic.test.js`:

```js
const test = require('node:test');
const assert = require('node:assert');
const H = require('./hours_logic.js');

// 建立具 getDay/getHours/getMinutes 的假時間
function at(day, hh, mm) {
  return { getDay: () => day, getHours: () => hh, getMinutes: () => mm };
}

const MON_LUNCH_DINNER = [
  { d: 1, o: '1100', c: '1430' },
  { d: 1, o: '1700', c: '2100' },
];

test('toMin handles 2400 and normal times', () => {
  assert.strictEqual(H.toMin('2400'), 1440);
  assert.strictEqual(H.toMin('0930'), 570);
});

test('isOpenNow within and outside shifts', () => {
  assert.strictEqual(H.isOpenNow(MON_LUNCH_DINNER, at(1, 12, 30)), true);
  assert.strictEqual(H.isOpenNow(MON_LUNCH_DINNER, at(1, 15, 0)), false);
  assert.strictEqual(H.isOpenNow(MON_LUNCH_DINNER, at(1, 20, 59)), true);
  assert.strictEqual(H.isOpenNow(MON_LUNCH_DINNER, at(1, 21, 0)), false);
});

test('cross-midnight open spills into next day', () => {
  const fri = [{ d: 5, o: '1800', c: '0200' }];
  assert.strictEqual(H.isOpenNow(fri, at(6, 1, 0)), true);   // 週六凌晨1點仍營業
  assert.strictEqual(H.isOpenNow(fri, at(6, 3, 0)), false);
});

test('week-boundary wrap (Sat night into Sun)', () => {
  const sat = [{ d: 6, o: '2300', c: '0100' }];
  assert.strictEqual(H.isOpenNow(sat, at(0, 0, 30)), true);  // 週日00:30
});

test('24h open is always open and serves every meal', () => {
  const all = [];
  for (let i = 0; i < 7; i++) all.push({ d: i, o: '0000', c: '2400' });
  assert.strictEqual(H.isOpenNow(all, at(3, 4, 0)), true);
  for (const k of H.MEAL_KEYS) {
    assert.strictEqual(H.servesMeal(all, at(3, 4, 0), k), true);
  }
});

test('servesMeal is today-aware', () => {
  const monDinner = [{ d: 1, o: '1700', c: '2100' }];
  assert.strictEqual(H.servesMeal(monDinner, at(1, 9, 0), 'dinner'), true);
  assert.strictEqual(H.servesMeal(monDinner, at(1, 9, 0), 'breakfast'), false);
  assert.strictEqual(H.servesMeal(monDinner, at(2, 9, 0), 'dinner'), false); // 週二不算
});

test('matchesHoursFilter: unknown only via unknown checkbox', () => {
  const noHours = { hours: null };
  assert.strictEqual(H.matchesHoursFilter(noHours, at(1, 12, 0), new Set(['unknown'])), true);
  assert.strictEqual(H.matchesHoursFilter(noHours, at(1, 12, 0), new Set(['open-now'])), false);

  const withHours = { hours: MON_LUNCH_DINNER };
  assert.strictEqual(H.matchesHoursFilter(withHours, at(1, 12, 0), new Set(['unknown'])), false);
  assert.strictEqual(H.matchesHoursFilter(withHours, at(1, 12, 0), new Set(['open-now'])), true);
  assert.strictEqual(H.matchesHoursFilter(withHours, at(1, 12, 0), new Set(['lunch'])), true);
  assert.strictEqual(H.matchesHoursFilter(withHours, at(1, 12, 0), new Set([])), false);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test hours_logic.test.js`
Expected: FAIL — `Cannot find module './hours_logic.js'`

- [ ] **Step 3: Write minimal implementation**

Create `hours_logic.js`:

```js
// hours_logic.js — 純函式：由店家每週營業時段 (hours) 與傳入的「現在」時間，
// 判斷是否營業中、是否供應某餐時段。瀏覽器與 Node 皆可用。
(function (global) {
  'use strict';

  // 分鐘（自午夜起算）；latenight >1440 表示延伸到隔天。
  var MEAL_WINDOWS = {
    breakfast: [300, 630],    // 05:00–10:30
    lunch:     [630, 840],    // 10:30–14:00
    tea:       [840, 1020],   // 14:00–17:00
    dinner:    [1020, 1260],  // 17:00–21:00
    latenight: [1260, 1740],  // 21:00–次日05:00
  };
  var MEAL_KEYS = ['breakfast', 'lunch', 'tea', 'dinner', 'latenight'];
  var WEEK = 7 * 1440;

  function toMin(hhmm) {
    return parseInt(hhmm.slice(0, 2), 10) * 60 + parseInt(hhmm.slice(2), 10);
  }

  // 展開成一週分鐘軸上的營業區間 [start, end)，並加 ±一週副本以處理跨午夜與週界。
  function expandIntervals(hours) {
    var out = [];
    if (!hours || !hours.length) return out;
    for (var i = 0; i < hours.length; i++) {
      var h = hours[i];
      var oMin = toMin(h.o);
      var cMin = toMin(h.c);
      var start = h.d * 1440 + oMin;
      var end = (cMin <= oMin) ? (h.d * 1440 + 1440 + cMin) : (h.d * 1440 + cMin);
      out.push([start, end]);
      out.push([start - WEEK, end - WEEK]);
      out.push([start + WEEK, end + WEEK]);
    }
    return out;
  }

  function nowToAbs(now) {
    return now.getDay() * 1440 + now.getHours() * 60 + now.getMinutes();
  }

  function isOpenNow(hours, now) {
    var abs = nowToAbs(now);
    var iv = expandIntervals(hours);
    for (var i = 0; i < iv.length; i++) {
      if (iv[i][0] <= abs && abs < iv[i][1]) return true;
    }
    return false;
  }

  function servesMeal(hours, now, mealKey) {
    var win = MEAL_WINDOWS[mealKey];
    if (!win) return false;
    var base = now.getDay() * 1440;
    var winStart = base + win[0];
    var winEnd = base + win[1];
    var iv = expandIntervals(hours);
    for (var i = 0; i < iv.length; i++) {
      if (iv[i][0] < winEnd && iv[i][1] > winStart) return true; // 有重疊
    }
    return false;
  }

  // store.hours: null/undefined/[] → 未知；有資料的店永遠不經 'unknown' 命中。
  function matchesHoursFilter(store, now, checkedSet) {
    var hours = store.hours;
    if (hours == null || hours.length === 0) {
      return checkedSet.has('unknown');
    }
    if (checkedSet.has('open-now') && isOpenNow(hours, now)) return true;
    for (var i = 0; i < MEAL_KEYS.length; i++) {
      if (checkedSet.has(MEAL_KEYS[i]) && servesMeal(hours, now, MEAL_KEYS[i])) return true;
    }
    return false;
  }

  var api = {
    MEAL_WINDOWS: MEAL_WINDOWS, MEAL_KEYS: MEAL_KEYS, toMin: toMin,
    expandIntervals: expandIntervals, isOpenNow: isOpenNow,
    servesMeal: servesMeal, matchesHoursFilter: matchesHoursFilter,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    global.HoursLogic = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test hours_logic.test.js`
Expected: PASS — `# pass 7` / `# fail 0`

- [ ] **Step 5: Commit**

```bash
git add hours_logic.js hours_logic.test.js
git commit -m "feat: 新增前端營業時間判斷純函式與 node 測試"
```

---

### Task 4: 整合到 lottery.html

**Files:**
- Modify: `lottery.html`（載入 script 約 700；側欄篩選區約 517–536 後；結果標籤約 666 後；`updateFilters()` 約 832–913；`displayWinner()` 約 998–1064）

**Interfaces:**
- Consumes: `window.HoursLogic.matchesHoursFilter`、`window.HoursLogic.isOpenNow`（Task 3）
- Produces: 側欄「營業時間」篩選、結果卡片營業狀態標籤。

- [ ] **Step 1: 載入 hours_logic.js**

在 `<script src="data/output/stores_data.js"></script>`（第 700 行）之後加入：

```html
  <!-- 營業時間判斷純函式（供瀏覽器與 Node 共用） -->
  <script src="hours_logic.js"></script>
```

- [ ] **Step 2: 新增「營業時間」篩選區**

在「回訪狀態」`filter-section`（結束於第 536 行 `</div>`）之後、「餐飲類型」區之前，插入：

```html
      <!-- Business Hours Filter -->
      <div class="filter-section">
        <div class="filter-title">
          <span>營業時間</span>
          <div class="filter-actions">
            <a onclick="selectAll('hours', true)">全選</a>
            <span>|</span>
            <a onclick="selectAll('hours', false)">全不選</a>
          </div>
        </div>
        <div class="checkbox-group">
          <label class="checkbox-label">
            <input type="checkbox" name="hours" value="open-now" checked> 營業中（依現在時間）
          </label>
          <label class="checkbox-label">
            <input type="checkbox" name="hours" value="breakfast"> 早餐 (05:00–10:30)
          </label>
          <label class="checkbox-label">
            <input type="checkbox" name="hours" value="lunch"> 中餐 (10:30–14:00)
          </label>
          <label class="checkbox-label">
            <input type="checkbox" name="hours" value="tea"> 下午茶 (14:00–17:00)
          </label>
          <label class="checkbox-label">
            <input type="checkbox" name="hours" value="dinner"> 晚餐 (17:00–21:00)
          </label>
          <label class="checkbox-label">
            <input type="checkbox" name="hours" value="latenight"> 消夜 (21:00–05:00)
          </label>
          <label class="checkbox-label">
            <input type="checkbox" name="hours" value="unknown"> 未知（無營業時間資料）
          </label>
        </div>
      </div>
```

- [ ] **Step 3: 在 updateFilters() 讀取勾選並套用篩選**

在 `updateFilters()` 內、取得 `activeCounties` 之後（約第 847 行）加入：

```javascript
      // 6. Business Hours filter
      const activeHours = new Set(
        Array.from(document.querySelectorAll('input[name="hours"]:checked')).map(b => b.value)
      );
      const now = new Date();
```

接著在 `filteredStores = stores.filter(s => { ... })` 內、`return true;`（約第 902 行）之前加入：

```javascript
        // Match Business Hours
        if (!window.HoursLogic.matchesHoursFilter(s, now, activeHours)) return false;
```

- [ ] **Step 4: 結果卡片加營業狀態標籤（HTML）**

在 result-tags 內、`winner-tag-visit`（第 666 行）之後加入：

```html
              <span class="badge" id="winner-tag-hours" style="display: none;"></span>
```

- [ ] **Step 5: 結果卡片營業狀態標籤（JS）**

在 `displayWinner()` 內、Visited Badge 區塊（約第 1044 行 `}` 之後）加入：

```javascript
      // Business Hours Badge
      const hoursBadge = document.getElementById('winner-tag-hours');
      if (!winner.hours || winner.hours.length === 0) {
        hoursBadge.innerText = '營業時間未知';
        hoursBadge.style.background = 'rgba(148, 163, 184, 0.15)';
        hoursBadge.style.color = '#94a3b8';
        hoursBadge.style.border = '1px solid rgba(148, 163, 184, 0.3)';
      } else if (window.HoursLogic.isOpenNow(winner.hours, new Date())) {
        hoursBadge.innerText = '營業中';
        hoursBadge.style.background = 'rgba(34, 197, 94, 0.15)';
        hoursBadge.style.color = '#4ade80';
        hoursBadge.style.border = '1px solid rgba(34, 197, 94, 0.3)';
      } else {
        hoursBadge.innerText = '已打烊';
        hoursBadge.style.background = 'rgba(148, 163, 184, 0.15)';
        hoursBadge.style.color = '#94a3b8';
        hoursBadge.style.border = '1px solid rgba(148, 163, 184, 0.3)';
      }
      hoursBadge.style.display = 'inline-block';
```

- [ ] **Step 6: Playwright 冒煙驗證**

現有 `stores_data.js` 尚無 `hours`（皆為未知），正好可驗證未知/勾選行為。用 Playwright MCP：

1. `browser_navigate` 到 `file:///d:/code/MyGoogleMap/lottery.html`
2. `browser_snapshot`：確認側欄出現「營業時間」區，且「營業中」為勾選、其餘未勾。
3. 讀取 `#matching-count`：目前資料皆未知 + 只勾營業中 → 應顯示 `0`（含「無符合→從全部抽」提示）。
4. `browser_click` 勾選「未知」→ `#matching-count` 應跳升為接近全部店家數（約 786）。
5. `browser_console_messages`：確認無 JavaScript 錯誤。

Expected：以上皆符合；無 console error。

- [ ] **Step 7: Commit**

```bash
git add lottery.html
git commit -m "feat: 抽籤頁新增營業時間篩選與結果營業狀態標籤"
```

---

### Task 5: 部署說明（文件，非程式）

**Files:**
- Modify: `README.md`（營業時間相關說明，接在既有抽籤說明段落）

**Interfaces:** 無程式介面；記錄使用者重跑管線與部署步驟。

- [ ] **Step 1: 補充 README 說明**

在 `README.md` 適當段落新增（純文字，說明營業時間資料來源與更新方式）：

```markdown
### 營業時間篩選

抽籤頁的「營業時間」分類（營業中／早餐／中餐／下午茶／晚餐／消夜／未知）
以 Google Maps 的營業時間為基準，資料存在 `stores_data.js` 每筆的 `hours` 欄位。

- 需在 `.env` 設定 `MAPS_API_KEY` 並啟用 Places API，重跑 `export_to_sheets.py` 才會抓到營業時間。
- 未設定金鑰或查不到營業時間的店家，`hours` 為 `null`，歸類為「未知」，
  預設不會被抽到，需手動勾選「未知」。
- 用餐時段界線：早餐 05:00–10:30、中餐 10:30–14:00、下午茶 14:00–17:00、
  晚餐 17:00–21:00、消夜 21:00–次日 05:00。
```

- [ ] **Step 2: 提醒使用者重跑與部署（不在此自動執行）**

於交付時口頭提醒使用者：

```text
1. 於 .env 設定 MAPS_API_KEY 並啟用 Places API。
2. 執行：python export_to_sheets.py（重新產生含 hours 的 data/output/stores_data.js）。
3. 部署 gh-pages 時，stores_data.js 被 .gitignore 忽略，需 git add -f data/output/stores_data.js。
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README 補充營業時間篩選與更新流程說明"
```

---

## Self-Review

**1. Spec coverage：**
- 資料模型 `hours` 欄位 → Task 1（正規化）+ Task 2（輸出）。✓
- 管線抓 opening_hours + 快取 + 降級 → Task 2。✓
- 前端篩選 UI（7 選項、複選、全選/全不選、預設只勾營業中）→ Task 4 Step 2。✓
- 判斷邏輯（營業中／今日時段／未知）→ Task 3。✓
- updateFilters 群組間 AND、群組內 OR → Task 4 Step 3（沿用既有 filter 結構）。✓
- 與 fallback 互動 → 由 Task 4 保留既有邏輯，Playwright Step 6 驗證 count=0 行為。✓
- 中獎卡片營業狀態標籤 → Task 4 Steps 4–5。✓
- CSV 人類可讀欄 → Task 2 Step 5。✓
- 邊界（跨午夜/24h/公休/null/週界）→ Task 1 與 Task 3 測試涵蓋。✓
- 部署（重跑、force-add）→ Task 5。✓
- 凌晨勾消夜的已知取捨 → 屬設計取捨，不需程式；README 未特別列，spec 已記錄。可接受。

**2. Placeholder scan：** 無 TBD/TODO；每個程式步驟均含實際程式碼與可執行指令。✓

**3. Type consistency：**
- `parse_place_details_response` 回傳鍵 `address/hours/hours_text` 在 Task 1 定義、Task 2 使用一致。✓
- `hours` 元素鍵 `d/o/c` 在 Python 正規化、JS `toMin/expandIntervals`、測試三處一致。✓
- checkbox `value`（open-now/breakfast/lunch/tea/dinner/latenight/unknown）與 `MEAL_KEYS`、`matchesHoursFilter` 一致。✓
- `window.HoursLogic.matchesHoursFilter` / `isOpenNow` 命名在 Task 3 定義、Task 4 使用一致。✓
