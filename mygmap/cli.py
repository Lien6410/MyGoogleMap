import logging
import os

from . import config, db, export, gapi, report
from .enrich import enrich_pending
from .ingest import ingest_entries
from .takeout import extract_and_read, find_latest_zip, parse_export_time
from .verify import verify_import

log = logging.getLogger(__name__)


def run(conn, takeout_dir='data/takeout', out_dir='data/output'):
    log.info("初始化資料庫 schema…")
    db.init_schema(conn)
    zip_path = find_latest_zip(takeout_dir)
    entries = extract_and_read(zip_path) if zip_path else []
    source_zip = os.path.basename(zip_path) if zip_path else None
    if not entries:
        log.info("data/takeout/ 找不到可匯入的 zip 或清單，未進行匯入。")
        return {'import_id': None, 'report_path': None, 'place_count': 0,
                'enriched': 0, 'verified': 0, 'zip': source_zip,
                'stores_js': None}

    log.info("匯入 %s（%d 筆條目）…", source_zip, len(entries))
    exported_at = parse_export_time(source_zip) if source_zip else None
    import_id = ingest_entries(conn, entries, source_zip=source_zip,
                               takeout_exported_at=exported_at)
    log.info("匯入完成 import_id=%s", import_id)

    env = config.load_env()
    api_key = env.get('GEMINI_API_KEY', '')
    maps_key = env.get('MAPS_API_KEY', '') or api_key
    model = env.get('GEMINI_MODEL', 'gemini-2.5-flash')
    home = env.get('HOME_ADDRESS', '')
    # 節流：enrich 每批走一次 Gemini，預設每批間隔 7 秒（≈8.5 req/min，壓在免費層 10 RPM 內）；
    # 無金鑰走本地啟發式、不需節流。verify 走 Maps（額度高），預設不節流。皆可用 .env 覆寫。
    batch_delay = float(env.get('ENRICH_BATCH_DELAY') or 7) if api_key else 0
    verify_delay = float(env.get('VERIFY_REQUEST_DELAY') or 0)
    if not api_key and not maps_key:
        log.info("未偵測到 API 金鑰：enrichment 走本地啟發式、跳過歇業驗證。")

    home_lat = home_lng = None
    place_details = None
    # 一顆記憶化的 find_place，enrich（取 place_id 查營業時間）與 verify（取 status）共用，
    # 每家店的 Find Place 只打一次網路，省 Maps 額度。
    find_place = gapi.make_find_place(maps_key)
    if maps_key:
        if home:
            log.info("定位住家地址…")
            home_lat, home_lng = gapi.geocode(home, maps_key)
        place_details = gapi.make_place_details(maps_key, find_place)

    classify = gapi.make_classifier(api_key, model, home_address=home)
    enriched = enrich_pending(conn, classify, place_details=place_details,
                              home_lat=home_lat, home_lng=home_lng,
                              mark_enriched=bool(api_key), batch_delay=batch_delay)

    verified = 0
    if maps_key:
        verified = verify_import(conn, import_id, find_place, request_delay=verify_delay)

    log.info("產生變化報告…")
    report_path = report.write_report(conn, out_dir=out_dir)
    log.info("從 DB 產出 stores_data.js 與 CSV…")
    stores_js = export.write_stores_js(conn, path=os.path.join(out_dir, 'stores_data.js'))
    export.write_stores_csv(
        conn,
        os.path.join(out_dir, 'MyGoogleMap_Stores_active.csv'),
        os.path.join(out_dir, 'MyGoogleMap_Stores_closed.csv'),
    )
    with conn.cursor() as cur:
        cur.execute("SELECT place_count FROM imports WHERE id=%s", (import_id,))
        place_count = cur.fetchone()[0]
    log.info("完成。")
    return {'import_id': import_id, 'report_path': report_path,
            'place_count': place_count, 'enriched': enriched,
            'verified': verified, 'zip': source_zip,
            'stores_js': stores_js}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")
    conn = db.connect()
    try:
        result = run(conn)
        if result['import_id'] is None:
            print("[INFO] data/takeout/ 找不到可匯入的 zip 或清單，未進行匯入。")
            return
        print(f"[OK] import_id={result['import_id']} place_count={result['place_count']} "
              f"enriched={result['enriched']} verified={result['verified']}")
        print(f"[OK] report: {result['report_path']}")
        print(f"[OK] stores_data.js: {result['stores_js']}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
