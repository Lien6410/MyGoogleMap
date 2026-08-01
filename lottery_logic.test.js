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
});
