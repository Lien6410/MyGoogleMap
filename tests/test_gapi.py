from mygmap.gapi import (heuristic_classify, haversine_distance,
                         name_similarity, extract_json_from_text,
                         make_place_details, _pick_place_id)


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
    # 新介面：以（店名, 地址）呼叫（內部走 Find Place 取 place_id 再查 details）
    assert pd('某店', '新竹市') == {'address': '', 'hours': None, 'hours_text': ''}


def test_pick_place_id_similarity_guard():
    # 名稱相符 → 取其 place_id
    match = [{'place_id': 'ChIJ_ok', 'name': '小吳牛肉麵'}]
    assert _pick_place_id(match, '小吳牛肉麵') == 'ChIJ_ok'
    # 名稱不符（Find Place 找錯店）→ 回 None，避免補到別家的營業時間
    wrong = [{'place_id': 'ChIJ_wrong', 'name': '麥當勞'}]
    assert _pick_place_id(wrong, '小吳牛肉麵') is None
    # 無候選 → None
    assert _pick_place_id([], '任何店') is None
