# lottery.html 篩選優化 + UI 美化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `lottery.html` 的抽籤篩選重構為「高覆蓋率欄位硬篩、低覆蓋率欄位加權」的自適應模型（修掉空池 bug），加上五個一鍵情境與加權抽籤，並套用暖食慾配色（B）＋一鍵情境版面（L3）。

**Architecture:** 抽出純函式模組 `lottery_logic.js`（比照 `hours_logic.js`，瀏覽器/Node 雙用、`node --test` 可測），承載分桶/覆蓋率/加權/篩選/情境預設；`lottery.html` 只留 DOM glue（渲染、事件、動畫、結果卡）。不動 `hours_logic.js`、不動 `window.STORES_DATA` 欄位契約、不碰 Python 管線。

**Tech Stack:** 原生 JS（ES5 風格 IIFE，與 `hours_logic.js` 一致）、`node:test` + `node:assert`、HTML/CSS（Google Fonts）。

## Global Constraints

- 資料契約不變：`window.STORES_DATA` 欄位順序 `title, address, url, cuisine_type, source_list, visited, distance_km, avg_spending, note, hours`；`visited` 為 `'是'`/`'否'`；`distance_km` 可為 `null`；`hours` 為陣列或 `null`。
- `lottery_logic.js` 須瀏覽器（`window.LotteryLogic`）與 Node（`module.exports`）雙用；Node 端以 `require('./hours_logic.js')` 取得 HoursLogic，瀏覽器端用 `window.HoursLogic`。
- 純函式一律吃注入的 `now`（具 `getDay/getHours/getMinutes`）與可注入的 `rng`；**不得**呼叫 `Date.now()`/`new Date()`/`Math.random()` 於可測邏輯內（呼叫端才傳入）。
- 測試以 `node --test` 執行（專案無 package.json，勿新增）。既有 `hours_logic.test.js` 須維持綠燈。
- 距離分桶邊界：`≤1→'1', ≤3→'3', ≤5→'5', ≤10→'10', >10→'far', null→'unknown'`（`km` 單位公里，含等號皆取較小桶）。
- 價格分桶邊界：`falsy或≤0→'free', ≤200→'200', ≤500→'500', ≤1000→'1000', >1000→'expensive'`。
- 加權曲線（全域單一）：`wDist`＝`null→1.0, ≤1→3.0, ≤3→2.0, ≤5→1.3, ≤10→0.8, >10→0.4`；`wOpen`＝`無hours→1.0, 營業中→1.8, 已打烊→0.5`；`weight=wDist×wOpen`；`weightOn=false→1`。
- `HOURS_COVERAGE_THRESHOLD = 0.5`。
- 視覺 B 暖食慾：背景炭黑 `#1a1210→#2b1a12`；主色 `#f97316`/`#ef4444`/`#fb923c`；暖白文字 `#fff7ed`；次文字 `#a8836b`。
- 不 push（push 會觸發 gh-pages 部署）；本計畫僅本地 commit。

---

### Task 1: `lottery_logic.js` 模組骨架 + 分桶 + 正規化

**Files:**
- Create: `lottery_logic.js`
- Test: `lottery_logic.test.js`

**Interfaces:**
- Consumes: `hours_logic.js`（Node: `require`；瀏覽器: `window.HoursLogic`）。
- Produces: `window.LotteryLogic`/`module.exports` 上的 `TAIWAN_COUNTIES`（陣列）、`extractCounty(address)→string|null`、`CUISINE_ALIASES`（物件）、`normalizeCuisine(raw)→string`、`distanceBucket(km)→'1'|'3'|'5'|'10'|'far'|'unknown'`、`priceBucket(spending)→'200'|'500'|'1000'|'expensive'|'free'`。

- [ ] **Step 1: Write the failing test**

建立 `lottery_logic.test.js`：

```js
const test = require('node:test');
const assert = require('node:assert');
const L = require('./lottery_logic.js');

test('distanceBucket boundaries', () => {
  assert.strictEqual(L.distanceBucket(null), 'unknown');
  assert.strictEqual(L.distanceBucket(undefined), 'unknown');
  assert.strictEqual(L.distanceBucket(0.5), '1');
  assert.strictEqual(L.distanceBucket(1.0), '1');
  assert.strictEqual(L.distanceBucket(1.01), '3');
  assert.strictEqual(L.distanceBucket(3.0), '3');
  assert.strictEqual(L.distanceBucket(5.0), '5');
  assert.strictEqual(L.distanceBucket(10.0), '10');
  assert.strictEqual(L.distanceBucket(10.1), 'far');
});

test('priceBucket boundaries', () => {
  assert.strictEqual(L.priceBucket(null), 'free');
  assert.strictEqual(L.priceBucket(0), 'free');
  assert.strictEqual(L.priceBucket(200), '200');
  assert.strictEqual(L.priceBucket(201), '500');
  assert.strictEqual(L.priceBucket(500), '500');
  assert.strictEqual(L.priceBucket(1000), '1000');
  assert.strictEqual(L.priceBucket(1001), 'expensive');
});

test('extractCounty normalizes 臺->台 and returns null when absent', () => {
  assert.strictEqual(L.extractCounty('臺北市中正區'), '台北市');
  assert.strictEqual(L.extractCounty('新竹市東區光復路'), '新竹市');
  assert.strictEqual(L.extractCounty('30 Bencoolen St, Singapore'), null);
  assert.strictEqual(L.extractCounty(''), null);
});

test('normalizeCuisine maps aliases', () => {
  assert.strictEqual(L.normalizeCuisine('台式'), '中式');
  assert.strictEqual(L.normalizeCuisine('日式'), '日式');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test lottery_logic.test.js`
Expected: FAIL（`Cannot find module './lottery_logic.js'`）。

- [ ] **Step 3: Write minimal implementation**

建立 `lottery_logic.js`：

```js
// lottery_logic.js — 純函式：抽籤的分桶/覆蓋率/加權/篩選/情境預設。瀏覽器與 Node 皆可用。
(function (global) {
  'use strict';

  var Hours = (typeof module !== 'undefined' && module.exports)
    ? require('./hours_logic.js')
    : global.HoursLogic;

  var TAIWAN_COUNTIES = [
    '台北市', '新北市', '桃園市', '台中市', '台南市', '高雄市',
    '基隆市', '新竹市', '嘉義市',
    '新竹縣', '苗栗縣', '彰化縣', '南投縣', '雲林縣', '嘉義縣',
    '屏東縣', '宜蘭縣', '花蓮縣', '台東縣', '澎湖縣', '金門縣', '連江縣'
  ];

  function extractCounty(address) {
    var addr = (address || '').replace(/臺/g, '台');
    for (var i = 0; i < TAIWAN_COUNTIES.length; i++) {
      if (addr.indexOf(TAIWAN_COUNTIES[i]) !== -1) return TAIWAN_COUNTIES[i];
    }
    return null;
  }

  var CUISINE_ALIASES = { '台式': '中式' };
  function normalizeCuisine(raw) { return CUISINE_ALIASES[raw] || raw; }

  function distanceBucket(km) {
    if (km == null) return 'unknown';
    if (km <= 1.0) return '1';
    if (km <= 3.0) return '3';
    if (km <= 5.0) return '5';
    if (km <= 10.0) return '10';
    return 'far';
  }

  function priceBucket(spending) {
    if (!spending || spending <= 0) return 'free';
    if (spending <= 200) return '200';
    if (spending <= 500) return '500';
    if (spending <= 1000) return '1000';
    return 'expensive';
  }

  var api = {
    TAIWAN_COUNTIES: TAIWAN_COUNTIES, extractCounty: extractCounty,
    CUISINE_ALIASES: CUISINE_ALIASES, normalizeCuisine: normalizeCuisine,
    distanceBucket: distanceBucket, priceBucket: priceBucket
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.LotteryLogic = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test lottery_logic.test.js`
Expected: PASS（4 tests）。

- [ ] **Step 5: Commit**

```bash
git add lottery_logic.js lottery_logic.test.js
git commit -m "feat(lottery): 純函式模組骨架 + 分桶/縣市/菜系正規化"
```

---

### Task 2: 覆蓋率 + 自適應 hours 預設

**Files:**
- Modify: `lottery_logic.js`
- Test: `lottery_logic.test.js`

**Interfaces:**
- Produces: `computeCoverage(stores)→{hours:number, distance:number, total:number}`（比例 0..1）、`HOURS_COVERAGE_THRESHOLD`（number, 0.5）、`adaptiveHoursDefault(coverage)→string[]`（hours 篩選 key 陣列）、`ALL_HOURS`（string[]）。

- [ ] **Step 1: Write the failing test**

在 `lottery_logic.test.js` 追加：

```js
test('computeCoverage counts hours and distance ratios', () => {
  const stores = [
    { hours: [{ d: 1, o: '1100', c: '1400' }], distance_km: 1.2 },
    { hours: null, distance_km: 3.0 },
    { hours: [], distance_km: null },
    { hours: null, distance_km: null },
  ];
  const c = L.computeCoverage(stores);
  assert.strictEqual(c.total, 4);
  assert.strictEqual(c.hours, 0.25);      // 只有第一筆有非空 hours
  assert.strictEqual(c.distance, 0.5);    // 前兩筆有距離
  assert.deepStrictEqual(L.computeCoverage([]), { hours: 0, distance: 0, total: 0 });
});

test('adaptiveHoursDefault relaxes when coverage is low', () => {
  const low = L.adaptiveHoursDefault({ hours: 0.0 });
  assert.ok(low.includes('open-now') && low.includes('lunch') && low.includes('unknown'));
  assert.strictEqual(low.length, L.ALL_HOURS.length);   // 全勾
  const high = L.adaptiveHoursDefault({ hours: 0.8 });
  assert.deepStrictEqual(high.sort(), ['open-now', 'unknown'].sort());
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test lottery_logic.test.js`
Expected: FAIL（`L.computeCoverage is not a function`）。

- [ ] **Step 3: Write minimal implementation**

在 `lottery_logic.js` 的 `api` 定義前插入：

```js
  function computeCoverage(stores) {
    var total = stores.length, h = 0, d = 0;
    for (var i = 0; i < total; i++) {
      var s = stores[i];
      if (s.hours && s.hours.length) h++;
      if (s.distance_km != null) d++;
    }
    return { hours: total ? h / total : 0, distance: total ? d / total : 0, total: total };
  }

  var HOURS_COVERAGE_THRESHOLD = 0.5;
  var ALL_HOURS = ['open-now', 'breakfast', 'lunch', 'tea', 'dinner', 'latenight', 'unknown'];

  function adaptiveHoursDefault(coverage) {
    if (coverage.hours < HOURS_COVERAGE_THRESHOLD) return ALL_HOURS.slice();
    return ['open-now', 'unknown'];
  }
```

並在 `api` 物件加入：`computeCoverage: computeCoverage, HOURS_COVERAGE_THRESHOLD: HOURS_COVERAGE_THRESHOLD, ALL_HOURS: ALL_HOURS, adaptiveHoursDefault: adaptiveHoursDefault`。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test lottery_logic.test.js`
Expected: PASS（全部 tests）。

- [ ] **Step 5: Commit**

```bash
git add lottery_logic.js lottery_logic.test.js
git commit -m "feat(lottery): computeCoverage + 自適應 hours 預設"
```

---

### Task 3: 加權（storeWeight + weightedPick）

**Files:**
- Modify: `lottery_logic.js`
- Test: `lottery_logic.test.js`

**Interfaces:**
- Consumes: `Hours.isOpenNow(hours, now)`（來自 `hours_logic.js`）。
- Produces: `storeWeight(store, now, weightOn)→number`、`weightedPick(pool, now, weightOn, rng)→store|null`（`rng` 預設 `Math.random`，回傳 [0,1) 值）。

- [ ] **Step 1: Write the failing test**

在 `lottery_logic.test.js` 追加（沿用 `hours_logic.test.js` 的假時間風格）：

```js
function at(day, hh, mm) { return { getDay: () => day, getHours: () => hh, getMinutes: () => mm }; }
const OPEN_MON_NOON = [{ d: 1, o: '1100', c: '1400' }];

test('storeWeight multiplies distance and open factors', () => {
  const now = at(1, 12, 0);
  // 近(≤1km,×3) × 營業中(×1.8) = 5.4
  assert.ok(Math.abs(L.storeWeight({ distance_km: 0.5, hours: OPEN_MON_NOON }, now, true) - 5.4) < 1e-9);
  // 遠(>10km,×0.4) × 已打烊(×0.5) = 0.2
  assert.ok(Math.abs(L.storeWeight({ distance_km: 20, hours: OPEN_MON_NOON }, at(1, 15, 0), true) - 0.2) < 1e-9);
  // 距離未知(×1.0) × 無hours(×1.0) = 1.0
  assert.strictEqual(L.storeWeight({ distance_km: null, hours: null }, now, true), 1.0);
  // 關閉加權 → 一律 1
  assert.strictEqual(L.storeWeight({ distance_km: 0.5, hours: OPEN_MON_NOON }, now, false), 1);
});

test('weightedPick honors cumulative weights via injected rng', () => {
  const now = at(1, 12, 0);
  const pool = [
    { title: 'A', distance_km: 0.5, hours: OPEN_MON_NOON }, // weight 5.4
    { title: 'B', distance_km: 20, hours: null },           // weight 0.4
  ];
  // sum = 5.8。rng*sum 落在 [0,5.4) → A；落在 [5.4,5.8) → B。
  assert.strictEqual(L.weightedPick(pool, now, true, () => 0.0).title, 'A');
  assert.strictEqual(L.weightedPick(pool, now, true, () => 0.99).title, 'B');
  // 空池 → null
  assert.strictEqual(L.weightedPick([], now, true, () => 0.5), null);
  // 關閉加權 → 等機率索引
  assert.strictEqual(L.weightedPick(pool, now, false, () => 0.0).title, 'A');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test lottery_logic.test.js`
Expected: FAIL（`L.storeWeight is not a function`）。

- [ ] **Step 3: Write minimal implementation**

在 `lottery_logic.js` 插入：

```js
  function storeWeight(store, now, weightOn) {
    if (!weightOn) return 1;
    var km = store.distance_km, wDist;
    if (km == null) wDist = 1.0;
    else if (km <= 1) wDist = 3.0;
    else if (km <= 3) wDist = 2.0;
    else if (km <= 5) wDist = 1.3;
    else if (km <= 10) wDist = 0.8;
    else wDist = 0.4;
    var wOpen;
    if (!store.hours || !store.hours.length) wOpen = 1.0;
    else if (Hours.isOpenNow(store.hours, now)) wOpen = 1.8;
    else wOpen = 0.5;
    return wDist * wOpen;
  }

  function weightedPick(pool, now, weightOn, rng) {
    if (!pool || !pool.length) return null;
    rng = rng || Math.random;
    if (!weightOn) return pool[Math.floor(rng() * pool.length)];
    var weights = [], sum = 0;
    for (var i = 0; i < pool.length; i++) {
      var w = storeWeight(pool[i], now, true);
      if (!(w > 0)) w = 0;
      weights.push(w); sum += w;
    }
    if (sum <= 0) return pool[Math.floor(rng() * pool.length)];
    var r = rng() * sum;
    for (var j = 0; j < pool.length; j++) {
      r -= weights[j];
      if (r < 0) return pool[j];
    }
    return pool[pool.length - 1];
  }
```

並在 `api` 加入 `storeWeight: storeWeight, weightedPick: weightedPick`。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test lottery_logic.test.js`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add lottery_logic.js lottery_logic.test.js
git commit -m "feat(lottery): 加權 storeWeight + weightedPick（rng 可注入）"
```

---

### Task 4: 篩選（storeMatches）

**Files:**
- Modify: `lottery_logic.js`
- Test: `lottery_logic.test.js`

**Interfaces:**
- Consumes: `distanceBucket`、`priceBucket`、`extractCounty`、`normalizeCuisine`、`Hours.matchesHoursFilter(store, now, Set)`。
- Produces: `storeMatches(store, filters, now)→bool`。`filters` 形狀：`{ visit:'all'|'yes'|'no', cuisines:Set<string>|null, distances:Set, prices:Set, counties:Set(含 'unknown'), hours:Set }`。`cuisines` 為 `null` 代表全菜系（不過濾）。

- [ ] **Step 1: Write the failing test**

在 `lottery_logic.test.js` 追加：

```js
test('storeMatches applies each hard filter', () => {
  const now = at(1, 12, 0);
  const base = {
    visit: 'all', cuisines: null,
    distances: new Set(['1', '3', '5', '10', 'far', 'unknown']),
    prices: new Set(['200', '500', '1000', 'expensive', 'free']),
    counties: new Set(['新竹市', 'unknown']),
    hours: new Set(L.ALL_HOURS),
  };
  const store = {
    title: 'X', address: '新竹市東區', cuisine_type: '日式',
    distance_km: 2.0, avg_spending: 300, visited: '否', hours: null,
  };
  assert.strictEqual(L.storeMatches(store, base, now), true);
  // 回訪不合
  assert.strictEqual(L.storeMatches(store, Object.assign({}, base, { visit: 'yes' }), now), false);
  // 菜系不含
  assert.strictEqual(L.storeMatches(store, Object.assign({}, base, { cuisines: new Set(['中式']) }), now), false);
  // 台式→中式 別名命中
  assert.strictEqual(L.storeMatches(Object.assign({}, store, { cuisine_type: '台式' }),
    Object.assign({}, base, { cuisines: new Set(['中式']) }), now), true);
  // 距離桶不含（2.0→'3'）
  assert.strictEqual(L.storeMatches(store, Object.assign({}, base, { distances: new Set(['1']) }), now), false);
  // 價格桶不含（300→'500'）
  assert.strictEqual(L.storeMatches(store, Object.assign({}, base, { prices: new Set(['200']) }), now), false);
  // 縣市：非台灣店（county=null）需 counties 含 'unknown'
  const sg = Object.assign({}, store, { address: 'Singapore' });
  assert.strictEqual(L.storeMatches(sg, base, now), true);               // base 含 'unknown' → 通過
  assert.strictEqual(L.storeMatches(sg, Object.assign({}, base, { counties: new Set(['新竹市']) }), now), false); // 不含 unknown → 排除
  // 無 hours 只經 'unknown'
  assert.strictEqual(L.storeMatches(store, Object.assign({}, base, { hours: new Set(['open-now']) }), now), false);
  assert.strictEqual(L.storeMatches(store, Object.assign({}, base, { hours: new Set(['unknown']) }), now), true);
});

test('storeMatches: no cuisine_type needs 其他 when cuisines is a Set', () => {
  const now = at(1, 12, 0);
  const base = {
    visit: 'all', cuisines: new Set(['日式']),
    distances: new Set(['unknown']), prices: new Set(['free']),
    counties: new Set(['unknown']), hours: new Set(['unknown']),
  };
  const noCuisine = { address: '', cuisine_type: '', distance_km: null, avg_spending: 0, visited: '是', hours: null };
  assert.strictEqual(L.storeMatches(noCuisine, base, now), false);
  assert.strictEqual(L.storeMatches(noCuisine, Object.assign({}, base, { cuisines: new Set(['其他']) }), now), true);
  assert.strictEqual(L.storeMatches(noCuisine, Object.assign({}, base, { cuisines: null }), now), true);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test lottery_logic.test.js`
Expected: FAIL（`L.storeMatches is not a function`）。

- [ ] **Step 3: Write minimal implementation**

在 `lottery_logic.js` 插入：

```js
  function storeMatches(store, filters, now) {
    if (filters.visit === 'yes' && store.visited !== '是') return false;
    if (filters.visit === 'no' && store.visited !== '否') return false;

    if (filters.cuisines) {
      if (!store.cuisine_type) {
        if (!filters.cuisines.has('其他')) return false;
      } else {
        var cs = store.cuisine_type.split(',').map(function (c) { return normalizeCuisine(c.trim()); });
        var ok = cs.some(function (c) { return filters.cuisines.has(c); });
        if (!ok) return false;
      }
    }

    if (!filters.distances.has(distanceBucket(store.distance_km))) return false;
    if (!filters.prices.has(priceBucket(store.avg_spending))) return false;

    var county = extractCounty(store.address);
    if (county) { if (!filters.counties.has(county)) return false; }
    else { if (!filters.counties.has('unknown')) return false; }

    if (!Hours.matchesHoursFilter(store, now, filters.hours)) return false;
    return true;
  }
```

並在 `api` 加入 `storeMatches: storeMatches`。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test lottery_logic.test.js`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add lottery_logic.js lottery_logic.test.js
git commit -m "feat(lottery): storeMatches 硬篩（回訪/菜系/距離/價格/縣市/hours）"
```

---

### Task 5: 情境預設（PRESET_SPECS + resolvePreset）

**Files:**
- Modify: `lottery_logic.js`
- Test: `lottery_logic.test.js`

**Interfaces:**
- Consumes: `adaptiveHoursDefault(coverage)`。
- Produces: `PRESET_NAMES`（string[]，順序＝顯示順序）、`resolvePreset(name, coverage, dataCounties)→filters`（filters 形狀同 Task 4，另含 `weightOn:bool`）。`dataCounties` 為資料中實際出現的縣市字串陣列。

- [ ] **Step 1: Write the failing test**

在 `lottery_logic.test.js` 追加：

```js
test('resolvePreset builds 智慧推薦 base with adaptive hours + home counties', () => {
  const cov = { hours: 0.0, distance: 0.3 };  // hours 覆蓋低 → 全勾
  const f = L.resolvePreset('智慧推薦', cov, ['新竹市', '台北市']);
  assert.strictEqual(f.visit, 'all');
  assert.strictEqual(f.cuisines, null);
  assert.strictEqual(f.weightOn, true);
  assert.deepStrictEqual([...f.counties].sort(), ['新竹市'].sort());   // 只取住家縣市中資料存在者
  assert.ok(f.distances.has('1') && f.distances.has('far') && f.distances.has('unknown'));
  assert.deepStrictEqual([...f.prices].sort(), ['200', '500', 'free'].sort());
  assert.strictEqual(f.hours.size, L.ALL_HOURS.length);              // 自適應全勾
});

test('resolvePreset variants', () => {
  const cov = { hours: 0.9, distance: 0.9 };  // 高覆蓋 → 自適應 {open-now,unknown}
  const dc = ['新竹市', '台北市'];
  // 附近：距離收窄含 unknown
  assert.deepStrictEqual([...L.resolvePreset('附近', cov, dc).distances].sort(),
    ['1', '3', 'unknown'].sort());
  // 沒去過：visit=no
  assert.strictEqual(L.resolvePreset('沒去過', cov, dc).visit, 'no');
  // 現在營業：hours={open-now,unknown}
  assert.deepStrictEqual([...L.resolvePreset('現在營業', cov, dc).hours].sort(),
    ['open-now', 'unknown'].sort());
  // 全部隨機：全開、含資料所有縣市+unknown、關加權
  const rnd = L.resolvePreset('全部隨機', cov, dc);
  assert.strictEqual(rnd.weightOn, false);
  assert.ok(rnd.counties.has('新竹市') && rnd.counties.has('台北市') && rnd.counties.has('unknown'));
  assert.strictEqual(rnd.hours.size, L.ALL_HOURS.length);
  assert.strictEqual(rnd.cuisines, null);
});

test('PRESET_NAMES order', () => {
  assert.deepStrictEqual(L.PRESET_NAMES,
    ['智慧推薦', '附近', '沒去過', '現在營業', '全部隨機']);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test lottery_logic.test.js`
Expected: FAIL（`L.resolvePreset is not a function`）。

- [ ] **Step 3: Write minimal implementation**

在 `lottery_logic.js` 插入：

```js
  var PRESET_NAMES = ['智慧推薦', '附近', '沒去過', '現在營業', '全部隨機'];

  function resolvePreset(name, coverage, dataCounties) {
    dataCounties = dataCounties || [];
    var homeCounties = ['新竹市', '新竹縣'].filter(function (c) {
      return dataCounties.indexOf(c) !== -1;
    });
    var f = {
      visit: 'all',
      cuisines: null,
      distances: new Set(['1', '3', '5', '10', 'far', 'unknown']),
      prices: new Set(['200', '500', 'free']),
      counties: new Set(homeCounties),
      hours: new Set(adaptiveHoursDefault(coverage)),
      weightOn: true,
    };
    if (name === '附近') {
      f.distances = new Set(['1', '3', 'unknown']);
    } else if (name === '沒去過') {
      f.visit = 'no';
    } else if (name === '現在營業') {
      f.hours = new Set(['open-now', 'unknown']);
    } else if (name === '全部隨機') {
      f.distances = new Set(['1', '3', '5', '10', 'far', 'unknown']);
      f.prices = new Set(['200', '500', '1000', 'expensive', 'free']);
      f.counties = new Set(dataCounties.concat(['unknown']));
      f.hours = new Set(ALL_HOURS);
      f.weightOn = false;
    }
    return f;
  }
```

並在 `api` 加入 `PRESET_NAMES: PRESET_NAMES, resolvePreset: resolvePreset`。

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test lottery_logic.test.js && node --test hours_logic.test.js`
Expected: PASS（兩檔全綠）。

- [ ] **Step 5: Commit**

```bash
git add lottery_logic.js lottery_logic.test.js
git commit -m "feat(lottery): 五情境 PRESET + resolvePreset（自適應/住家縣市）"
```

---

### Task 6: lottery.html — 視覺 B（暖食慾）+ 版面 L3 骨架

**Files:**
- Modify: `lottery.html`（`<head>` 內 `:root` 與樣式、`<body>` 結構、`<script src>` 引入）

**Interfaces:**
- Consumes: 新增 `<script src="lottery_logic.js"></script>`（置於 `hours_logic.js` 之後、主 `<script>` 之前）。
- Produces: 供 Task 7/8 綁定的 DOM id/class：`#preset-bar`、`.preset-chip[data-preset]`、`#advanced-toggle`、`#advanced-panel`、`#weight-toggle`、既有 `#matching-count`、`#board`、`#result-card` 等維持。

> 本任務為靜態結構＋配色，不改行為邏輯（Task 7/8 再接線）。驗證＝瀏覽器目視。

- [ ] **Step 1: 換色票（`:root`）**

將 `<head>` `:root` 換成暖食慾配色（保留變數名，讓既有樣式沿用）：

```css
:root {
  --bg-gradient: linear-gradient(135deg, #1a1210 0%, #2b1a12 100%);
  --panel-bg: rgba(43, 26, 18, 0.55);
  --border-color: rgba(255, 237, 213, 0.10);
  --border-hover: rgba(255, 237, 213, 0.22);
  --text-primary: #fff7ed;
  --text-secondary: #a8836b;
  --accent-color: #f97316;
  --accent-glow: rgba(249, 115, 22, 0.4);
  --accent-gradient: linear-gradient(135deg, #f97316 0%, #ef4444 100%);
  --accent-secondary: #fb923c;
  --card-bg: rgba(26, 18, 16, 0.6);
  --shadow-lg: 0 10px 25px -5px rgba(0,0,0,0.4), 0 8px 10px -6px rgba(0,0,0,0.4);
  --shadow-glow: 0 0 30px rgba(249, 115, 22, 0.2);
}
```

同步把 `header h1` 的漸層改暖色：`background: linear-gradient(135deg, #fb923c 0%, #f97316 50%, #ef4444 100%);`；`.orb-1` 保留、`.orb-2` 的 radial 改 `rgba(239,68,68,0.15)`。標題文案 `<h1>` 可改為「🍜 今天吃什麼」、副標保留。

- [ ] **Step 2: 版面改為 L3（單欄、抽籤為主）**

把 `.main-container` 由 `grid-template-columns: 350px 1fr` 改為單欄置中：

```css
.main-container { max-width: 720px; display: flex; flex-direction: column; gap: 1.25rem; }
```

移除 `<aside class="sidebar">…</aside>` 的側欄定位用法，改為：在 `.main-container` 內，`draw-area` 之上放**情境列**與**進階面板**。將原本 sidebar 內的六個 `.filter-section` 整段搬進 `#advanced-panel`（見 Step 4），sidebar 容器可移除或改成 `#advanced-panel` 的內層。

- [ ] **Step 3: 加入情境快捷列（chips）**

在 `.main-container` 最上方（counter 之前）插入：

```html
<div id="preset-bar" class="preset-bar">
  <!-- chips 由 JS 依 LotteryLogic.PRESET_NAMES 產生；此處僅容器 -->
</div>
```

CSS：

```css
.preset-bar { display: flex; gap: 0.5rem; overflow-x: auto; padding: 0.25rem; -webkit-overflow-scrolling: touch; }
.preset-chip { white-space: nowrap; padding: 0.5rem 1rem; border-radius: 999px; font-size: 0.9rem;
  font-weight: 600; cursor: pointer; border: 1px solid var(--border-color);
  background: rgba(43,26,18,0.5); color: var(--text-secondary); transition: all 0.2s ease; }
.preset-chip:hover { color: var(--text-primary); border-color: var(--border-hover); }
.preset-chip.active { background: var(--accent-gradient); color: #fff; border-color: transparent;
  box-shadow: 0 6px 16px -4px var(--accent-glow); }
.preset-chip.custom { font-style: italic; }
```

- [ ] **Step 4: 加入可收合進階面板**

在情境列之後、counter 之前插入折疊容器，並把原 sidebar 的六個 `.filter-section`（回訪/營業時間/菜系/距離/人均/縣市，原樣搬入）放進 `#advanced-panel`，最上方新增加權開關：

```html
<div class="advanced">
  <button type="button" id="advanced-toggle" class="advanced-toggle" aria-expanded="false">
    <span>⚙ 進階篩選</span><span class="chev">▾</span>
  </button>
  <div id="advanced-panel" class="advanced-panel" hidden>
    <label class="checkbox-label" style="margin-bottom:1rem;">
      <input type="checkbox" id="weight-toggle" checked> ⚡ 加權抽籤（近／營業中優先）
    </label>
    <!-- 原 sidebar 內六個 .filter-section 全部搬到這裡 -->
  </div>
</div>
```

CSS：

```css
.advanced-toggle { width: 100%; display: flex; justify-content: space-between; align-items: center;
  background: var(--panel-bg); border: 1px solid var(--border-color); color: var(--text-primary);
  border-radius: 12px; padding: 0.85rem 1.1rem; font-size: 1rem; font-weight: 600; cursor: pointer; }
.advanced-toggle .chev { transition: transform 0.2s ease; }
.advanced-toggle[aria-expanded="true"] .chev { transform: rotate(180deg); }
.advanced-panel { background: var(--panel-bg); backdrop-filter: blur(12px); border: 1px solid var(--border-color);
  border-top: none; border-radius: 0 0 16px 16px; padding: 1.5rem; margin-top: -6px; }
.advanced-panel[hidden] { display: none; }
```

- [ ] **Step 5: 引入模組 + 目視驗證**

在 `hours_logic.js` 的 `<script>` 後、主 `<script>` 前加入 `<script src="lottery_logic.js"></script>`。用瀏覽器開 `lottery.html`（`file://` 或本地伺服器皆可）。

Expected（目視）：整頁為暖色炭黑；標題暖橘漸層；一條（暫時空的）情境列容器；「⚙ 進階篩選」按鈕點擊可展開/收合，內含加權開關與原六組篩選；大抽籤板置中。此時抽籤行為可能因尚未接線而異常，屬正常（下一任務修）。

- [ ] **Step 6: Commit**

```bash
git add lottery.html
git commit -m "style(lottery): 暖食慾配色 + L3 單欄版面（情境列/進階面板骨架）"
```

---

### Task 7: lottery.html — 接線情境鍵 / 進階面板 / 計數

**Files:**
- Modify: `lottery.html`（主 `<script>`）

**Interfaces:**
- Consumes: `window.LotteryLogic`（`PRESET_NAMES`、`resolvePreset`、`computeCoverage`、`storeMatches`、`extractCounty`、`normalizeCuisine`、`distanceBucket`、`priceBucket`）、`window.HoursLogic`。
- Produces: 全域 `filteredStores`（供 Task 8 抽籤）、`getCurrentFilters()→filters`、`applyPreset(name)`、`updateFilters()`；`window.APP_COVERAGE`、`window.DATA_COUNTIES`。

> 目標：以 LotteryLogic 取代原內嵌的 `extractCounty/normalizeCuisine/updateFilters` 重複邏輯；情境鍵套用、手動改動 →「自訂」、計數即時更新。驗證＝瀏覽器目視 + console。

- [ ] **Step 1: 移除重複、改用模組 + 計算覆蓋率/縣市**

刪除主 `<script>` 內重複的 `TAIWAN_COUNTIES`、`extractCounty`、`CUISINE_ALIASES`、`normalizeCuisine` 定義，改用 `const LL = window.LotteryLogic;` 並在初始化算：

```js
const LL = window.LotteryLogic;
window.APP_COVERAGE = LL.computeCoverage(stores);
const DATA_COUNTIES = Array.from(new Set(
  stores.map(s => LL.extractCounty(s.address)).filter(Boolean)
));
window.DATA_COUNTIES = DATA_COUNTIES;
```

`populateCountyFilters`/`populateCuisineFilters` 改呼叫 `LL.extractCounty`/`LL.normalizeCuisine`（其餘不變）。

- [ ] **Step 2: 讀取當前 DOM 篩選狀態 → filters**

新增 `getCurrentFilters()`，把 DOM 勾選狀態組成 Task 4 的 `filters` 形狀：

```js
function getCurrentFilters() {
  const visit = document.querySelector('input[name="visit-status"]:checked').value;
  const cuisineBoxes = Array.from(document.querySelectorAll('input[name="cuisine"]'));
  const allCuisineChecked = cuisineBoxes.every(b => b.checked);
  const cuisines = allCuisineChecked ? null
    : new Set(cuisineBoxes.filter(b => b.checked).map(b => b.value));
  const setOf = name => new Set(
    Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map(b => b.value));
  return {
    visit,
    cuisines,
    distances: setOf('distance'),
    prices: setOf('price'),
    counties: setOf('county'),      // 'unknown' 已是其中一個 checkbox value
    hours: setOf('hours'),
  };
}
```

- [ ] **Step 3: 重寫 updateFilters 用 storeMatches**

把 `updateFilters()` 內的過濾主體換成：

```js
function updateFilters() {
  const filters = getCurrentFilters();
  const now = new Date();
  filteredStores = stores.filter(s => LL.storeMatches(s, filters, now));
  const countEl = document.getElementById('matching-count');
  if (filteredStores.length === 0) {
    countEl.innerHTML = `0 <span style="color:var(--text-secondary);font-size:0.85rem;font-weight:normal;">(無符合，將從全部抽)</span>`;
    document.getElementById('btn-start').disabled = stores.length === 0;
  } else {
    countEl.textContent = String(filteredStores.length);
    document.getElementById('btn-start').disabled = false;
  }
}
```

- [ ] **Step 4: 渲染情境鍵 + applyPreset**

新增 chip 渲染與套用邏輯（含表情符號對照與自適應提示）：

```js
const PRESET_EMOJI = { '智慧推薦': '🎯', '附近': '📍', '沒去過': '🆕', '現在營業': '🍜', '全部隨機': '🎲' };
let activePreset = null;

function renderPresetBar() {
  const bar = document.getElementById('preset-bar');
  bar.innerHTML = '';
  LL.PRESET_NAMES.forEach(name => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'preset-chip';
    chip.dataset.preset = name;
    chip.textContent = `${PRESET_EMOJI[name] || ''} ${name}`;
    chip.addEventListener('click', () => applyPreset(name));
    bar.appendChild(chip);
  });
}

function setCheckboxes(name, values /* Set|null=all */) {
  document.querySelectorAll(`input[name="${name}"]`).forEach(b => {
    b.checked = (values == null) ? true : values.has(b.value);
  });
}

function applyPreset(name) {
  const f = LL.resolvePreset(name, window.APP_COVERAGE, window.DATA_COUNTIES);
  document.querySelector(`input[name="visit-status"][value="${f.visit}"]`).checked = true;  // f.visit ∈ {all,yes,no}，對應 radio value
  setCheckboxes('cuisine', f.cuisines);       // null → 全勾
  setCheckboxes('distance', f.distances);
  setCheckboxes('price', f.prices);
  setCheckboxes('county', f.counties);
  setCheckboxes('hours', f.hours);
  document.getElementById('weight-toggle').checked = f.weightOn;
  activePreset = name;
  highlightPreset();
  updateFilters();
}

function highlightPreset() {
  document.querySelectorAll('.preset-chip').forEach(c => {
    c.classList.toggle('active', c.dataset.preset === activePreset);
    c.classList.remove('custom');
  });
  if (!activePreset) {
    // 顯示一個「自訂」提示：把第一個 chip 標為 custom 文字
  }
}
```

- [ ] **Step 5: 手動改動 → 自訂**

在既有「為每個 checkbox/radio 綁 change → updateFilters」處，額外把 `activePreset` 設為 `null` 並更新高亮（但**由 applyPreset 觸發的程式性變更不可誤判**，故用旗標）：

```js
let applyingPreset = false;
// applyPreset 內：開頭 applyingPreset = true; 結尾 applyingPreset = false;
document.querySelectorAll('input[type="checkbox"], input[type="radio"]').forEach(el => {
  el.addEventListener('change', () => {
    if (!applyingPreset) { activePreset = null; highlightPreset(); }
    updateFilters();
  });
});
```

並在 `highlightPreset()` 裡，`activePreset===null` 時於情境列顯示一枚 `自訂 ✎`（可用一個固定的 `.preset-chip.custom.active` 節點或在 bar 前插入 label）。最小作法：在 `#preset-bar` 前放一個 `<span id="custom-flag" class="preset-chip custom" hidden>✎ 自訂</span>`，`highlightPreset` 依 `activePreset` 切 `hidden`。

- [ ] **Step 6: 初始化：載入即套「智慧推薦」**

把檔尾初始化改為：

```js
populateCuisineFilters();
populateCountyFilters();
renderPresetBar();
// 進階面板收合鈕
const at = document.getElementById('advanced-toggle');
at.addEventListener('click', () => {
  const panel = document.getElementById('advanced-panel');
  const open = panel.hasAttribute('hidden');
  if (open) panel.removeAttribute('hidden'); else panel.setAttribute('hidden', '');
  at.setAttribute('aria-expanded', String(open));
});
applyPreset('智慧推薦');   // 載入即套 → 不會空池
```

- [ ] **Step 7: 目視 + console 驗證**

瀏覽器開 `lottery.html`：
- Expected：載入時「🎯 智慧推薦」高亮，計數 > 0（現況資料 hours 覆蓋 0% → 自適應全勾，不空池）。
- 點「📍 附近」「🆕 沒去過」「🎲 全部隨機」→ 計數隨之變動、高亮切換。
- 展開進階面板手動取消某菜系 → 高亮清除、出現「✎ 自訂」、計數更新。
- console：`window.APP_COVERAGE` 顯示 `{hours:0, distance:~0.33, ...}`。

- [ ] **Step 8: Commit**

```bash
git add lottery.html
git commit -m "feat(lottery): 情境鍵/進階面板/計數改用 LotteryLogic（自訂狀態）"
```

---

### Task 8: lottery.html — 加權抽籤 / 結果卡 / 自適應提示

**Files:**
- Modify: `lottery.html`（主 `<script>`、結果卡標籤）

**Interfaces:**
- Consumes: `LL.weightedPick(pool, now, weightOn, rng)`、`HoursLogic.isOpenNow`、全域 `filteredStores`、`stores`、`window.APP_COVERAGE`。
- Produces: 最終抽籤結果渲染（沿用結果卡 DOM）。

> 保留既有 slot-machine 動畫與 confetti；只改「最終贏家的選法（改加權）」與結果卡暖色標籤、加入自適應提示。驗證＝瀏覽器目視。

- [ ] **Step 1: 最終贏家改用 weightedPick**

`displayWinner` 內，把 `const winner = pool[Math.floor(Math.random()*pool.length)];` 改為：

```js
const weightOn = document.getElementById('weight-toggle').checked;
const winner = LL.weightedPick(pool, new Date(), weightOn, Math.random);
if (!winner) return;
```

（`drawLottery` 的 fallback 判斷維持：`filteredStores` 空 → `drawPool = stores; isFallback = true`。）

- [ ] **Step 2: 結果卡營業狀態標籤（沿用既有 hoursBadge）**

確認 `displayWinner` 內既有的 `winner-tag-hours` 區塊維持（營業中／已打烊／未知三態，用 `HoursLogic.isOpenNow`）。距離標籤文案統一為 `距離住家 X km`；價格 `人均 NT$ X` / `未知/免費`。（此區大多沿用既有程式，僅確保配色沿用 CSS 變數而非硬編色，見 Step 3。）

- [ ] **Step 3: 結果卡暖色化**

檢查 `.result-card`、`.badge-*` 是否吃 `:root` 變數；若有硬編的舊藍紫色（如 `#818cf8`），改為暖色等價（`badge-cuisine` 用 `--accent-color` 系、`badge-distance` 用 `#fb923c` 系、`badge-price` 用 `#facc15` 保留、`badge-visit` 用 `--accent-secondary`）。confetti 顏色陣列改為暖色：`['#f97316','#ef4444','#fb923c','#facc15','#fca5a5']`。

- [ ] **Step 4: 自適應提示**

在 `renderPresetBar()` 之後，若 `window.APP_COVERAGE.hours < LL.HOURS_COVERAGE_THRESHOLD`，於「現在營業」chip 加上 `title`（tooltip）並在其下方顯示小字提示：

```js
if (window.APP_COVERAGE.hours < LL.HOURS_COVERAGE_THRESHOLD) {
  const chip = document.querySelector('.preset-chip[data-preset="現在營業"]');
  if (chip) chip.title = '營業時間資料未匯入，此模式已用寬鬆判定';
  const hint = document.createElement('p');
  hint.style.cssText = 'color:var(--text-secondary);font-size:0.8rem;margin:0.25rem 0.25rem 0;';
  hint.textContent = 'ℹ️ 營業時間資料尚未匯入，「營業中」相關以寬鬆模式處理。';
  document.getElementById('preset-bar').after(hint);
}
```

- [ ] **Step 5: 目視驗證（完整抽籤流程）**

瀏覽器開 `lottery.html`：
- 點「✨ 開始抽籤」→ slot-machine 動畫 → 結果卡出現（暖色）、confetti 為暖色。
- 結果卡含菜系／營業狀態／距離／均消／回訪標籤、地址·來源·備註、「在 Google 地圖開啟」可點、「再抽一次」可重抽。
- 反覆多抽數次：關掉「⚡ 加權抽籤」再抽，觀察分佈更均勻（近店不再明顯偏多）。
- 因現況 hours 0%，情境列下方顯示自適應提示小字。

- [ ] **Step 6: 全測試回歸 + Commit**

```bash
node --test lottery_logic.test.js && node --test hours_logic.test.js
git add lottery.html
git commit -m "feat(lottery): 加權抽籤選贏家 + 結果卡暖色化 + 自適應提示"
```

Expected：兩測試檔全綠；抽籤流程完整。

---

## Self-Review

**Spec coverage：**
- §2 修空池／自適應 → Task 2（adaptiveHoursDefault）、Task 5（resolvePreset）、Task 7（載入即套智慧推薦）。
- §4 加權公式 → Task 3。§5 自適應門檻 → Task 2。§6 五情境 → Task 5 + Task 7。
- §7 版面 L3／視覺 B／結果卡／自適應提示 → Task 6、Task 8。
- §8 元件切分（LotteryLogic vs DOM glue）→ Task 1–5（模組）、Task 6–8（glue）。
- §9 測試 → Task 1–5 各自 node:test；Task 5/8 跑回歸。
- 資料契約不變、不動 hours_logic/管線 → 全任務僅新增 `lottery_logic.*` 與改 `lottery.html`。✔ 無遺漏。

**Placeholder scan：** 各程式步驟均附實際碼；DOM 任務的「搬移原 filter-section」為明確指令（原樣搬入 `#advanced-panel`）。無 TBD/TODO。

**Type consistency：** `filters` 形狀（`visit/cuisines/distances/prices/counties/hours(+weightOn)`）在 Task 4/5/7 一致；`resolvePreset(name, coverage, dataCounties)`、`weightedPick(pool, now, weightOn, rng)`、`storeMatches(store, filters, now)`、`computeCoverage(stores)`、`adaptiveHoursDefault(coverage)` 命名前後一致；`cuisines=null` 代表全菜系於 Task 4（storeMatches 略過）、Task 5（resolvePreset 產出）、Task 7（`setCheckboxes(null)`→全勾）一致處理。
