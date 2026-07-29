import csv as _csv
import json
import os

_PERM_CLOSED = ('CLOSED_PERMANENTLY', 'CLOSED')
_FIELD_ORDER = ['title', 'address', 'url', 'cuisine_type', 'source_list',
                'visited', 'distance_km', 'avg_spending', 'note', 'hours']

_CSV_HEADER = ['店名', '地址', '網址', '餐飲類型', '來源清單',
               '是否曾去過', '距離住家(公里)', '人均消費預估(元)', '備註', '營業時間']


def latest_import_id(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM imports ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return row[0] if row else None


def _perm_closed_keys(conn, import_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT place_key FROM closure_checks "
            "WHERE import_id=%s AND status = ANY(%s)",
            (import_id, list(_PERM_CLOSED)),
        )
        return {r[0] for r in cur.fetchall()}


def active_stores(conn, import_id=None):
    if import_id is None:
        import_id = latest_import_id(conn)
    if import_id is None:
        return []
    closed = _perm_closed_keys(conn, import_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.place_key, p.title, p.address, p.url, p.cuisine_type,
                   p.avg_spending, p.distance_km, p.hours,
                   m.is_visited, m.list_name, m.note
            FROM list_memberships m JOIN places p ON p.place_key = m.place_key
            WHERE m.import_id = %s
            ORDER BY p.title, m.list_name
            """,
            (import_id,),
        )
        rows = cur.fetchall()

    grouped = {}
    for (pk, title, address, url, cuisine, avg, dist, hours,
         is_visited, list_name, note) in rows:
        if pk in closed:
            continue
        g = grouped.get(pk)
        if g is None:
            g = {'title': title, 'address': address or '', 'url': url or '',
                 'cuisine_type': cuisine or '其他',
                 'avg_spending': avg if avg is not None else 0,
                 'distance_km': dist, 'hours': hours,
                 '_visited': False, '_lists': set(), '_note': ''}
            grouped[pk] = g
        g['_visited'] = g['_visited'] or bool(is_visited)
        g['_lists'].add(list_name)
        if not g['_note'] and note:
            g['_note'] = note

    stores = []
    for g in grouped.values():
        stores.append({
            'title':        g['title'],
            'address':      g['address'],
            'url':          g['url'],
            'cuisine_type': g['cuisine_type'],
            'source_list':  ', '.join(sorted(g['_lists'], reverse=True)),
            'visited':      '是' if g['_visited'] else '否',
            'distance_km':  g['distance_km'],
            'avg_spending': g['avg_spending'],
            'note':         g['_note'],
            'hours':        g['hours'],
        })
    stores.sort(key=lambda s: s['title'])
    return stores


def closed_stores(conn, import_id=None):
    if import_id is None:
        import_id = latest_import_id(conn)
    if import_id is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT p.title, p.address, p.url, p.cuisine_type,
                   p.avg_spending, c.status
            FROM closure_checks c JOIN places p ON p.place_key = c.place_key
            WHERE c.import_id = %s AND c.status = ANY(%s)
            ORDER BY p.title
            """,
            (import_id, list(_PERM_CLOSED)),
        )
        return [{'店名': t, '地址': a or '', '網址': u or '',
                 '餐飲類型': cu or '其他',
                 '人均消費預估(元)': av if av else '未知', '停業狀態': st}
                for (t, a, u, cu, av, st) in cur.fetchall()]


def _hours_text(hours):
    return '' if not hours else ';'.join(f"{h.get('d')}:{h.get('o')}-{h.get('c')}" for h in hours)


def write_stores_csv(conn, active_path, closed_path, import_id=None):
    os.makedirs(os.path.dirname(active_path) or '.', exist_ok=True)
    with open(active_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = _csv.writer(f)
        w.writerow(_CSV_HEADER)
        for s in active_stores(conn, import_id):
            w.writerow([s['title'], s['address'], s['url'], s['cuisine_type'],
                        s['source_list'], s['visited'],
                        s['distance_km'] if s['distance_km'] is not None else '未知',
                        s['avg_spending'] if s['avg_spending'] else '未知',
                        s['note'], _hours_text(s['hours'])])
    with open(closed_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = _csv.DictWriter(f, fieldnames=['店名', '地址', '網址', '餐飲類型',
                                           '人均消費預估(元)', '停業狀態'])
        w.writeheader()
        w.writerows(closed_stores(conn, import_id))
    return active_path, closed_path


def write_stores_js(conn, path='data/output/stores_data.js', import_id=None):
    if latest_import_id(conn) is None:
        return None
    stores = active_stores(conn, import_id)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write("// 自動產生的店家資料檔，請勿手動修改。\n")
        f.write("window.STORES_DATA = ")
        json.dump(stores, f, ensure_ascii=False, indent=2)
        f.write(";\n")
    return path
