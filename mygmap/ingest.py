from .places import extract_cid, place_key


def ingest_entries(conn, entries, source_zip=None, takeout_exported_at=None):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO imports (source_zip, takeout_exported_at, place_count) "
                "VALUES (%s, %s, 0) RETURNING id",
                (source_zip, takeout_exported_at),
            )
            import_id = cur.fetchone()[0]

            # 以 place_key 去重（同店可出現在多清單）
            unique = {}
            for e in entries:
                pk = place_key(e.get('url', ''), e['title'], e.get('address', ''))
                e['_pk'] = pk
                unique.setdefault(pk, e)

            for pk, e in unique.items():
                cur.execute(
                    """
                    INSERT INTO places (place_key, cid, title, address, url,
                                        first_seen_import_id, last_seen_import_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (place_key) DO UPDATE SET
                        title   = EXCLUDED.title,
                        address = COALESCE(NULLIF(EXCLUDED.address, ''), places.address),
                        url     = COALESCE(NULLIF(EXCLUDED.url, ''), places.url),
                        last_seen_import_id = EXCLUDED.last_seen_import_id,
                        updated_at = now()
                    """,
                    (pk, extract_cid(e.get('url', '')), e['title'],
                     e.get('address', ''), e.get('url', ''), import_id, import_id),
                )

            for e in entries:
                cur.execute(
                    """
                    INSERT INTO list_memberships
                        (import_id, place_key, list_name, is_visited, note, tags, raw_title)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (import_id, place_key, list_name) DO NOTHING
                    """,
                    (import_id, e['_pk'], e['list_name'], bool(e['is_visited']),
                     e.get('note', ''), e.get('tags', ''), e['title']),
                )

            cur.execute("UPDATE imports SET place_count=%s WHERE id=%s",
                        (len(unique), import_id))
        conn.commit()
        return import_id
    except Exception:
        conn.rollback()
        raise
