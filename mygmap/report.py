import csv
import os


def latest_two_imports(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM imports ORDER BY id DESC LIMIT 2")
        rows = [r[0] for r in cur.fetchall()]
    curr = rows[0] if rows else None
    prev = rows[1] if len(rows) > 1 else None
    return prev, curr


def _place_lists(conn, import_id):
    """回傳 {place_key: (title, url, [list_name,...])}。"""
    result = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.place_key, p.title, p.url, m.list_name
            FROM list_memberships m JOIN places p ON p.place_key = m.place_key
            WHERE m.import_id = %s
            ORDER BY p.title, m.list_name
            """,
            (import_id,),
        )
        for place_key, title, url, list_name in cur.fetchall():
            entry = result.setdefault(place_key, (title, url, []))
            entry[2].append(list_name)
    return result


def added_places(conn, prev, curr):
    curr_map = _place_lists(conn, curr)
    prev_map = _place_lists(conn, prev) if prev else {}
    out = []
    for pk, (title, url, lists) in curr_map.items():
        if pk not in prev_map:
            out.append({'place_key': pk, 'title': title, 'url': url, 'lists': lists})
    return sorted(out, key=lambda x: x['title'])


def removed_places(conn, prev, curr):
    if not prev:
        return []
    curr_map = _place_lists(conn, curr)
    prev_map = _place_lists(conn, prev)
    out = []
    for pk, (title, url, lists) in prev_map.items():
        if pk not in curr_map:
            out.append({'place_key': pk, 'title': title, 'url': url, 'lists': lists})
    return sorted(out, key=lambda x: x['title'])


def list_changes(conn, prev, curr):
    if not prev:
        return []
    curr_map = _place_lists(conn, curr)
    prev_map = _place_lists(conn, prev)
    out = []
    for pk in set(curr_map) & set(prev_map):
        title, _url, curr_lists = curr_map[pk]
        _t, _u, prev_lists = prev_map[pk]
        added = sorted(set(curr_lists) - set(prev_lists))
        removed = sorted(set(prev_lists) - set(curr_lists))
        if added or removed:
            out.append({'place_key': pk, 'title': title,
                        'added_lists': added, 'removed_lists': removed})
    return sorted(out, key=lambda x: x['title'])


def closure_changes(conn, prev, curr):
    if not prev:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.place_key, p.title, prev.status, c.status
            FROM closure_checks c
            JOIN places p ON p.place_key = c.place_key
            JOIN closure_checks prev
              ON prev.place_key = c.place_key AND prev.import_id = %s
            WHERE c.import_id = %s AND c.status <> prev.status
            ORDER BY p.title
            """,
            (prev, curr),
        )
        return [{'place_key': pk, 'title': t, 'old_status': o, 'new_status': n}
                for pk, t, o, n in cur.fetchall()]


def render_markdown(conn, prev, curr, date_str):
    added = added_places(conn, prev, curr)
    removed = removed_places(conn, prev, curr)
    lists = list_changes(conn, prev, curr)
    closures = closure_changes(conn, prev, curr)

    lines = [f"# 清單變化報告 {date_str}", ""]
    if prev is None:
        lines.append("> 初始快照，無上一次匯入可比對。")
        lines.append("")

    lines.append(f"## 新增店家（{len(added)}）")
    for p in added:
        lines.append(f"- {p['title']}（{', '.join(p['lists'])}）{p['url']}")
    lines.append("")

    lines.append(f"## 消失店家（{len(removed)}）")
    lines.append("> 可能是你自行移除，或本次 Takeout 未含。可拿去 Google Maps 手動確認。")
    for p in removed:
        lines.append(f"- {p['title']}（原清單：{', '.join(p['lists'])}）{p['url']}")
    lines.append("")

    lines.append(f"## 所屬清單變化（{len(lists)}）")
    for c in lists:
        parts = []
        if c['added_lists']:
            parts.append(f"加入 {', '.join(c['added_lists'])}")
        if c['removed_lists']:
            parts.append(f"移出 {', '.join(c['removed_lists'])}")
        lines.append(f"- {c['title']}：{'；'.join(parts)}")
    lines.append("")

    lines.append(f"## 歇業狀態變化（{len(closures)}）")
    for c in closures:
        lines.append(f"- {c['title']}：{c['old_status']} → {c['new_status']}")
    lines.append("")
    return "\n".join(lines)


def write_report(conn, out_dir='data/output', date_str=None):
    prev, curr = latest_two_imports(conn)
    if curr is None:
        return None
    if date_str is None:
        with conn.cursor() as cur:
            cur.execute("SELECT to_char(imported_at, 'YYYY-MM-DD') FROM imports WHERE id=%s",
                        (curr,))
            date_str = cur.fetchone()[0]
    os.makedirs(out_dir, exist_ok=True)

    md = render_markdown(conn, prev, curr, date_str)
    md_path = os.path.join(out_dir, f"changes_{date_str}.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)

    csv_path = os.path.join(out_dir, f"changes_{date_str}.csv")
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['變化類型', '店名', '清單/狀態', '連結'])
        for p in added_places(conn, prev, curr):
            w.writerow(['新增', p['title'], ', '.join(p['lists']), p['url']])
        for p in removed_places(conn, prev, curr):
            w.writerow(['消失', p['title'], ', '.join(p['lists']), p['url']])
        for c in list_changes(conn, prev, curr):
            detail = f"+{c['added_lists']} -{c['removed_lists']}"
            w.writerow(['清單變化', c['title'], detail, ''])
        for c in closure_changes(conn, prev, curr):
            w.writerow(['歇業變化', c['title'], f"{c['old_status']}→{c['new_status']}", ''])
    return md_path
