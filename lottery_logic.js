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
