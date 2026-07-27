from mygmap.places import extract_cid, place_key


def test_extract_cid_from_maps_url():
    url = ("https://www.google.com/maps/place/x/data=!4m2!3m1!1s"
           "0x3442a90e656a081f:0x713c3942e872dca2")
    assert extract_cid(url) == "0x3442a90e656a081f:0x713c3942e872dca2"


def test_extract_cid_none_when_absent():
    assert extract_cid("https://example.com") is None
    assert extract_cid("") is None


def test_place_key_uses_cid_when_present():
    url = "x/data=!1s0x1a:0x2b"
    assert place_key(url, "小吳牛肉麵", "台北市") == "0x1a:0x2b"


def test_place_key_falls_back_to_normalized_name_and_address():
    key = place_key("", "小吳 牛肉麵（總店）", "台北市 大安區")
    assert key == "name:小吳牛肉麵總店|台北市大安區"


def test_extract_cid_is_case_normalized():
    upper = "x/data=!1s0X1A:0X2B"
    lower = "x/data=!1s0x1a:0x2b"
    assert extract_cid(upper) == "0x1a:0x2b"
    assert place_key(upper, "店", "址") == place_key(lower, "店", "址")


def test_place_key_preserves_hyphen_in_address():
    a = place_key("", "某店", "新竹市光復路5-1號")
    b = place_key("", "某店", "新竹市光復路51號")
    assert a != b
