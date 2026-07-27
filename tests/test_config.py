from mygmap.config import DbConfig


def test_from_env_reads_pg_vars():
    env = {
        'PGHOST': 'localhost', 'PGPORT': '5432',
        'PGDATABASE': 'mygooglemap', 'PGUSER': 'mygmap_app',
        'PGPASSWORD': 's3cret',
    }
    cfg = DbConfig.from_env(env=env)
    assert cfg.host == 'localhost'
    assert cfg.dbname == 'mygooglemap'
    assert cfg.user == 'mygmap_app'


def test_conninfo_contains_password_but_repr_hides_it():
    cfg = DbConfig.from_env(env={'PGDATABASE': 'd', 'PGUSER': 'u', 'PGPASSWORD': 's3cret'})
    assert 'password=s3cret' in cfg.conninfo()
    assert 's3cret' not in repr(cfg)
    assert 's3cret' not in str(cfg.safe_dict())


def test_conninfo_escapes_special_chars_in_password():
    import psycopg.conninfo
    cfg = DbConfig.from_env(env={'PGDATABASE': 'd', 'PGUSER': 'u',
                                 'PGPASSWORD': 'a b\\c'})
    parsed = psycopg.conninfo.conninfo_to_dict(cfg.conninfo())
    assert parsed['password'] == 'a b\\c'
    assert parsed['dbname'] == 'd'
    assert parsed['user'] == 'u'
