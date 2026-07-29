import json

from mygmap.ingest import ingest_entries
from mygmap.enrich import enrich_pending
from mygmap.verify import verify_import
from mygmap import export


def _e(title, list_name, url='', visited=True, note=''):
    return {'title': title, 'list_name': list_name, 'url': url, 'address': '新竹市',
            'note': note, 'tags': '', 'is_visited': visited}


def _fake_classify(items):
    return [{'types': '日式', 'avg_spending': 250, 'lat': 24.8, 'lng': 120.97,
             'address': '新竹市光復路'} for _ in items]


def _seed(conn):
    iid = ingest_entries(conn, [
        _e('營業店', '台北牛肉麵', url='x/data=!1s0x1:0x1', note='紅燒'),
        _e('營業店', '想去的地點', url='x/data=!1s0x1:0x1'),      # same place, 2 lists
        _e('只想去店', '想去的地點', url='x/data=!1s0x2:0x2', visited=False),
        _e('歇業店', '台北牛肉麵', url='x/data=!1s0x3:0x3'),
    ], source_zip='t.zip')
    enrich_pending(conn, _fake_classify, home_lat=24.80, home_lng=120.97)

    def fake_find(name, address):
        status = 'CLOSED_PERMANENTLY' if name == '歇業店' else 'OPERATIONAL'
        return {'status': status, 'address': '', 'price_level': None, 'match': 'EXACT'}

    verify_import(conn, iid, fake_find)
    return iid


def test_active_stores_fields_and_rules(conn):
    _seed(conn)
    stores = {s['title']: s for s in export.active_stores(conn)}
    assert '歇業店' not in stores                      # CLOSED_PERMANENTLY excluded
    assert set(stores) == {'營業店', '只想去店'}
    a = stores['營業店']
    assert a['visited'] == '是'                         # in a non-想去 list
    assert a['source_list'] == '想去的地點, 台北牛肉麵'   # sorted, comma-joined
    assert a['note'] == '紅燒'                          # first non-empty note
    assert a['cuisine_type'] == '日式' and a['avg_spending'] == 250
    assert a['distance_km'] == 0.0
    assert stores['只想去店']['visited'] == '否'         # only in 想去的地點


def test_write_stores_js_matches_contract(conn, tmp_path):
    _seed(conn)
    path = export.write_stores_js(conn, path=str(tmp_path / 'stores_data.js'))
    text = open(path, encoding='utf-8').read()
    assert text.startswith('// ')
    assert 'window.STORES_DATA = ' in text
    body = text[text.index('['):text.rindex(']') + 1]
    data = json.loads(body)
    keys = list(data[0].keys())
    assert keys == ['title', 'address', 'url', 'cuisine_type', 'source_list',
                    'visited', 'distance_km', 'avg_spending', 'note', 'hours']
