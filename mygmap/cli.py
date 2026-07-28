import os

from . import config, db, gapi, report
from .enrich import enrich_pending
from .ingest import ingest_entries
from .takeout import extract_and_read, find_latest_zip, parse_export_time
from .verify import verify_import


def run(conn, takeout_dir='data/takeout', out_dir='data/output'):
    db.init_schema(conn)
    zip_path = find_latest_zip(takeout_dir)
    entries = extract_and_read(zip_path) if zip_path else []
    source_zip = os.path.basename(zip_path) if zip_path else None
    if not entries:
        return {'import_id': None, 'report_path': None, 'place_count': 0,
                'enriched': 0, 'verified': 0, 'zip': source_zip}

    exported_at = parse_export_time(source_zip) if source_zip else None
    import_id = ingest_entries(conn, entries, source_zip=source_zip,
                               takeout_exported_at=exported_at)

    env = config.load_env()
    api_key = env.get('GEMINI_API_KEY', '')
    maps_key = env.get('MAPS_API_KEY', '') or api_key
    model = env.get('GEMINI_MODEL', 'gemini-2.5-flash')
    home = env.get('HOME_ADDRESS', '')

    classify = gapi.make_classifier(api_key, model, home_address=home)
    enriched = enrich_pending(conn, classify)

    verified = 0
    if maps_key:
        verified = verify_import(conn, import_id, gapi.make_find_place(maps_key))

    report_path = report.write_report(conn, out_dir=out_dir)
    with conn.cursor() as cur:
        cur.execute("SELECT place_count FROM imports WHERE id=%s", (import_id,))
        place_count = cur.fetchone()[0]
    return {'import_id': import_id, 'report_path': report_path,
            'place_count': place_count, 'enriched': enriched,
            'verified': verified, 'zip': source_zip}


def main():
    conn = db.connect()
    try:
        result = run(conn)
        if result['import_id'] is None:
            print("[INFO] data/takeout/ 找不到可匯入的 zip 或清單，未進行匯入。")
            return
        print(f"[OK] import_id={result['import_id']} place_count={result['place_count']} "
              f"enriched={result['enriched']} verified={result['verified']}")
        print(f"[OK] report: {result['report_path']}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
