import os
import shutil

from mygmap import cli

FIX_SAVED = os.path.join(os.path.dirname(__file__), 'fixtures', 'saved')


def _make_zip(tmp_path):
    import zipfile
    zdir = tmp_path / 'data' / 'takeout'
    zdir.mkdir(parents=True)
    zpath = zdir / 'takeout-20260524T120207Z-1-001.zip'
    with zipfile.ZipFile(zpath, 'w') as z:
        for fn in os.listdir(FIX_SAVED):
            z.write(os.path.join(FIX_SAVED, fn), arcname=f'Takeout/已儲存/{fn}')
    return str(zdir)


def test_run_ingests_and_writes_report(conn, tmp_path):
    takeout_dir = _make_zip(tmp_path)
    out_dir = str(tmp_path / 'out')
    result = cli.run(conn, takeout_dir=takeout_dir, out_dir=out_dir)
    assert result['import_id'] is not None
    assert result['place_count'] == 3          # 小吳、牛耳、阿發（圖片排除）
    assert os.path.exists(result['report_path'])
