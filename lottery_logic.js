// lottery_logic.js — 純函式：抽籤的分桶/覆蓋率/加權/篩選/情境預設。瀏覽器與 Node 皆可用。
(function (global) {
  'use strict';

  // Hours：hours_logic.js 的營業判斷；Task 3/4 的 storeWeight/storeMatches 會用到（此處先取得）。
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

  // 與 mygmap/export.py 的 POOL_LISTS / VISITED_LISTS 對應：抽籤池就是這四個清單，
  // 「想去的地點」＝沒去過，其餘三個＝去過。
  var POOL_LISTS = ['想去的地點', '回訪', '常用早餐', '常用晚餐'];
  var VISITED_LISTS = ['回訪', '常用早餐', '常用晚餐'];

  function storeLists(store) {
    var raw = (store && store.source_list) || '';
    if (!raw) return [];
    return raw.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  }

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

  function storeMatches(store, filters, now) {
    // 來源清單：任一清單被勾就通過。全不勾（或未提供）視同全勾——
    // 手滑清空不該變成解不開的空池。
    if (filters.lists && filters.lists.size) {
      var ls = storeLists(store);
      var hit = ls.some(function (l) { return filters.lists.has(l); });
      if (!hit) return false;
    }

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

  function sortCandidates(stores) {
    // 近的排前面，距離未知的排最後，同距離按店名。回傳新陣列，不動原陣列。
    return (stores || []).slice().sort(function (a, b) {
      var da = a.distance_km, db = b.distance_km;
      if (da == null && db != null) return 1;
      if (da != null && db == null) return -1;
      if (da != null && db != null && da !== db) return da - db;
      return String(a.title || '').localeCompare(String(b.title || ''), 'zh-Hant');
    });
  }

  var PRESET_NAMES = ['智慧推薦', '附近', '沒去過', '現在營業', '全部隨機'];

  function resolvePreset(name, coverage, dataCounties) {
    dataCounties = dataCounties || [];
    var homeCounties = ['新竹市', '新竹縣'].filter(function (c) {
      return dataCounties.indexOf(c) !== -1;
    });
    var f = {
      lists: new Set(POOL_LISTS),
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
      f.lists = new Set(['想去的地點']);
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

  var api = {
    TAIWAN_COUNTIES: TAIWAN_COUNTIES, extractCounty: extractCounty,
    CUISINE_ALIASES: CUISINE_ALIASES, normalizeCuisine: normalizeCuisine,
    POOL_LISTS: POOL_LISTS, VISITED_LISTS: VISITED_LISTS, storeLists: storeLists,
    sortCandidates: sortCandidates,
    distanceBucket: distanceBucket, priceBucket: priceBucket,
    computeCoverage: computeCoverage, HOURS_COVERAGE_THRESHOLD: HOURS_COVERAGE_THRESHOLD, ALL_HOURS: ALL_HOURS, adaptiveHoursDefault: adaptiveHoursDefault,
    storeWeight: storeWeight, weightedPick: weightedPick, storeMatches: storeMatches,
    PRESET_NAMES: PRESET_NAMES, resolvePreset: resolvePreset
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.LotteryLogic = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
