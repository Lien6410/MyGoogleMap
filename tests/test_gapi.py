import mygmap.gapi as gapi
from mygmap.gapi import (heuristic_classify, haversine_distance,
                         name_similarity, extract_json_from_text,
                         make_place_details, make_find_place,
                         county_agrees, extract_county)


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


def test_extract_county_and_agreement():
    assert extract_county('新竹市東區光復路一段100號') == '新竹市'
    assert extract_county('300台灣新竹縣竹北市文興路') == '新竹縣'
    assert extract_county('Tokyo, Japan') is None
    assert county_agrees('新竹市東區', '300新竹市東區光復路') is True
    assert county_agrees('新竹市東區', '台北市大安區') is False
    assert county_agrees('', '台北市大安區') is True        # 無我方地址 → 退回只看店名


def _patch_urlopen(monkeypatch, payload):
    """讓 find_place_status 讀到假的 Find Place 回應，不打真實網路。"""
    import contextlib
    import io
    import json

    @contextlib.contextmanager
    def fake_urlopen(url, timeout=None):
        yield io.BytesIO(json.dumps(payload).encode('utf-8'))

    monkeypatch.setattr(gapi.urllib.request, 'urlopen', fake_urlopen)


def test_find_place_status_rejects_other_county(monkeypatch):
    """店名相似度再高，縣市對不上就不是同一家（「小林」→ 別縣市的「小林眼鏡」）。"""
    _patch_urlopen(monkeypatch, {'status': 'OK', 'candidates': [{
        'name': '小林眼鏡', 'business_status': 'OPERATIONAL',
        'formatted_address': '台北市大安區忠孝東路', 'place_id': 'ChIJwrong'}]})
    res = gapi.find_place_status('小林', '新竹市東區光復路', 'KEY')
    assert res['match'] == 'NO_MATCH' and res['place_id'] is None


def test_find_place_status_accepts_branch_suffix_same_county(monkeypatch):
    """同縣市的「店名＋分店」展開是正常情況，不能被擋掉。"""
    _patch_urlopen(monkeypatch, {'status': 'OK', 'candidates': [{
        'name': '安咖哩 新竹店', 'business_status': 'OPERATIONAL',
        'formatted_address': '300新竹市東區建功路', 'place_id': 'ChIJok'}]})
    res = gapi.find_place_status('安咖哩', '新竹市東區建功路一段', 'KEY')
    assert res['place_id'] == 'ChIJok' and res['status'] == 'OPERATIONAL'


def test_make_find_place_does_not_memoize_transient_errors(monkeypatch):
    """一次逾時不該毒害這家店整輪——下次仍要真的重查。"""
    results = [{'status': 'ERROR', 'place_id': None, 'match': 'EXCEPTION'},
               {'status': 'OPERATIONAL', 'place_id': 'ChIJok', 'match': 'EXACT'}]
    calls = []

    def fake_status(name, address, key):
        calls.append(name)
        return results[len(calls) - 1]

    monkeypatch.setattr(gapi, 'find_place_status', fake_status)
    fp = make_find_place('KEY')
    assert fp('A', 'x')['status'] == 'ERROR'
    assert fp('A', 'x')['status'] == 'OPERATIONAL'   # 重查，不吃到記憶的 ERROR
    assert len(calls) == 2
    fp('A', 'x')
    assert len(calls) == 2                            # 成功結果才進記憶


def test_place_details_registers_alias_so_verify_reuses_lookup(monkeypatch):
    """enrich 會把地址換成 Google 版寫回 DB；verify 之後用新地址查同一家店不該再打一次。"""
    calls = []

    def fake_status(name, address, key):
        calls.append((name, address))
        return {'status': 'OPERATIONAL', 'place_id': 'ChIJx', 'match': 'EXACT'}

    monkeypatch.setattr(gapi, 'find_place_status', fake_status)
    monkeypatch.setattr(gapi, 'place_details',
                        lambda pid, key: {'address': '300新竹市東區光復路一段1號',
                                          'hours': [{'d': 1, 'o': '0900', 'c': '1700'}],
                                          'hours_text': 'x'})
    fp = make_find_place('KEY')
    resolve = make_place_details('KEY', fp)
    det = resolve('某店', '新竹市')                      # enrich：用原地址
    fp('某店', det['address'])                          # verify：用 Google 回的新地址
    assert len(calls) == 1                              # 每家店 Find Place 只打一次
