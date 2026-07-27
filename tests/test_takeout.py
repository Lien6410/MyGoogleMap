import os

from mygmap.takeout import read_all_from_dir, parse_export_time

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'saved')


def test_read_all_excludes_image_list_and_sets_visited():
    entries = read_all_from_dir(FIX)
    lists = {e['list_name'] for e in entries}
    assert '圖片' not in lists                      # 排除圖片清單
    # 想去的地點 → 未去過；其餘 → 去過
    by_title = {(e['title'], e['list_name']): e for e in entries}
    assert by_title[('阿發滷味', '想去的地點')]['is_visited'] is False
    assert by_title[('牛耳精緻麵館', '台北牛肉麵')]['is_visited'] is True


def test_read_all_captures_note_and_tags():
    entries = read_all_from_dir(FIX)
    niu = next(e for e in entries if e['title'] == '牛耳精緻麵館')
    assert niu['note'] == '紅燒'
    assert niu['tags'] == '好吃'
    assert niu['url'].endswith('!1s0x3c:0x4d')


def test_parse_export_time_from_zip_name():
    dt = parse_export_time('takeout-20260524T120207Z-3-001.zip')
    assert dt is not None
    assert dt.year == 2026 and dt.month == 5 and dt.day == 24


def test_parse_export_time_none_on_unparseable():
    assert parse_export_time('random.zip') is None
