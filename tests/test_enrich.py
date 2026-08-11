from mygmap.ingest import ingest_entries
from mygmap.enrich import enrich_pending


def _e(title, url='', address=''):
    return {'title': title, 'list_name': '想去的地點', 'url': url,
            'address': address, 'note': '', 'tags': '', 'is_visited': False}


def _fake_classify(items):
    return [{'types': '日式', 'avg_spending': 250, 'lat': 24.8, 'lng': 120.97,
             'address': it['address'] or '新竹市自動補齊'} for it in items]


def test_enrich_fills_places_and_sets_enriched_at(conn):
    ingest_entries(conn, [_e('拉麵店', url='x/data=!1s0x1:0x2')], source_zip='t.zip')
    n = enrich_pending(conn, _fake_classify, home_lat=24.80, home_lng=120.97)
    assert n == 1
    with conn.cursor() as cur:
        cur.execute("SELECT cuisine_type, avg_spending, lat, address, enriched_at, distance_km "
                    "FROM places WHERE title='拉麵店'")
        cuisine, spend, lat, addr, enriched_at, dist = cur.fetchone()
    assert cuisine == '日式' and spend == 250 and lat == 24.8
    assert addr == '新竹市自動補齊'
    assert enriched_at is not None
    assert dist == 0.0            # home == place coords -> 0 km


def test_enrich_skips_already_enriched(conn):
    ingest_entries(conn, [_e('已補齊店', url='x/data=!1s0x3:0x4')], source_zip='t.zip')
    assert enrich_pending(conn, _fake_classify) == 1
    # second run: nothing pending
    assert enrich_pending(conn, _fake_classify) == 0


def test_enrich_uses_place_details_for_address_and_hours(conn):
    ingest_entries(conn, [_e('有CID店', url='x/data=!1s0xaa:0xbb')], source_zip='t.zip')

    def fake_details(name, address):
        return {'address': '精確地址', 'hours': [{'d': 1, 'o': '1100', 'c': '1400'}],
                'hours_text': '週一 11-14'}

    enrich_pending(conn, _fake_classify, place_details=fake_details)
    with conn.cursor() as cur:
        cur.execute("SELECT address, hours_text, hours FROM places WHERE title='有CID店'")
        addr, htext, hours = cur.fetchone()
    assert addr == '精確地址'
    assert htext == '週一 11-14'
    assert hours == [{'d': 1, 'o': '1100', 'c': '1400'}]


def test_enrich_does_not_wipe_existing_hours_when_lookup_fails(conn):
    """Find Place 這次沒查到 → 不能把 backfill_hours 補好的營業時間洗成 NULL。"""
    ingest_entries(conn, [_e('保住時間店', url='x/data=!1s0xc1:0xc2')], source_zip='t.zip')
    with conn.cursor() as cur:
        cur.execute("UPDATE places SET hours='[{\"d\":1,\"o\":\"0900\",\"c\":\"1700\"}]'::jsonb, "
                    "hours_text='週一 9-17' WHERE title='保住時間店'")

    def empty_details(name, address):
        return {'address': '', 'hours': None, 'hours_text': ''}

    enrich_pending(conn, _fake_classify, place_details=empty_details)
    with conn.cursor() as cur:
        cur.execute("SELECT hours, hours_text, cuisine_type FROM places WHERE title='保住時間店'")
        hours, htext, cuisine = cur.fetchone()
    assert hours == [{'d': 1, 'o': '0900', 'c': '1700'}]   # 保留
    assert htext == '週一 9-17'
    assert cuisine == '日式'                                # 分類照樣更新


def test_enrich_keeps_progress_when_a_later_batch_raises(conn):
    """API 已計費，中途炸掉不該讓前面幾批的成果一起回滾。"""
    ingest_entries(conn, [_e('先成功店', url='x/data=!1s0xd1:0xd2'),
                          _e('後爆炸店', url='y/data=!1s0xd3:0xd4')], source_zip='t.zip')
    calls = []

    def flaky_classify(items):
        calls.append(items)
        if len(calls) == 2:
            raise RuntimeError('REQUEST_DENIED')
        return _fake_classify(items)

    try:
        enrich_pending(conn, flaky_classify, batch_size=1)
    except RuntimeError:
        pass
    else:
        raise AssertionError('應該把例外往上拋')
    with conn.cursor() as cur:
        cur.execute("SELECT cuisine_type FROM places WHERE title='先成功店'")
        assert cur.fetchone()[0] == '日式'      # 第一批已 commit，沒被回滾


def test_enrich_heuristic_run_does_not_mark_enriched(conn):
    ingest_entries(conn, [_e('待補店', url='x/data=!1s0xe:0xf')], source_zip='t.zip')
    # heuristic/no-key run: fills fields but leaves enriched_at NULL
    enrich_pending(conn, _fake_classify, mark_enriched=False)
    with conn.cursor() as cur:
        cur.execute("SELECT cuisine_type, enriched_at FROM places WHERE title='待補店'")
        cuisine, enriched_at = cur.fetchone()
    assert cuisine == '日式' and enriched_at is None
    # a later keyed run still finds it pending and marks it
    assert enrich_pending(conn, _fake_classify, mark_enriched=True) == 1
    with conn.cursor() as cur:
        cur.execute("SELECT enriched_at FROM places WHERE title='待補店'")
        assert cur.fetchone()[0] is not None


def test_enrich_logs_progress(conn, caplog):
    import logging
    ingest_entries(conn, [_e('進度店', url='x/data=!1s0x9:0xa')], source_zip='t.zip')
    with caplog.at_level(logging.INFO, logger='mygmap.enrich'):
        enrich_pending(conn, _fake_classify)
    msgs = [r.getMessage() for r in caplog.records]
    assert any('待補齊 1' in m for m in msgs)     # header line
    assert any('enrich 1/1' in m for m in msgs)    # per-batch progress


def test_enrich_throttles_between_batches(conn, monkeypatch):
    import mygmap.enrich as enrich_mod
    slept = []
    monkeypatch.setattr(enrich_mod.time, 'sleep', lambda s: slept.append(s))
    ingest_entries(conn, [_e('甲', url='x/data=!1s0x1:0x2'),
                          _e('乙', url='y/data=!1s0x3:0x4')], source_zip='t.zip')
    enrich_pending(conn, _fake_classify, batch_size=1, batch_delay=5)
    assert slept == [5]           # 2 批次 → 僅批次「之間」sleep 一次（最後一批後不 sleep）


def test_enrich_no_throttle_by_default(conn, monkeypatch):
    import mygmap.enrich as enrich_mod
    slept = []
    monkeypatch.setattr(enrich_mod.time, 'sleep', lambda s: slept.append(s))
    ingest_entries(conn, [_e('丙', url='x/data=!1s0x5:0x6'),
                          _e('丁', url='y/data=!1s0x7:0x8')], source_zip='t.zip')
    enrich_pending(conn, _fake_classify, batch_size=1)   # batch_delay 預設 0
    assert slept == []            # 測試不因節流變慢
