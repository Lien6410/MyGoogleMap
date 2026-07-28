from psycopg.types.json import Json


def cache_get(conn, key, max_age_seconds=None):
    with conn.cursor() as cur:
        if max_age_seconds is None:
            cur.execute("SELECT value FROM api_cache WHERE cache_key=%s", (key,))
        else:
            cur.execute(
                "SELECT value FROM api_cache WHERE cache_key=%s "
                "AND fetched_at >= now() - (%s * interval '1 second')",
                (key, max_age_seconds),
            )
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
