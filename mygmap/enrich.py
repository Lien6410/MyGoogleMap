from psycopg.types.json import Json

from .gapi import haversine_distance
from .places import extract_cid


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
    with conn.cursor() as cur:
        set_enriched = ", enriched_at = now()" if mark_enriched else ""
        cur.execute(
            "UPDATE places SET "
            "cuisine_type = %s, avg_spending = %s, lat = %s, lng = %s, "
            "address = COALESCE(NULLIF(%s, ''), address), "
            "hours = %s, hours_text = %s, distance_km = %s, updated_at = now()"
            + set_enriched +
            " WHERE place_key = %s",
            (det.get('types'), det.get('avg_spending'), lat, lng, address,
             Json(hours) if hours is not None else None, hours_text,
             distance_km, place_key),
        )


def enrich_pending(conn, classify, *, place_details=None,
                   home_lat=None, home_lng=None, batch_size=20, limit=None, mark_enriched=True):
    pending = _pending_places(conn, limit)
    done = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        items = [{'title': p['title'], 'address': p['address'] or ''} for p in batch]
        results = classify(items)
        for p, det in zip(batch, results):
            lat, lng = det.get('lat'), det.get('lng')
            address = p['address'] or det.get('address') or ''
            hours, hours_text = None, ''
            cid = extract_cid(p['url'] or '')
            if place_details and cid:
                pd = place_details(cid)
                if pd.get('address'):
                    address = pd['address']
                hours = pd.get('hours')
                hours_text = pd.get('hours_text', '')
            distance_km = (haversine_distance(home_lat, home_lng, lat, lng)
                           if home_lat is not None and home_lng is not None else None)
            _update_place(conn, p['place_key'], det, address, lat, lng,
                          hours, hours_text, distance_km, mark_enriched)
            done += 1
    conn.commit()
    return done
