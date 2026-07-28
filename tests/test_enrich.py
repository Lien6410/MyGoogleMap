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

    def fake_details(cid):
        return {'address': '精確地址', 'hours': [{'d': 1, 'o': '1100', 'c': '1400'}],
                'hours_text': '週一 11-14'}

    enrich_pending(conn, _fake_classify, place_details=fake_details)
    with conn.cursor() as cur:
        cur.execute("SELECT address, hours_text, hours FROM places WHERE title='有CID店'")
        addr, htext, hours = cur.fetchone()
    assert addr == '精確地址'
    assert htext == '週一 11-14'
    assert hours == [{'d': 1, 'o': '1100', 'c': '1400'}]
