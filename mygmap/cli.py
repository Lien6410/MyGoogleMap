import os

from . import db, report
from .ingest import ingest_entries
from .takeout import extract_and_read, find_latest_zip, parse_export_time


def run(conn, takeout_dir='data/takeout', out_dir='data/output'):
    db.init_schema(conn)
    zip_path = find_latest_zip(takeout_dir)
    entries = extract_and_read(zip_path) if zip_path else []
    source_zip = os.path.basename(zip_path) if zip_path else None
    exported_at = parse_export_time(source_zip) if source_zip else None
    import_id = ingest_entries(conn, entries, source_zip=source_zip,
                               takeout_exported_at=exported_at)
    report_path = report.write_report(conn, out_dir=out_dir)
    with conn.cursor() as cur:
        cur.execute("SELECT place_count FROM imports WHERE id=%s", (import_id,))
        place_count = cur.fetchone()[0]
    return {'import_id': import_id, 'report_path': report_path,
            'place_count': place_count}


def main():
    conn = db.connect()
    try:
        result = run(conn)
        print(f"[OK] import_id={result['import_id']} "
              f"place_count={result['place_count']}")
        if result['report_path']:
            print(f"[OK] report: {result['report_path']}")
        else:
            print("[INFO] 尚無可比對的上一次匯入，未產生報告。")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
