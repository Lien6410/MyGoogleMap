from psycopg.types.json import Json

from mygmap.ingest import ingest_entries
from mygmap.backfill_hours import backfill_hours


def _e(title, url, address=''):
    return {'title': title, 'list_name': '想去的地點', 'url': url,
            'address': address, 'note': '', 'tags': '', 'is_visited': False}


def test_backfill_fills_hours_and_address_for_cid_stores_only(conn):
    ingest_entries(conn, [
        _e('有CID店', 'x/data=!1s0xaa:0xbb'),
        _e('無URL店', ''),                      # 空 URL → 跳過（無 CID）
    ], source_zip='t.zip')

    calls = []

    def fake_details(name, address):
        calls.append(name)
        return {'address': '精確地址', 'hours': [{'d': 1, 'o': '1100', 'c': '1400'}],
                'hours_text': '週一 11-14'}

    updated, got_hours = backfill_hours(conn, fake_details)
    assert updated == 1 and got_hours == 1
    assert calls == ['有CID店']                 # 無 URL 的不查
    with conn.cursor() as cur:
        cur.execute("SELECT hours, hours_text, address FROM places WHERE title='有CID店'")
        hours, htext, addr = cur.fetchone()
    assert hours == [{'d': 1, 'o': '1100', 'c': '1400'}]
    assert htext == '週一 11-14'
    assert addr == '精確地址'


def test_backfill_fills_address_even_without_hours(conn):
    # Find Place 配到店、但該店 Google 無營業時間 → 仍補地址（供縣市篩選），hours 留空
    ingest_entries(conn, [_e('無時間但有地址店', 'x/data=!1s0x11:0x22')], source_zip='t.zip')

    def fake_details(name, address):
        return {'address': '新竹市東區信義街1號', 'hours': None, 'hours_text': ''}

    updated, got_hours = backfill_hours(conn, fake_details)
    assert updated == 1 and got_hours == 0
    with conn.cursor() as cur:
        cur.execute("SELECT hours, address FROM places WHERE title='無時間但有地址店'")
        hours, addr = cur.fetchone()
    assert hours is None                        # 沒把 SQL NULL 變成 jsonb null
    assert addr == '新竹市東區信義街1號'          # 地址補上了


def test_backfill_no_write_when_nothing_found(conn):
    ingest_entries(conn, [_e('查無店', 'x/data=!1s0xc:0xd', address='原地址')], source_zip='t.zip')

    def fake_details(name, address):
        return {'address': '', 'hours': None, 'hours_text': ''}

    updated, got_hours = backfill_hours(conn, fake_details)
    assert updated == 0 and got_hours == 0
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

    updated, got_hours = backfill_hours(conn, fake_details)
    assert updated == 0 and calls == []   # 已有 hours → 完全不查
