import logging
import time

from . import cache

CLOSED_STATUSES = {'CLOSED_PERMANENTLY', 'CLOSED_TEMPORARILY', 'CLOSED', 'NOT_FOUND'}
_UNSURE = {'UNCERTAIN', 'ERROR', 'UNKNOWN', None}

log = logging.getLogger(__name__)


def _places_in_import(conn, import_id, limit=None):
    sql = ("SELECT DISTINCT p.place_key, p.title, p.address "
           "FROM list_memberships m JOIN places p ON p.place_key=m.place_key "
           "WHERE m.import_id=%s ORDER BY p.place_key")
    params = [import_id]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [{'place_key': r[0], 'title': r[1], 'address': r[2]} for r in cur.fetchall()]


def _write_closure(conn, import_id, place_key, status, is_closed, source):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO closure_checks (import_id, place_key, status, is_closed, source)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (import_id, place_key) DO UPDATE SET
                status=EXCLUDED.status, is_closed=EXCLUDED.is_closed,
                source=EXCLUDED.source, checked_at=now()
            """,
            (import_id, place_key, status, is_closed, source),
        )


def verify_import(conn, import_id, find_place, *, gemini_verify=None, limit=None,
                  cache_max_age_days=1, request_delay=0):
    max_age = cache_max_age_days * 86400 if cache_max_age_days is not None else None
    places = _places_in_import(conn, import_id, limit)
    total = len(places)
    log.info("歇業驗證：%d 家（快取內的近期結果會略過查詢）", total)
    written = 0
    for p in places:
        ck = f"__closure__{p['place_key']}"
        cached = cache.cache_get(conn, ck, max_age_seconds=max_age)
        if cached and cached.get('status') not in _UNSURE:
            status, source = cached['status'], cached.get('source', 'cache')
        else:
            res = find_place(p['title'], p['address'] or '')
            status = res.get('status') or 'UNKNOWN'
            source = 'maps'
            if status not in _UNSURE:
                cache.cache_set(conn, ck, {'status': status, 'source': source})
            if request_delay:
                time.sleep(request_delay)   # 只在真的打了 API（cache-miss）後才節流
        is_closed = status in CLOSED_STATUSES
        _write_closure(conn, import_id, p['place_key'], status, is_closed, source)
        written += 1
        if total and (written % 25 == 0 or written == total):
            log.info("  verify %d/%d", written, total)
    conn.commit()
    return written
