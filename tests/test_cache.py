from mygmap import cache


def test_cache_set_then_get_roundtrip(conn):
    cache.cache_set(conn, "k1", {"status": "OPERATIONAL", "n": 3})
    assert cache.cache_get(conn, "k1") == {"status": "OPERATIONAL", "n": 3}


def test_cache_get_missing_returns_none(conn):
    assert cache.cache_get(conn, "nope") is None


def test_cache_set_overwrites(conn):
    cache.cache_set(conn, "k2", {"v": 1})
    cache.cache_set(conn, "k2", {"v": 2})
    assert cache.cache_get(conn, "k2") == {"v": 2}
