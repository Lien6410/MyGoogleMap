from psycopg.types.json import Json


def cache_get(conn, key):
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM api_cache WHERE cache_key=%s", (key,))
        row = cur.fetchone()
    return row[0] if row else None


def cache_set(conn, key, value):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO api_cache (cache_key, value) VALUES (%s, %s) "
            "ON CONFLICT (cache_key) DO UPDATE SET value=EXCLUDED.value, fetched_at=now()",
            (key, Json(value)),
        )
    conn.commit()
