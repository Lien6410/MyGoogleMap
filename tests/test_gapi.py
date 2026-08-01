import mygmap.gapi as gapi
from mygmap.gapi import (heuristic_classify, haversine_distance,
                         name_similarity, extract_json_from_text,
                         make_place_details, make_find_place)


def test_heuristic_classify_detects_japanese():
    types, spend = heuristic_classify("一蘭拉麵", "")
    assert "日式" in types
    assert spend > 0


def test_heuristic_classify_non_dining_is_other_zero():
    types, spend = heuristic_classify("大安森林公園", "")
    assert types == "其他" and spend == 0


def test_haversine_known_distance():
    # 台北車站 -> 新竹車站 約 65-75 km
    d = haversine_distance(25.0478, 121.5170, 24.8015, 120.9715)
    assert 60 < d < 80


def test_haversine_none_on_missing():
    assert haversine_distance(None, 1, 2, 3) is None


def test_name_similarity_exact_and_mismatch():
    assert name_similarity("小吳牛肉麵", "小吳牛肉麵") >= 0.7
    assert name_similarity("小吳牛肉麵", "麥當勞") < 0.4


def test_extract_json_from_text_handles_wrapping():
    assert extract_json_from_text('前綴 {"a": 1} 後綴') == {"a": 1}
    assert extract_json_from_text("no json") is None


def test_make_place_details_no_key_returns_empty():
    pd = make_place_details('')
    # 以（店名, 地址）呼叫；無金鑰 → 空結果
    assert pd('某店', '新竹市') == {'address': '', 'hours': None, 'hours_text': ''}


def test_make_find_place_memoizes(monkeypatch):
    calls = []

    def fake_status(name, address, key):
        calls.append(name)
        return {'status': 'OPERATIONAL', 'place_id': 'ChIJ' + name, 'match': 'EXACT'}

    monkeypatch.setattr(gapi, 'find_place_status', fake_status)
    fp = make_find_place('KEY')
    fp('A', 'x'); fp('A', 'x'); fp('B', 'y')     # 'A' 呼叫兩次
    assert calls == ['A', 'B']                    # 但只真的查一次（memoize）


def test_make_place_details_shares_find_place(monkeypatch):
    fp_calls = []

    def fake_find_place(name, address):
        fp_calls.append((name, address))
        return {'status': 'OPERATIONAL', 'place_id': 'ChIJx', 'match': 'EXACT'}

    monkeypatch.setattr(gapi, 'place_details',
                        lambda pid, key: {'address': 'A', 'hours': [{'d': 1, 'o': '0900', 'c': '1700'}],
                                          'hours_text': 'x'})
    resolve = make_place_details('KEY', fake_find_place)
    out = resolve('店', '址')
    assert out['hours'] and fp_calls == [('店', '址')]   # 用共用 find_place 取 place_id 再查 details


def test_make_place_details_no_place_id_returns_empty():
    # find_place 回無 place_id（相似度不足）→ 不查 details、回空
    resolve = make_place_details('KEY', lambda n, a: {'status': 'NOT_FOUND', 'place_id': None})
    assert resolve('店', '址') == {'address': '', 'hours': None, 'hours_text': ''}
