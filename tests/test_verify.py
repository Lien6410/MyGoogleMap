from mygmap.ingest import ingest_entries
from mygmap.verify import verify_import
from mygmap import cache


def _e(title, url):
    return {'title': title, 'list_name': '想去的地點', 'url': url, 'address': '新竹市',
            'note': '', 'tags': '', 'is_visited': False}


def test_verify_writes_closure_rows_and_flags_closed(conn):
    iid = ingest_entries(conn, [
        _e('營業中店', 'x/data=!1s0x1:0x1'),
        _e('永久歇業店', 'x/data=!1s0x2:0x2'),
    ], source_zip='t.zip')

    def fake_find(name, address):
        status = 'CLOSED_PERMANENTLY' if name == '永久歇業店' else 'OPERATIONAL'
        return {'status': status, 'address': '', 'price_level': None, 'match': 'EXACT'}

    n = verify_import(conn, iid, fake_find)
    assert n == 2
    with conn.cursor() as cur:
        cur.execute("SELECT title, status, is_closed FROM closure_checks c "
                    "JOIN places p ON p.place_key=c.place_key ORDER BY title")
        rows = cur.fetchall()
    assert ('永久歇業店', 'CLOSED_PERMANENTLY', True) in rows
    assert ('營業中店', 'OPERATIONAL', False) in rows


def test_verify_uses_cache_second_run(conn):
    iid = ingest_entries(conn, [_e('快取店', 'x/data=!1s0x9:0x9')], source_zip='t.zip')
    calls = []

    def fake_find(name, address):
        calls.append(name)
        return {'status': 'OPERATIONAL', 'address': '', 'price_level': None, 'match': 'EXACT'}

    verify_import(conn, iid, fake_find)
    iid2 = ingest_entries(conn, [_e('快取店', 'x/data=!1s0x9:0x9')], source_zip='t2.zip')
    verify_import(conn, iid2, fake_find)
    assert len(calls) == 1          # second run served from api_cache


def test_verify_uncertain_not_cached(conn):
    iid = ingest_entries(conn, [_e('不確定店', 'x/data=!1s0x7:0x7')], source_zip='t.zip')

    def fake_find(name, address):
        return {'status': 'UNKNOWN', 'address': '', 'price_level': None, 'match': 'API_ERROR'}

    verify_import(conn, iid, fake_find)
    assert cache.cache_get(conn, '__closure__0x7:0x7') is None   # not long-term cached
    with conn.cursor() as cur:
        cur.execute("SELECT is_closed FROM closure_checks")
        assert cur.fetchone()[0] is False        # UNKNOWN is not 'closed'
