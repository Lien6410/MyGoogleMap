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
