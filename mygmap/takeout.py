import csv
import glob
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone

EXCLUDE_LISTS = {'圖片'}
UNVISITED_LIST_NAME = '想去的地點'

_ZIP_TS_RE = re.compile(r'(\d{8})T(\d{6})Z')


def find_latest_zip(takeout_dir='data/takeout'):
    zips = glob.glob(os.path.join(takeout_dir, '*.zip'))
    if not zips:
        return None
    return max(zips, key=os.path.getmtime)


def parse_export_time(zip_name):
    m = _ZIP_TS_RE.search(zip_name or '')
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S').replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _detect_headers(header_row):
    mapping = {'title': None, 'note': None, 'url': None, 'address': None, 'tags': None}
    for i, col in enumerate(header_row):
        c = col.strip().lower()
        if c in ('title', '標題', '名稱', 'name'):
            mapping['title'] = i
        elif c in ('note', '備註', '說明', '備忘錄', 'notes', '筆記'):
            mapping['note'] = i
        elif c in ('url', '網址', '連結', 'link'):
            mapping['url'] = i
        elif c in ('address', '地址'):
            mapping['address'] = i
        elif c in ('標籤', 'tags'):
            mapping['tags'] = i
    if mapping['title'] is None:
        mapping['title'] = 0
    return mapping


def read_saved_csv(path, list_name):
    entries = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return entries
        m = _detect_headers(headers)

        def cell(row, key):
            i = m[key]
            return row[i].strip() if i is not None and i < len(row) else ''

        for row in reader:
            if not row:
                continue
            title = cell(row, 'title')
            if not title:
                continue
            entries.append({
                'title': title,
                'note': cell(row, 'note'),
                'url': cell(row, 'url'),
                'address': cell(row, 'address'),
                'tags': cell(row, 'tags'),
                'list_name': list_name,
            })
    return entries


def read_all_from_dir(saved_dir):
    entries = []
    for fn in sorted(os.listdir(saved_dir)):
        if not fn.lower().endswith('.csv'):
            continue
        list_name = fn[:-4]
        if list_name in EXCLUDE_LISTS:
            continue
        for e in read_saved_csv(os.path.join(saved_dir, fn), list_name):
            e['is_visited'] = (list_name != UNVISITED_LIST_NAME)
            entries.append(e)
    return entries


def extract_and_read(zip_path, workdir=None):
    workdir = workdir or tempfile.mkdtemp(prefix='takeout_')
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(workdir)
    for root, _dirs, _files in os.walk(workdir):
        if os.path.basename(root) == '已儲存':
            return read_all_from_dir(root)
    return []
