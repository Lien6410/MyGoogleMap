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
  // 邊界：剛好等於門檻 0.5 → 收緊模式（非放寬）
  assert.deepStrictEqual(L.adaptiveHoursDefault({ hours: 0.5 }).sort(),
    ['open-now', 'unknown'].sort());
});

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
