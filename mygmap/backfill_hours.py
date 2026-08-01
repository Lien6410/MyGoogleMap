"""backfill_hours — 定向補營業時間。

背景：早期一次含金鑰的 enrich 已把所有 places 標記 enriched_at，但當時
place_details 用 hex CID 當 place_id（Places API 回 INVALID_REQUEST），故 hours 全空。
修正後 enrich 的閘門是 `enriched_at IS NULL`，不會再回頭補這些「已 enrich 但 hours 空」的店。

本模組只針對「有 CID 且 hours 為空」的店，用修正後的 make_place_details
（店名+地址 → Find Place → 正規 place_id → Place Details）補 hours + 地址，
**不重跑 Gemini 分類、不重匯入**，並每批 commit 以利長跑中斷後保留進度。
"""
import logging
import time

from psycopg.types.json import Json

from .places import extract_cid

log = logging.getLogger(__name__)


def _pending_hours(conn, limit=None):
    sql = ("SELECT place_key, title, address, url FROM places "
           "WHERE hours IS NULL AND url IS NOT NULL AND url <> '' "
           "ORDER BY place_key")
    params = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (int(limit),)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    # 只留真有 CID 者（＝真實 GMaps 店），與 enrich 的閘門一致
    return [{'place_key': r[0], 'title': r[1], 'address': r[2], 'url': r[3]}
            for r in rows if extract_cid(r[3] or '')]


def _update_hours(conn, place_key, hours, hours_text, address):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE places SET hours = %s, hours_text = %s, "
            "address = COALESCE(NULLIF(%s, ''), address), updated_at = now() "
            "WHERE place_key = %s",
            (Json(hours), hours_text, address or '', place_key),
        )


def backfill_hours(conn, place_details, *, limit=None, request_delay=0, commit_every=25):
    """對「有 CID 且 hours 空」的店補營業時間。

    place_details: 可注入的 (name, address) -> {"address","hours","hours_text"}
                   （正式用 gapi.make_place_details(maps_key)）。
    只有查到 hours 才寫入（查無不覆寫、不誤清）。回傳成功補齊的家數。
    """
    pending = _pending_hours(conn, limit)
    total = len(pending)
    log.info("補營業時間：候選 %d 家（有 CID 且 hours 空）", total)
    updated = 0
    for idx, p in enumerate(pending, 1):
        pd = place_details(p['title'], p['address'] or '')
        if pd.get('hours'):
            _update_hours(conn, p['place_key'], pd['hours'],
                          pd.get('hours_text', ''), pd.get('address', ''))
            updated += 1
        if idx % 25 == 0 or idx == total:
            log.info("  backfill %d/%d（已補 %d）", idx, total, updated)
        if commit_every and idx % commit_every == 0:
            conn.commit()
        if request_delay:
            time.sleep(request_delay)
    conn.commit()
    return updated


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")
    from . import config, db, gapi
    env = config.load_env()
    maps_key = env.get('MAPS_API_KEY', '') or env.get('GEMINI_API_KEY', '')
    if not maps_key:
        print("[INFO] 無 MAPS/GEMINI 金鑰，無法補營業時間。")
        return
    delay = float(env.get('VERIFY_REQUEST_DELAY') or 0)
    conn = db.connect()
    try:
        n = backfill_hours(conn, gapi.make_place_details(maps_key), request_delay=delay)
        print(f"[OK] 補了 {n} 家的營業時間。")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
