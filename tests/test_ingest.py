from mygmap.ingest import ingest_entries


def _entry(title, list_name, url='', address='', note='', tags='', visited=True):
    return {'title': title, 'list_name': list_name, 'url': url,
            'address': address, 'note': note, 'tags': tags, 'is_visited': visited}


def test_ingest_creates_import_places_and_memberships(conn):
    entries = [
        _entry('小吳牛肉麵', '台北牛肉麵', url='x/data=!1s0x1a:0x2b'),
        _entry('小吳牛肉麵', '想去的地點', url='x/data=!1s0x1a:0x2b', visited=False),
        _entry('阿發滷味', '想去的地點', address='新竹市', visited=False),
    ]
    import_id = ingest_entries(conn, entries, source_zip='t.zip')

    with conn.cursor() as cur:
        cur.execute("SELECT place_count FROM imports WHERE id=%s", (import_id,))
        assert cur.fetchone()[0] == 2                      # 兩個不重複地點
        cur.execute("SELECT count(*) FROM places")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM list_memberships WHERE import_id=%s", (import_id,))
        assert cur.fetchone()[0] == 3                      # 三筆清單歸屬


def test_ingest_membership_unique_dedup(conn):
    e = _entry('小吳牛肉麵', '台北牛肉麵', url='x/data=!1s0x1a:0x2b')
    import_id = ingest_entries(conn, [e, dict(e)], source_zip='t.zip')
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM list_memberships WHERE import_id=%s", (import_id,))
        assert cur.fetchone()[0] == 1                      # 同 import 同店同清單去重


def test_ingest_second_import_updates_last_seen(conn):
    e = _entry('小吳牛肉麵', '台北牛肉麵', url='x/data=!1s0x1a:0x2b')
    ingest_entries(conn, [e], source_zip='t1.zip')
    second = ingest_entries(conn, [e], source_zip='t2.zip')
    with conn.cursor() as cur:
        cur.execute("SELECT first_seen_import_id, last_seen_import_id FROM places")
        first_seen, last_seen = cur.fetchone()
        assert first_seen != last_seen
        assert last_seen == second
