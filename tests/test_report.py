from mygmap.ingest import ingest_entries
from mygmap import report


def _e(title, list_name, url='', visited=True):
    return {'title': title, 'list_name': list_name, 'url': url,
            'address': '', 'note': '', 'tags': '', 'is_visited': visited}


def _two_imports(conn):
    prev = ingest_entries(conn, [
        _e('A店', '想去的地點', url='x/data=!1s0x1:0x1', visited=False),
        _e('B店', '台北牛肉麵', url='x/data=!1s0x2:0x2'),
    ], source_zip='t1.zip')
    curr = ingest_entries(conn, [
        _e('B店', '想去的地點', url='x/data=!1s0x2:0x2', visited=False),  # 換清單
        _e('C店', '消夜', url='x/data=!1s0x3:0x3'),                        # 新增
    ], source_zip='t2.zip')                                                # A店 消失
    return prev, curr


def test_added_and_removed(conn):
    prev, curr = _two_imports(conn)
    added = {p['title'] for p in report.added_places(conn, prev, curr)}
    removed = {p['title'] for p in report.removed_places(conn, prev, curr)}
    assert added == {'C店'}
    assert removed == {'A店'}


def test_list_changes(conn):
    prev, curr = _two_imports(conn)
    changes = {c['title']: c for c in report.list_changes(conn, prev, curr)}
    assert 'B店' in changes
    assert changes['B店']['added_lists'] == ['想去的地點']
    assert changes['B店']['removed_lists'] == ['台北牛肉麵']


def test_render_markdown_has_sections(conn):
    prev, curr = _two_imports(conn)
    md = report.render_markdown(conn, prev, curr, '2026-07-25')
    assert '新增店家' in md
    assert '消失店家' in md
    assert 'C店' in md and 'A店' in md


def test_write_report_creates_file(conn, tmp_path):
    _two_imports(conn)
    path = report.write_report(conn, out_dir=str(tmp_path), date_str='2026-07-25')
    assert path is not None
    assert path.endswith('changes_2026-07-25.md')
    with open(path, encoding='utf-8') as f:
        assert '新增店家' in f.read()
