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
