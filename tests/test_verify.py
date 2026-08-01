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


def test_verify_none_status_does_not_crash(conn):
    iid = ingest_entries(conn, [_e('空狀態店', 'x/data=!1s0x5:0x5')], source_zip='t.zip')

    def fake_find(name, address):
        return {'status': None, 'address': '', 'price_level': None, 'match': 'X'}

    verify_import(conn, iid, fake_find)   # must not raise
    with conn.cursor() as cur:
        cur.execute("SELECT status, is_closed FROM closure_checks")
        status, is_closed = cur.fetchone()
    assert status == 'UNKNOWN' and is_closed is False
    assert cache.cache_get(conn, '__closure__0x5:0x5') is None   # unsure -> not cached


def test_verify_reverifies_when_cache_stale(conn):
    iid = ingest_entries(conn, [_e('易變店', 'x/data=!1s0xab:0xcd')], source_zip='t.zip')
    calls = []

    def fake_find(name, address):
        calls.append(name)
        return {'status': 'OPERATIONAL', 'address': '', 'price_level': None, 'match': 'EXACT'}

    verify_import(conn, iid, fake_find)                                  # caches (fresh)
    iid2 = ingest_entries(conn, [_e('易變店', 'x/data=!1s0xab:0xcd')], source_zip='t2.zip')
    verify_import(conn, iid2, fake_find, cache_max_age_days=0)           # stale -> re-verify
    assert len(calls) == 2


def test_verify_throttles_between_live_calls(conn, monkeypatch):
    import mygmap.verify as verify_mod
    slept = []
    monkeypatch.setattr(verify_mod.time, 'sleep', lambda s: slept.append(s))
    iid = ingest_entries(conn, [_e('甲店', 'x/data=!1s0xa1:0xa1'),
                                _e('乙店', 'x/data=!1s0xb2:0xb2')], source_zip='t.zip')

    def fake_find(name, address):
        return {'status': 'OPERATIONAL', 'address': '', 'price_level': None, 'match': 'EXACT'}

    verify_import(conn, iid, fake_find, request_delay=3)
    assert slept == [3, 3]        # 兩家都 cache-miss（真的打了 API）→ 各節流一次


def test_verify_no_throttle_on_cache_hit(conn, monkeypatch):
    import mygmap.verify as verify_mod
    slept = []
    monkeypatch.setattr(verify_mod.time, 'sleep', lambda s: slept.append(s))
    iid = ingest_entries(conn, [_e('快取節流店', 'x/data=!1s0xcc:0xcc')], source_zip='t.zip')

    def fake_find(name, address):
        return {'status': 'OPERATIONAL', 'address': '', 'price_level': None, 'match': 'EXACT'}

    verify_import(conn, iid, fake_find, request_delay=3)         # 1st: cache-miss -> sleep once
    iid2 = ingest_entries(conn, [_e('快取節流店', 'x/data=!1s0xcc:0xcc')], source_zip='t2.zip')
    verify_import(conn, iid2, fake_find, request_delay=3)        # 2nd: cache-hit -> no api, no sleep
    assert slept == [3]           # 只有第一次真打 API 才節流
