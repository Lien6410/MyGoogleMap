import os

from .ingest import ingest_entries
from .takeout import read_all_from_dir


def find_saved_dirs(archive_dir):
    found = []
    for root, dirs, _files in os.walk(archive_dir):
        if os.path.basename(root) == '已儲存':
            found.append(root)
    return sorted(found)


def backfill_archive(conn, archive_dir):
    ids = []
    for saved_dir in find_saved_dirs(archive_dir):
        entries = read_all_from_dir(saved_dir)
        if not entries:
            continue
        ids.append(ingest_entries(conn, entries, source_zip=f"archive:{saved_dir}"))
    return ids
