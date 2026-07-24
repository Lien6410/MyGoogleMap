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
