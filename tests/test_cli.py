import os

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


def test_run_with_no_zip_creates_no_import(conn, tmp_path):
    empty_dir = str(tmp_path / 'empty_takeout')
    os.makedirs(empty_dir)
    result = cli.run(conn, takeout_dir=empty_dir, out_dir=str(tmp_path / 'out'))
    assert result['import_id'] is None
    assert result['place_count'] == 0
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM imports")
        assert cur.fetchone()[0] == 0


def test_run_calls_enrich_and_verify(conn, tmp_path, monkeypatch):
    import mygmap.cli as climod
    calls = {'enrich': 0, 'verify': 0}

    def fake_enrich(conn_, classify, **kw):
        calls['enrich'] += 1
        return 0

    def fake_verify(conn_, import_id, find_place, **kw):
        calls['verify'] += 1
        return 0

    monkeypatch.setattr(climod, 'enrich_pending', fake_enrich)
    monkeypatch.setattr(climod, 'verify_import', fake_verify)
    monkeypatch.setattr(climod.config, 'load_env', lambda *a, **k: {'MAPS_API_KEY': 'x'})

    takeout_dir = _make_zip(tmp_path)
    result = climod.run(conn, takeout_dir=takeout_dir, out_dir=str(tmp_path / 'out'))
    assert result['import_id'] is not None
    assert calls['enrich'] == 1 and calls['verify'] == 1
    assert 'enriched' in result and 'verified' in result


def test_run_no_keys_skips_verify(conn, tmp_path, monkeypatch):
    import mygmap.cli as climod
    calls = {'enrich': 0, 'verify': 0}

    def fake_enrich(conn_, classify, **kw):
        calls['enrich'] += 1
        return 0

    def fake_verify(conn_, import_id, find_place, **kw):
        calls['verify'] += 1
        return 0

    monkeypatch.setattr(climod, 'enrich_pending', fake_enrich)
    monkeypatch.setattr(climod, 'verify_import', fake_verify)
    monkeypatch.setattr(climod.config, 'load_env', lambda *a, **k: {})

    takeout_dir = _make_zip(tmp_path)
    result = climod.run(conn, takeout_dir=takeout_dir, out_dir=str(tmp_path / 'out'))
    assert calls['enrich'] == 1          # enrich always runs (heuristic when no key)
    assert calls['verify'] == 0          # no key -> verify skipped
    assert result['verified'] == 0
