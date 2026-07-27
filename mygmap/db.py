import psycopg

from .config import DbConfig

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS imports (
    id                   BIGSERIAL PRIMARY KEY,
    source_zip           TEXT,
    takeout_exported_at  TIMESTAMPTZ,
    imported_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    place_count          INTEGER,
    notes                TEXT
);

CREATE TABLE IF NOT EXISTS places (
    place_key            TEXT PRIMARY KEY,
    cid                  TEXT,
    title                TEXT NOT NULL,
    address              TEXT,
    url                  TEXT,
    lat                  DOUBLE PRECISION,
    lng                  DOUBLE PRECISION,
    cuisine_type         TEXT,
    avg_spending         INTEGER,
    hours                JSONB,
    hours_text           TEXT,
    distance_km          DOUBLE PRECISION,
    first_seen_import_id BIGINT REFERENCES imports(id),
    last_seen_import_id  BIGINT REFERENCES imports(id),
    enriched_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS list_memberships (
    id          BIGSERIAL PRIMARY KEY,
    import_id   BIGINT  NOT NULL REFERENCES imports(id),
    place_key   TEXT    NOT NULL REFERENCES places(place_key),
    list_name   TEXT    NOT NULL,
    is_visited  BOOLEAN NOT NULL,
    note        TEXT,
    tags        TEXT,
    raw_title   TEXT,
    UNIQUE (import_id, place_key, list_name)
);

CREATE TABLE IF NOT EXISTS closure_checks (
    id          BIGSERIAL PRIMARY KEY,
    import_id   BIGINT  NOT NULL REFERENCES imports(id),
    place_key   TEXT    NOT NULL REFERENCES places(place_key),
    status      TEXT    NOT NULL,
    is_closed   BOOLEAN NOT NULL,
    source      TEXT,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (import_id, place_key)
);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key   TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS schema_meta (
    version     INTEGER NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memberships_import ON list_memberships(import_id);
CREATE INDEX IF NOT EXISTS idx_memberships_place  ON list_memberships(place_key);
CREATE INDEX IF NOT EXISTS idx_closure_import     ON closure_checks(import_id);
CREATE INDEX IF NOT EXISTS idx_places_cid         ON places(cid);
"""


def connect(config=None, dbname_key='PGDATABASE'):
    config = config or DbConfig.from_env(dbname_key=dbname_key)
    return psycopg.connect(config.conninfo())


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("SELECT version FROM schema_meta ORDER BY version DESC LIMIT 1")
        if cur.fetchone() is None:
            cur.execute("INSERT INTO schema_meta (version) VALUES (%s)",
                        (SCHEMA_VERSION,))
    conn.commit()
