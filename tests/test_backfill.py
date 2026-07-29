import os

from mygmap.backfill import backfill_archive

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'saved')


def test_backfill_archive_ingests_each_saved_dir(conn, tmp_path):
    # 造兩個含「已儲存」的 archive 快照
    for day in ('2026-06-20', '2026-06-21'):
        d = tmp_path / day / 'Takeout' / '已儲存'
        d.mkdir(parents=True)
        for fn in os.listdir(FIX):
            (d / fn).write_bytes(open(os.path.join(FIX, fn), 'rb').read())
    ids = backfill_archive(conn, str(tmp_path))
    assert len(ids) == 2
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM imports")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(DISTINCT place_key) FROM places")
        assert cur.fetchone()[0] >= 1
