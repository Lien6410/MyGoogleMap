import psycopg
import pytest

from mygmap import db
from mygmap.config import DbConfig

TEST_SCHEMA = "mygmap_test"


@pytest.fixture()
def conn():
    cfg = DbConfig.from_env()
    if not cfg.dbname:
        pytest.skip("PGDATABASE 未設定，略過 DB 測試")
    try:
        admin = psycopg.connect(cfg.conninfo())
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"無法連線 PostgreSQL：{e}")
    admin.autocommit = True

    c = None
    try:
        with admin.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
            cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
        c = psycopg.connect(cfg.conninfo())
        with c.cursor() as cur:
            cur.execute(f"SET search_path TO {TEST_SCHEMA}")
        db.init_schema(c)
        yield c
    finally:
        if c is not None:
            c.close()
        with admin.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
        admin.close()
