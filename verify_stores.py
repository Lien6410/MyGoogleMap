"""
verify_stores.py — 驗證 MyGoogleMap_Stores.csv

查詢策略（雙重保障）：
  1. Google Maps「Find Place from Text」API（主要）
     - 以店名 + 地址搜尋，取第一候選的 business_status
     - 若返回名稱與原店名不相符 → 判定為 NOT_FOUND（已從 Google Maps 移除，強烈暗示停業）
     - CLOSED_PERMANENTLY / NOT_FOUND → 移除
  2. Gemini + Google Search Grounding（備援）
     - 用於 Find Place 返回 UNKNOWN 或比對失敗仍有疑慮的情況

注意：CID（0x...:0x...）格式不被 Places API 接受，改用 Find Place from Text。

輸出：
  MyGoogleMap_Stores_verified.csv  ← 移除停業後的乾淨清單
  MyGoogleMap_Stores_closed.csv    ← 被移除的停業店家（備查）

需在 .env 設定：
  MAPS_API_KEY=   （需啟用 Places API）
  GEMINI_API_KEY= （備援）

執行：
  uv run verify_stores.py
"""

import os
import re
import csv
import json
import time
import sys
import urllib.parse
import urllib.request
import urllib.error

# ── 設定 ─────────────────────────────────────────────────────────────────────
INPUT_CSV = "MyGoogleMap_Stores.csv"
OUTPUT_CSV = "MyGoogleMap_Stores_verified.csv"
CLOSED_CSV = "MyGoogleMap_Stores_closed.csv"
CACHE_FILE = "verify_cache.json"
DEFAULT_MODEL = "gemini-2.5-flash"
BATCH_SIZE = 5       # Gemini 模式：每批筆數（搜尋時不宜太多）
BATCH_DELAY = 10      # 批次間等待秒數（控制速率）
MAX_RETRIES = 4

# price_level（0-4）→ 台幣人均估算
PRICE_MAP = {0: 0, 1: 120, 2: 350, 3: 800, 4: 1500}


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def load_env():
    env = {}
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def extract_cid(url):
    """從 Google Maps URL 取出 CID（僅用於 cache key，不作 API 查詢）。"""
    if not url:
        return None
    m = re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', url, re.IGNORECASE)
    return m.group(1) if m else None


def store_cache_key(store):
    cid = extract_cid(store.get('網址', ''))
    return cid if cid else f"{store['店名']}|{store['地址']}"


def name_similarity(orig, returned):
    """
    計算原始店名與 Find Place 返回店名的相似度（0~1）。
    去除括號、空格、特殊符號後，以字元重疊率判斷。
    """
    def clean(s):
        return re.sub(r'[（）()\s/,、\-．·　【】『』「」{}｛｝\[\]]', '', s)
    a = clean(orig)[:10]   # 取前 10 個有效字元（店名頭部最具代表性）
    b = clean(returned)
    if not a:
        return 0.0
    matched = sum(1 for c in a if c in b)
    return matched / len(a)


def parse_retry_delay(http_error):
    try:
        body = json.loads(http_error.read().decode('utf-8'))
        for detail in body.get('error', {}).get('details', []):
            if detail.get('@type') == 'type.googleapis.com/google.rpc.RetryInfo':
                return int(detail.get('retryDelay', '60s').rstrip('s')) + 5
    except Exception:
        pass
    return 65


# ── Google Maps Find Place from Text API ──────────────────────────────────────

def query_find_place(store_name, address, maps_api_key):
    """
    以店名 + 地址呼叫 Find Place from Text，取得 business_status / 地址 / 消費等級。

    回傳 dict：
      status       : 'OPERATIONAL' | 'CLOSED_TEMPORARILY' | 'CLOSED_PERMANENTLY'
                     | 'NOT_FOUND'（Google Maps 已無此店，強烈暗示停業）
                     | 'UNKNOWN'  （API 有回應但無法判斷）
                     | 'ERROR'    （呼叫失敗）
      address      : str
      price_level  : int | None（0-4）
      match        : 'EXACT' | 'FUZZY' | 'NO_MATCH' | 'NO_RESULTS'
    """
    if not maps_api_key:
        return {'status': 'ERROR', 'address': '', 'price_level': None, 'match': 'SKIP'}

    # 地址取前 15 字（縣市 + 區 + 路名），避免門牌號碼造成噪音
    addr_short = address[:15] if address else ''
    query = f"{store_name} {addr_short}".strip()

    params = urllib.parse.urlencode({
        'input':     query,
        'inputtype': 'textquery',
        'fields':    'business_status,formatted_address,price_level,name,place_id',
        'language':  'zh-TW',
        'key':       maps_api_key,
    })
    url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?{params}"

    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        api_status = data.get('status', '')
        candidates = data.get('candidates', [])

        if api_status == 'ZERO_RESULTS' or not candidates:
            return {'status': 'NOT_FOUND', 'address': '', 'price_level': None, 'match': 'NO_RESULTS'}

        if api_status != 'OK':
            return {'status': 'UNKNOWN', 'address': '', 'price_level': None, 'match': 'API_ERROR'}

        # 取第一候選，計算名稱相似度
        top = candidates[0]
        returned_name = top.get('name', '')
        similarity = name_similarity(store_name, returned_name)

        if similarity >= 0.4:
            match_type = 'EXACT' if similarity >= 0.7 else 'FUZZY'
            return {
                'status':      top.get('business_status', 'UNKNOWN'),
                'address':     top.get('formatted_address', ''),
                'price_level': top.get('price_level'),
                'match':       match_type,
            }
        else:
            # 返回的店名與原始店名不符 → 此店已從 Google Maps 消失（可能停業）
            return {'status': 'NOT_FOUND', 'address': '', 'price_level': None, 'match': 'NO_MATCH'}

    except urllib.error.HTTPError as e:
        print(f"    [Maps API HTTP {e.code}]")
        return {'status': 'ERROR', 'address': '', 'price_level': None, 'match': 'HTTP_ERR'}
    except Exception as e:
        print(f"    [Maps API 錯誤] {e}")
        return {'status': 'ERROR', 'address': '', 'price_level': None, 'match': 'EXCEPTION'}


# ── Gemini Search Grounding（備援） ───────────────────────────────────────────

def extract_json_from_text(text):
    """從 Gemini 回傳的純文字中提取 JSON 物件。"""
    # 嘗試直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 找第一個 { … } 區塊
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None


def query_gemini_batch(stores_batch, model_name, gemini_key):
    """
    使用 Gemini + Google Search Grounding 批次確認店家狀態。

    回傳 list（與 stores_batch 等長），每項：
      status   : 'OPEN' | 'CLOSED' | 'UNCERTAIN'
      address  : str（如有更精確地址）
      price_tw : int | None
    """
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={gemini_key}"
    )
    uncertain = [{'status': 'UNCERTAIN', 'address': '', 'price_tw': None}] * len(stores_batch)

    items_text = ""
    for i, s in enumerate(stores_batch):
        items_text += f'Index {i}: 店名="{s["店名"]}", 地址="{s["地址"]}"\n'

    prompt = (
        "你是一個餐廳資訊核查助手。請使用 Google Search 查詢以下每家台灣餐廳/店家在 2025～2026 年的最新營業狀態，"
        "並以 JSON 格式回傳結果，格式如下：\n"
        '{"results": [{"index": 0, "status": "OPEN", "address": "", "price_tw": 150}]}\n\n'
        "欄位說明：\n"
        "- status: 只能是 OPEN（確認正常營業）、CLOSED（確認已永久停業/倒閉）、UNCERTAIN（找不到足夠資訊）\n"
        "- address: 若找到更精確的繁體中文地址請填入，否則填空字串\n"
        "- price_tw: 預估台幣人均消費整數（無法確認填 null）\n\n"
        "重要：只輸出 JSON，不要有任何說明文字。\n\n"
        f"店家清單：\n{items_text}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={"Content-Type": "application/json"},
    )

    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                parts = res.get('candidates', [{}])[0].get('content', {}).get('parts', [])
                text = next((p.get('text', '') for p in parts if 'text' in p), '')
                data = extract_json_from_text(text)
                if not data:
                    print("    [Gemini] 無法解析 JSON 回應，該批標記 UNCERTAIN")
                    return uncertain
                results_map = {r['index']: r for r in data.get('results', [])}
                return [
                    results_map.get(i, {'status': 'UNCERTAIN', 'address': '', 'price_tw': None})
                    for i in range(len(stores_batch))
                ]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                delay = parse_retry_delay(e)
                if attempt < MAX_RETRIES:
                    print(f"    [429] 速率限制，等待 {delay} 秒後重試（{attempt+1}/{MAX_RETRIES}）...")
                    time.sleep(delay)
                    continue
            print(f"    [Gemini HTTP {e.code}] 查詢失敗，該批標記 UNCERTAIN")
            return uncertain
        except Exception as e:
            print(f"    [Gemini 錯誤] {e}，該批標記 UNCERTAIN")
            return uncertain

    return uncertain


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    print("====== MyGoogleMap 店家狀態驗證工具 ======\n")

    env = load_env()
    maps_key = env.get('MAPS_API_KEY', '') or os.environ.get('MAPS_API_KEY', '')
    gemini_key = env.get('GEMINI_API_KEY', '') or os.environ.get('GEMINI_API_KEY', '')
    model_name = env.get('GEMINI_MODEL', DEFAULT_MODEL)

    if maps_key:
        print("[主要模式] Google Maps Find Place from Text API")
    if gemini_key:
        print(f"[備援模式] Gemini Search Grounding（{model_name}）")
    if not maps_key and not gemini_key:
        print("[錯誤] 請在 .env 設定 MAPS_API_KEY 或 GEMINI_API_KEY")
        sys.exit(1)

    # 讀取輸入 CSV
    stores = []
    try:
        with open(INPUT_CSV, encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                stores.append(dict(row))
    except FileNotFoundError:
        print(f"[錯誤] 找不到 {INPUT_CSV}，請先執行 export_to_sheets.py")
        sys.exit(1)

    print(f"讀取 {len(stores)} 筆店家資料。")
    cache = load_cache()

    # ── 清除舊版快取中無效的 Maps API 條目（舊版用 CID 查詢，會得到 INVALID_REQUEST → UNKNOWN） ──
    stale_keys = [
        k for k, v in cache.items()
        if v.get('source') in ('maps', 'pending')
        and v.get('status') in ('UNKNOWN', 'ERROR', None)
        and 'match' not in v   # 新版 Find Place 結果都有 match 欄位，舊版沒有
    ]
    if stale_keys:
        for k in stale_keys:
            del cache[k]
        save_cache(cache)
        print(f"清除 {len(stale_keys)} 筆舊版無效快取，將重新查詢。")

    # ── 第一階段：Maps API 查詢（Find Place from Text） ───────────────────────
    if maps_key:
        need_maps = [s for s in stores if store_cache_key(s) not in cache]
        print(f"\n[Maps API] 需查詢 {len(need_maps)} 筆（已快取 {len(stores) - len(need_maps)} 筆）")

        for idx, store in enumerate(need_maps):
            ck = store_cache_key(store)
            result = query_find_place(store['店名'], store.get('地址', ''), maps_key)
            cache[ck] = {'source': 'maps', **result}

            if (idx + 1) % 20 == 0:
                save_cache(cache)
                print(f"  進度：{idx+1}/{len(need_maps)}")
            time.sleep(0.15)   # ~6-7 QPS，Find Place 預設上限約 10 QPS

        save_cache(cache)
        print("[Maps API] 查詢完成。")

    # ── 第二階段：Gemini 備援 ──────────────────────────────────────────────────
    # 觸發條件：Maps API 返回 UNKNOWN/ERROR，或 NO_MATCH 需要二次確認
    if gemini_key:
        need_gemini = [
            s for s in stores
            if cache.get(store_cache_key(s), {}).get('status') in ('UNKNOWN', 'ERROR', None)
            or (cache.get(store_cache_key(s), {}).get('status') == 'NOT_FOUND'
                and cache.get(store_cache_key(s), {}).get('match') == 'NO_MATCH')
        ]
        if need_gemini:
            print(f"\n[Gemini] 需補查 {len(need_gemini)} 筆（Maps 無法確認）...")
            for batch_start in range(0, len(need_gemini), BATCH_SIZE):
                batch = need_gemini[batch_start:batch_start + BATCH_SIZE]
                end = min(batch_start + BATCH_SIZE, len(need_gemini))
                print(f"  處理第 {batch_start+1}～{end} 筆...")
                results = query_gemini_batch(batch, model_name, gemini_key)
                for store, result in zip(batch, results):
                    ck = store_cache_key(store)
                    # Gemini 確認 CLOSED 才覆蓋 Maps 結果；UNCERTAIN 保留 Maps NOT_FOUND
                    gemini_status = result.get('status', 'UNCERTAIN')
                    prev = cache.get(ck, {})
                    if gemini_status == 'CLOSED':
                        cache[ck] = {
                            'source':      'gemini',
                            'status':      'CLOSED',
                            'address':     result.get('address', prev.get('address', '')),
                            'price_level': None,
                            'price_tw':    result.get('price_tw'),
                            'match':       prev.get('match', ''),
                        }
                    elif gemini_status == 'OPEN':
                        cache[ck] = {
                            'source':      'gemini',
                            'status':      'OPERATIONAL',
                            'address':     result.get('address', prev.get('address', '')),
                            'price_level': None,
                            'price_tw':    result.get('price_tw'),
                            'match':       prev.get('match', ''),
                        }
                    else:
                        # UNCERTAIN：保留 Maps NOT_FOUND 狀態（仍會移除）
                        cache[ck]['source'] = 'gemini+maps'
                save_cache(cache)
                if batch_start + BATCH_SIZE < len(need_gemini):
                    time.sleep(BATCH_DELAY)
            print("[Gemini] 補查完成。")

    # ── 第三階段：整理結果 ─────────────────────────────────────────────────────
    open_stores = []
    closed_stores = []

    for store in stores:
        ck = store_cache_key(store)
        result = cache.get(ck, {})
        status = result.get('status', 'UNCERTAIN')
        source = result.get('source', '')

        # 判斷是否停業
        # NOT_FOUND（Maps 找不到此店）→ 移除（店已從 Google Maps 消失＝強烈暗示停業）
        is_closed = status in ('CLOSED_PERMANENTLY', 'CLOSED_TEMPORARILY') or (
            status in ('CLOSED', 'NOT_FOUND')
        )

        # 更新地址（更詳細才覆寫）
        api_addr = result.get('address', '').strip()
        orig_addr = store.get('地址', '').strip()
        if api_addr and len(api_addr) >= len(orig_addr) and api_addr != orig_addr:
            store['地址'] = api_addr

        # 更新人均消費
        orig_spending = store.get('人均消費預估(元)', '未知')
        if source == 'maps' and result.get('price_level') is not None:
            pl = result['price_level']
            new_spending = PRICE_MAP.get(pl, '未知')
            # 只更新「未知」或「0」的欄位（保留原本已估算的值）
            if str(orig_spending) in ('未知', '0', ''):
                store['人均消費預估(元)'] = new_spending if new_spending else '未知'
        elif source == 'gemini' and result.get('price_tw'):
            if str(orig_spending) in ('未知', '0', ''):
                store['人均消費預估(元)'] = result['price_tw']

        # 確保 0 → 未知
        if str(store.get('人均消費預估(元)', '')) in ('0', ''):
            store['人均消費預估(元)'] = '未知'

        if is_closed:
            store['_close_status'] = status
            closed_stores.append(store)
        else:
            open_stores.append(store)

    # ── 輸出 CSV ────────────────────────────────────────────────────────────────
    fieldnames = ['店名', '地址', '網址', '餐飲類型', '來源清單',
                  '是否曾去過', '距離住家(公里)', '人均消費預估(元)', '備註']

    # 已驗證（乾淨）清單
    with open(OUTPUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(open_stores)
    print(f"\n[成功] 已驗證清單：{OUTPUT_CSV}（{len(open_stores)} 筆）")

    # 已停業清單
    with open(CLOSED_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames + ['停業狀態'], extrasaction='ignore')
        writer.writeheader()
        for store in closed_stores:
            store['停業狀態'] = store.pop('_close_status', '')
            writer.writerow(store)
    print(f"[成功] 已停業清單：{CLOSED_CSV}（{len(closed_stores)} 筆）")

    # ── 摘要 ────────────────────────────────────────────────────────────────────
    uncertain_cnt = sum(
        1 for s in open_stores
        if cache.get(store_cache_key(s), {}).get('status') in ('UNCERTAIN', 'UNKNOWN', 'ERROR', None)
    )

    print(f"""
====== 完成摘要 ======
  原始筆數：      {len(stores)}
  確認停業移除：  {len(closed_stores)} 筆
  狀態無法確認：  {uncertain_cnt} 筆（已保留，建議手動確認）
  輸出清單筆數：  {len(open_stores)} 筆
""")

    if closed_stores:
        print("已移除的店家：")
        for s in closed_stores:
            status_label = s.get('停業狀態', s.get('_close_status', ''))
            print(f"  ✗  {s['店名']}  [{status_label}]  {s.get('地址', '')[:30]}")

    print("\n下一步：確認無誤後，可將 MyGoogleMap_Stores_verified.csv 重新命名為 MyGoogleMap_Stores.csv，")
    print("        然後執行 export_to_sheets.py 重新產生 stores_data.js 供抽籤頁使用。")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[中斷] 使用者停止。已儲存進度至 verify_cache.json，重新執行可從中斷點繼續。")
