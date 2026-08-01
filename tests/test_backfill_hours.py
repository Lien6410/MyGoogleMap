from psycopg.types.json import Json

from mygmap.ingest import ingest_entries
from mygmap.backfill_hours import backfill_hours


def _e(title, url, address=''):
    return {'title': title, 'list_name': '想去的地點', 'url': url,
            'address': address, 'note': '', 'tags': '', 'is_visited': False}


def test_backfill_fills_hours_for_cid_stores_only(conn):
    ingest_entries(conn, [
        _e('有CID店', 'x/data=!1s0xaa:0xbb'),
        _e('無URL店', ''),                      # 空 URL → 跳過（無 CID）
    ], source_zip='t.zip')

    calls = []

    def fake_details(name, address):
        calls.append(name)
        return {'address': '精確地址', 'hours': [{'d': 1, 'o': '1100', 'c': '1400'}],
                'hours_text': '週一 11-14'}

    n = backfill_hours(conn, fake_details)
    assert n == 1
    assert calls == ['有CID店']                 # 無 URL 的不查
    with conn.cursor() as cur:
        cur.execute("SELECT hours, hours_text, address FROM places WHERE title='有CID店'")
        hours, htext, addr = cur.fetchone()
    assert hours == [{'d': 1, 'o': '1100', 'c': '1400'}]
    assert htext == '週一 11-14'
    assert addr == '精確地址'


def test_backfill_no_write_when_hours_not_found(conn):
    ingest_entries(conn, [_e('查無店', 'x/data=!1s0xc:0xd', address='原地址')], source_zip='t.zip')

    def fake_details(name, address):
        return {'address': '', 'hours': None, 'hours_text': ''}

    n = backfill_hours(conn, fake_details)
    assert n == 0
    with conn.cursor() as cur:
        cur.execute("SELECT hours, address FROM places WHERE title='查無店'")
        hours, addr = cur.fetchone()
    assert hours is None            # 查無 → 不誤寫
    assert addr == '原地址'          # 地址不被空值覆蓋


def test_backfill_ignores_places_that_already_have_hours(conn):
    ingest_entries(conn, [_e('已有時間店', 'x/data=!1s0xe:0xf')], source_zip='t.zip')
    with conn.cursor() as cur:
        cur.execute("UPDATE places SET hours = %s WHERE title='已有時間店'",
                    (Json([{'d': 1, 'o': '0900', 'c': '1700'}]),))
    conn.commit()

    calls = []

    def fake_details(name, address):
        calls.append(name)
        return {'address': '', 'hours': [{'d': 2, 'o': '1000', 'c': '1400'}], 'hours_text': ''}

    n = backfill_hours(conn, fake_details)
    assert n == 0 and calls == []   # 已有 hours → 完全不查
