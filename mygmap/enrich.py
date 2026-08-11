import logging
import time

from psycopg.types.json import Json

from .gapi import haversine_distance
from .places import extract_cid

log = logging.getLogger(__name__)


def _pending_places(conn, limit=None):
    sql = ("SELECT place_key, title, address, url FROM places "
           "WHERE enriched_at IS NULL ORDER BY place_key")
    params = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (int(limit),)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [{'place_key': r[0], 'title': r[1], 'address': r[2], 'url': r[3]}
                for r in cur.fetchall()]


def _update_place(conn, place_key, det, address, lat, lng, hours, hours_text, distance_km, mark_enriched):
    """只寫「這次真的查到」的欄位。

    Find Place 偶爾失敗（逾時／相似度不足）會讓 hours 回 None；若無條件寫入，
    就會把 backfill_hours 補好的營業時間洗掉。座標與距離同理（無住家地址時
    distance_km 為 None）。分類與消費一律寫入，那正是 enrich 的目的。
    """
    sets = ["cuisine_type = %s", "avg_spending = %s",
            "address = COALESCE(NULLIF(%s, ''), address)"]
    params = [det.get('types'), det.get('avg_spending'), address]
    if lat is not None and lng is not None:
        sets += ["lat = %s", "lng = %s"]
        params += [lat, lng]
    if hours is not None:
        sets += ["hours = %s", "hours_text = %s"]
        params += [Json(hours), hours_text or '']
    if distance_km is not None:
        sets.append("distance_km = %s")
        params.append(distance_km)
    sets.append("updated_at = now()")
    if mark_enriched:
        sets.append("enriched_at = now()")
    params.append(place_key)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE places SET {', '.join(sets)} WHERE place_key = %s", params)


def enrich_pending(conn, classify, *, place_details=None,
                   home_lat=None, home_lng=None, batch_size=20, limit=None,
                   mark_enriched=True, batch_delay=0):
    pending = _pending_places(conn, limit)
    total = len(pending)
    log.info("enrichment：待補齊 %d 家", total)
    done = 0
    try:
        for i in range(0, total, batch_size):
            batch = pending[i:i + batch_size]
            items = [{'title': p['title'], 'address': p['address'] or ''} for p in batch]
            results = classify(items)
            for p, det in zip(batch, results):
                lat, lng = det.get('lat'), det.get('lng')
                address = p['address'] or det.get('address') or ''
                hours, hours_text = None, ''
                cid = extract_cid(p['url'] or '')
                if place_details and cid:
                    # hex CID 無法直接查 Place Details，place_details 內部改以
                    # Find Place(店名+地址) 解析正規 place_id 再查營業時間。
                    pd = place_details(p['title'], address)
                    if pd.get('address'):
                        address = pd['address']
                    hours = pd.get('hours')
                    hours_text = pd.get('hours_text', '')
                distance_km = (haversine_distance(home_lat, home_lng, lat, lng)
                               if home_lat is not None and home_lng is not None else None)
                _update_place(conn, p['place_key'], det, address, lat, lng,
                              hours, hours_text, distance_km, mark_enriched)
                done += 1
            # 每批就 commit：API 已計費，中途炸掉（例如 REQUEST_DENIED）不該讓成果全丟
            conn.commit()
            if total:
                log.info("  enrich %d/%d", done, total)
            if batch_delay and i + batch_size < total:
                log.info("  節流：等待 %s 秒（避免觸發 API 速率限制）…", batch_delay)
                time.sleep(batch_delay)
    except Exception:
        conn.commit()       # 保住已完成（且已計費）的部分後再往上拋
        raise
    conn.commit()
    return done
