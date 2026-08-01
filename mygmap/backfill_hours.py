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


def _update_details(conn, place_key, hours, hours_text, address):
    """只寫「查到的」欄位：有 hours 才寫 hours（避免把 SQL NULL 變成 jsonb null）；
    有 address 才寫 address（COALESCE 保留舊值防空）。回傳是否有寫入。"""
    sets = ["updated_at = now()"]
    params = []
    if hours:
        sets.append("hours = %s")
        params.append(Json(hours))
        sets.append("hours_text = %s")
        params.append(hours_text or '')
    if address:
        sets.append("address = COALESCE(NULLIF(%s, ''), address)")
        params.append(address)
    if len(sets) == 1:          # 只有 updated_at → 沒查到任何可寫的
        return False
    params.append(place_key)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE places SET {', '.join(sets)} WHERE place_key = %s", params)
    return True


def backfill_hours(conn, place_details, *, limit=None, request_delay=0, commit_every=25):
    """對「有 CID 且 hours 空」的店，用 Find Place 信心比對後補**地址＋營業時間**。

    place_details: 可注入的 (name, address) -> {"address","hours","hours_text"}
                   （正式用 gapi.make_place_details(maps_key)，內含 name_similarity 門檻）。
    補地址是為了讓抽籤頁的縣市篩選能正確納入新竹本地、排除國外/他縣市店。
    只寫查到的欄位（查無不覆寫、不誤清）。回傳 (更新家數, 其中補到 hours 的家數)。
    """
    pending = _pending_hours(conn, limit)
    total = len(pending)
    log.info("補地址＋營業時間：候選 %d 家（有 CID 且 hours 空）", total)
    updated = 0
    got_hours = 0
    for idx, p in enumerate(pending, 1):
        pd = place_details(p['title'], p['address'] or '')
        if _update_details(conn, p['place_key'], pd.get('hours'),
                           pd.get('hours_text', ''), pd.get('address', '')):
            updated += 1
            if pd.get('hours'):
                got_hours += 1
        if idx % 25 == 0 or idx == total:
            log.info("  backfill %d/%d（更新 %d，其中 hours %d）", idx, total, updated, got_hours)
        if commit_every and idx % commit_every == 0:
            conn.commit()
        if request_delay:
            time.sleep(request_delay)
    conn.commit()
    return updated, got_hours


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
    find_place = gapi.make_find_place(maps_key)
    conn = db.connect()
    try:
        updated, got_hours = backfill_hours(conn, gapi.make_place_details(maps_key, find_place),
                                            request_delay=delay)
        print(f"[OK] 更新 {updated} 家（其中補到營業時間 {got_hours} 家）。")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
