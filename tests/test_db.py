def test_init_schema_creates_all_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'mygmap_test'
        """)
        tables = {r[0] for r in cur.fetchall()}
    assert {'imports', 'places', 'list_memberships',
            'closure_checks', 'api_cache', 'schema_meta'} <= tables


def test_init_schema_is_idempotent(conn):
    from mygmap import db
    db.init_schema(conn)  # 再跑一次不應報錯
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_meta")
        assert cur.fetchone()[0] == 1
