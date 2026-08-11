"""gapi.py — 參數化 Google API 函式與純輔助函式。

從 export_to_sheets.py / verify_stores.py 移植，改為可獨立匯入的參數化版本：
原始程式依賴模組層級全域 MODEL_NAME（僅在各自 main() 內賦值），
故無法直接 import 使用；本模組將其改為函式參數 model_name。

邏輯與原始碼保持一致，僅做參數化 / 改名 / 欄位名稱調整（詳見各函式註解）。
"""

import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from hours_normalize import parse_place_details_response

# 注意：兩個原始模組各自定義了同名但數值不同的 MAX_RETRIES 全域常數
# （export_to_sheets.py = 5，供 classify_cuisine_and_details 使用；
#  verify_stores.py = 4，供 query_gemini_batch 使用）。
# 為忠實移植兩者原本的重試次數，此處拆成兩個獨立常數，不合併為單一值。
_CLASSIFY_MAX_RETRIES = 5  # 同 export_to_sheets.py 的 MAX_RETRIES（classify_batch 使用）
_VERIFY_MAX_RETRIES = 4    # 同 verify_stores.py 的 MAX_RETRIES（gemini_verify_batch 使用）


# === 純輔助函式（無網路） ===

def heuristic_classify(title, note):
    """自 export_to_sheets.py:306-381 完整複製，內容不變。"""
    title_lower = title.lower()
    note_lower = note.lower() if note else ''
    combined = title_lower + " " + note_lower

    types = []
    avg_spending = 150

    # 1. 偵測非餐飲或免費景點
    if any(x in combined for x in [
        '景點', '公園', '大學', '中心', '博物館', '廟', '古蹟', '紀念館',
        '影城', '戲院', '球場', '體育館', '圖書館', '車站', '機場',
        '飯店', '酒店', '旅店', '民宿', '商旅'
    ]):
        return '其他', 0

    is_dining = False

    # 義式
    if any(x in combined for x in ['義大利麵', '披薩', '比薩', '義式', 'pasta', 'pizza', 'milano', 'banco']):
        types.append('義式')
        avg_spending = 350
        is_dining = True
    # 日式
    elif any(x in combined for x in [
        '拉麵', '壽司', '居酒屋', '日式', '和食', '鰻魚', '刺身', '生魚片',
        '丼', '串燒', '天婦羅', '安兵衛', 'naniwa', 'sojibō', 'yagura', '吉塚'
    ]):
        types.append('日式')
        avg_spending = 300
        if '拉麵' in combined or '麵' in combined:
            avg_spending = 250
        elif '居酒屋' in combined or '燒肉' in combined or '鰻' in combined:
            avg_spending = 600
        is_dining = True
    # 美式
    elif any(x in combined for x in ['漢堡', '美式', 'burger', '牛排', '薯條', 'steak', 'the lobbyof simple kaffa']):
        types.append('美式')
        avg_spending = 400
        is_dining = True
    # 韓式
    elif any(x in combined for x in ['韓式', '韓國', '韓華園', '韓國美食', '烤冷麵', '部隊鍋', '韓餐']):
        types.append('韓式')
        avg_spending = 350
        is_dining = True
    # 東南亞式
    elif any(x in combined for x in ['泰式', '東南亞', '越式', '星馬', '印尼', '甩餅', '咖哩', '印度']):
        types.append('東南亞式')
        avg_spending = 250
        is_dining = True
    # 中式
    elif any(x in combined for x in [
        '麵', '飯', '餃', '包', '羹', '粥', '湯', '鵝肉', '鴨肉', '滷肉', '魯肉',
        '小吃', '滷味', '燒餅', '油條', '肉粥', '餛飩', '抄手', '臭豆腐', '涼麵',
        '炒麵', '火鍋', '涮牛肉', '海鮮', '熱炒', '燉鰻', '豬血', '肉圓', '米糕',
        '當歸', '食堂', '茶餐廳', '港式'
    ]):
        types.append('中式')
        avg_spending = 120
        if ('火鍋' in combined or '涮' in combined or '海鮮' in combined
                or '熱炒' in combined or '餐廳' in combined):
            avg_spending = 450
        is_dining = True

    if not is_dining:
        if any(x in combined for x in [
            '咖啡', 'cafe', '烘焙', '麵包', '茶', '甜點', '蛋糕', '冰', '豆花',
            '下午茶', '鬆餅', '雞蛋糕', '糖餅', '拿鐵', '焙茶', '手搖', '大茗', '果子', '飲料'
        ]):
            types.append('其他')
            avg_spending = 150
        else:
            types.append('其他')
            avg_spending = 150

    return ','.join(types), avg_spending


def haversine_distance(lat1, lon1, lat2, lon2):
    """自 export_to_sheets.py:514-525 複製，內容不變。"""
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
        return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)
    except Exception:
        return None


def name_similarity(orig, returned):
    """自 verify_stores.py:94-106 複製，內容不變。

    計算原始店名與 Find Place 返回店名的相似度（0~1）。
    去除括號、空格、特殊符號後，以字元重疊率判斷。

    ⚠️ 已知限制：這是**單向**包含率，短店名容易虛高——「小林」對「小林眼鏡」得 1.0。
    加長度懲罰會誤殺「安咖哩」→「安咖哩 新竹店」這類正當的分店展開（本資料集很常見），
    故改由 county_agrees() 用縣市把關；同縣市的同前綴異店仍無法只靠字元區分。
    """
    def clean(s):
        return re.sub(r'[（）()\s/,、\-．·　【】『』「」{}｛｝\[\]]', '', s)
    a = clean(orig)[:10]   # 取前 10 個有效字元（店名頭部最具代表性）
    b = clean(returned)
    if not a:
        return 0.0
    matched = sum(1 for c in a if c in b)
    return matched / len(a)


_COUNTY_RE = re.compile(r'[一-鿿]{2}[縣市]')


def extract_county(address):
    """從地址取出「◯◯縣/市」，取不到回 None（外國地址、空地址）。"""
    m = _COUNTY_RE.search(address or '')
    return m.group(0) if m else None


def county_agrees(ours, returned):
    """我方地址與 Find Place 回傳地址的縣市是否相容。

    任一方取不到縣市（地址空、外國地址）→ 視為相容，退回只看店名的舊行為。
    兩邊都有且不同 → 不是同一家店，擋掉以免把別家的狀態／地址／營業時間寫進來。
    """
    a, b = extract_county(ours), extract_county(returned)
    return not (a and b) or a == b


def extract_json_from_text(text):
    """自 verify_stores.py:191-206 複製，內容不變。

    從 Gemini 回傳的純文字中提取 JSON 物件。
    """
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


def _parse_retry_delay(http_error):
    """自 export_to_sheets.py:500-510 複製，內容不變。

    從 429 回應中解析建議的等待秒數，預設 65 秒。
    （供下方 API 函式重試用；亦等同 verify_stores.parse_retry_delay 的邏輯。）
    """
    try:
        body = json.loads(http_error.read().decode('utf-8'))
        for detail in body.get('error', {}).get('details', []):
            if detail.get('@type') == 'type.googleapis.com/google.rpc.RetryInfo':
                delay_str = detail.get('retryDelay', '60s')
                return int(delay_str.rstrip('s')) + 5
    except Exception:
        pass
    return 65


# === API 函式（需金鑰，網路） ===

def geocode(address, maps_api_key):
    """同 export_to_sheets.geocode_with_maps_api（export_to_sheets.py:144-158），
    改名為 geocode，內容不變。

    使用 Google Maps Geocoding API 取得精確座標，回傳 (lat, lng) 或 (None, None)。
    """
    if not address or not maps_api_key:
        return None, None
    encoded = urllib.parse.quote(address)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded}&key={maps_api_key}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('status') == 'OK' and data.get('results'):
                loc = data['results'][0]['geometry']['location']
                return loc['lat'], loc['lng']
    except Exception:
        pass
    return None, None


def place_details(place_id, maps_api_key):
    """用**正規 place_id（ChIJ…）**呼叫 Place Details API，取回地址與營業時間。

    ⚠️ Google Maps URL 內的 hex CID（`0xA:0xB`）**不是**合法 place_id，
    直接傳入會得到 `INVALID_REQUEST`（實測 error_message="Invalid 'placeid' parameter"）。
    故 enrich 流程須先以 find_place_id() 由店名+地址解析出 ChIJ… 再呼叫本函式。
    對 parse_place_details_response 的依賴：from hours_normalize import …（repo 根層模組）。
    需要 MAPS_API_KEY 且已啟用 Places API。
    回傳 {"address": str, "hours": list|None, "hours_text": str}。
    """
    empty = {"address": "", "hours": None, "hours_text": ""}
    if not place_id or not maps_api_key:
        return empty
    try:
        params = urllib.parse.urlencode({
            'place_id': place_id,
            'fields':   'formatted_address,name,opening_hours',
            'language': 'zh-TW',
            'key':      maps_api_key,
        })
        api_url = f"https://maps.googleapis.com/maps/api/place/details/json?{params}"
        with urllib.request.urlopen(api_url, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        status = data.get('status', '')
        if status == 'OK':
            return parse_place_details_response(data)
        if status == 'REQUEST_DENIED':
            raise RuntimeError('Places API 未啟用，請在 Google Cloud Console 開啟 Places API')
    except RuntimeError:
        raise
    except Exception as e:
        print(f"  [Place Details] 查詢失敗: {e}")
    return empty


def find_place_status(name, address, maps_api_key):
    """以店名 + 地址呼叫 Find Place from Text，一次取得 verify 需要的 business_status
    與 enrich 需要的正規 place_id（ChIJ…），供兩者共用（省 Maps 額度）。

    回傳 dict：
      status       : 'OPERATIONAL' | 'CLOSED_TEMPORARILY' | 'CLOSED_PERMANENTLY'
                     | 'NOT_FOUND'（Google Maps 已無此店，強烈暗示停業）
                     | 'UNKNOWN'  （API 有回應但無法判斷）
                     | 'ERROR'    （呼叫失敗）
      address      : str
      price_level  : int | None（0-4）
      match        : 'EXACT' | 'FUZZY' | 'NO_MATCH' | 'NO_RESULTS'
      place_id     : str | None（僅名稱相似度達標的相符店才給，供 Place Details 查營業時間）
    """
    store_name = name
    if not maps_api_key:
        return {'status': 'ERROR', 'address': '', 'price_level': None, 'match': 'SKIP', 'place_id': None}

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
            return {'status': 'NOT_FOUND', 'address': '', 'price_level': None, 'match': 'NO_RESULTS', 'place_id': None}

        if api_status != 'OK':
            return {'status': 'UNKNOWN', 'address': '', 'price_level': None, 'match': 'API_ERROR', 'place_id': None}

        # 取第一候選，計算名稱相似度
        top = candidates[0]
        returned_name = top.get('name', '')
        similarity = name_similarity(store_name, returned_name)

        if similarity >= 0.4 and county_agrees(address, top.get('formatted_address', '')):
            match_type = 'EXACT' if similarity >= 0.7 else 'FUZZY'
            return {
                'status':      top.get('business_status', 'UNKNOWN'),
                'address':     top.get('formatted_address', ''),
                'price_level': top.get('price_level'),
                'match':       match_type,
                'place_id':    top.get('place_id'),   # 相符才給，供 enrich 查營業時間
            }
        else:
            # 店名不符或縣市不符 → 不是同一家；不給 place_id 以免補錯店。
            # NOT_FOUND 不在 export 的永久歇業名單內，誤判只會少補資料、不會把店踢出抽籤池。
            return {'status': 'NOT_FOUND', 'address': '', 'price_level': None, 'match': 'NO_MATCH', 'place_id': None}

    except urllib.error.HTTPError as e:
        print(f"    [Maps API HTTP {e.code}]")
        return {'status': 'ERROR', 'address': '', 'price_level': None, 'match': 'HTTP_ERR', 'place_id': None}
    except Exception as e:
        print(f"    [Maps API 錯誤] {e}")
        return {'status': 'ERROR', 'address': '', 'price_level': None, 'match': 'EXCEPTION', 'place_id': None}


def classify_batch(items, home_address, api_key, model_name):
    """移植 export_to_sheets.classify_cuisine_and_details（export_to_sheets.py:385-497）。

    將函式內所有 MODEL_NAME 全域改為參數 model_name；其餘（Gemini 呼叫、
    responseSchema、429/500/503 重試、失敗退回 heuristic_classify）保持不變。
    items 每筆需有 title/address 鍵。
    """
    # 建立啟發式分類備援資料
    fallback = []
    for item in items:
        t, spending = heuristic_classify(item['title'], item.get('note', ''))
        fallback.append({
            'types':        t,
            'avg_spending': spending,
            'lat':          item.get('lat'),
            'lng':          item.get('lng'),
            'address':      item['address']
        })

    if not api_key:
        return fallback

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    prompt = (
        "分析以下店家的名稱和輸入地址（若地址為空，請由店名補足預估的詳細中文地址）。\n"
        "請為每一筆判斷「餐飲類型」、「預估人均消費（台幣）」、「預估經緯度座標」及「預估中文詳細地址」。\n"
    )
    if home_address:
        prompt += (
            f"\n參考資訊：使用者的住家位於「{home_address}」。"
            "此資訊僅供後續距離計算使用，\n"
            "請勿以住家城市強制推斷店家位置。"
            "每筆店家請依照店名本身在台灣的實際位置給出正確座標與地址，\n"
            "若一家店明確位於台中、台北、高雄等其他城市，請如實標記，不要改成住家所在縣市。\n"
        )
    prompt += (
        "\n餐飲類型選項（可複選，以半角逗號隔開，例如：中式,日式）：\n"
        "  中式 / 日式 / 義式 / 美式 / 韓式 / 東南亞式 / 其他\n\n"
        "說明：\n"
        "1. 餐飲類型：非餐飲場所（景點、飯店、公園、商店等）請標記「其他」。\n"
        "2. 人均消費：預估台幣整數（平價小吃約 80~150，中價位約 350~500，"
        "高檔約 1200；非餐飲或免費景點請填 0）。\n"
        "3. 經緯度：根據店名判斷其在台灣的實際 GPS 座標（lat/lng），務必反映真實地理位置。\n"
        "4. 詳細地址：店家的中文詳細地址（含正確的縣市），若完全不知請填「未知地址」。\n"
        "5. 請依照提供的 index 對應填寫。\n\n"
        "請嚴格以下列 JSON 格式回傳（不含 Markdown 或說明文字）：\n"
        '{"results": [{"index": 0, "types": "中式", "avg_spending": 150, '
        '"lat": 25.033, "lng": 121.564, "address": "台北市大安區信義路二段194號"}]}\n\n'
        "待處理店家：\n"
    )
    for idx, item in enumerate(items):
        prompt += f'Index {idx}: 店名="{item["title"]}", 地址="{item["address"]}"\n'

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "results": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "index": {"type": "INTEGER"},
                                "types": {"type": "STRING"},
                                "avg_spending": {"type": "INTEGER"},
                                "lat": {"type": "NUMBER"},
                                "lng": {"type": "NUMBER"},
                                "address": {"type": "STRING"}
                            },
                            "required": ["index", "types", "avg_spending", "lat", "lng", "address"]
                        }
                    }
                },
                "required": ["results"]
            }
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={"Content-Type": "application/json"}
    )

    for attempt in range(_CLASSIFY_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                data = json.loads(res['candidates'][0]['content']['parts'][0]['text'])
                results_map = {r['index']: r for r in data.get('results', [])}
                return [
                    {
                        'types': results_map[i]['types'] if i in results_map else '其他',
                        'avg_spending': results_map[i]['avg_spending'] if i in results_map else 0,
                        'lat': results_map[i].get('lat') if i in results_map else None,
                        'lng': results_map[i].get('lng') if i in results_map else None,
                        'address': results_map[i].get('address', '') if i in results_map else ''
                    }
                    for i in range(len(items))
                ]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503):
                delay = _parse_retry_delay(e) if e.code == 429 else 30
                if attempt < _CLASSIFY_MAX_RETRIES:
                    label = '超過速率限制' if e.code == 429 else f'服務暫時不可用 (HTTP {e.code})'
                    print(f"    [{e.code}] {label}，等待 {delay} 秒後重試（第 {attempt + 1}/{_CLASSIFY_MAX_RETRIES} 次）...")
                    time.sleep(delay)
                    continue
                print("    [錯誤] 達到最大重試次數，將使用本地啟發式分類作為備援方案。")
            else:
                print(f"    [錯誤] API 回傳 HTTP {e.code}，將使用本地啟發式分類作為備援方案。")
            return fallback
        except Exception as e:
            print(f"    [錯誤] 呼叫 Gemini API 失敗: {e}，將使用本地啟發式分類作為備援方案。")
            return fallback

    return fallback


def gemini_verify_batch(items, model_name, gemini_key):
    """移植 verify_stores.query_gemini_batch（verify_stores.py:209-278）。

    將讀取欄位由 s['店名']/s['地址'] 改為 s['title']/s['address']；其餘不變。

    使用 Gemini + Google Search Grounding 批次確認店家狀態。

    回傳 list（與 items 等長），每項：
      status   : 'OPEN' | 'CLOSED' | 'UNCERTAIN'
      address  : str（如有更精確地址）
      price_tw : int | None
    """
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={gemini_key}"
    )
    uncertain = [{'status': 'UNCERTAIN', 'address': '', 'price_tw': None}] * len(items)

    items_text = ""
    for i, s in enumerate(items):
        items_text += f'Index {i}: 店名="{s["title"]}", 地址="{s["address"]}"\n'

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

    for attempt in range(_VERIFY_MAX_RETRIES + 1):
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
                    for i in range(len(items))
                ]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                delay = _parse_retry_delay(e)
                if attempt < _VERIFY_MAX_RETRIES:
                    print(f"    [429] 速率限制，等待 {delay} 秒後重試（{attempt+1}/{_VERIFY_MAX_RETRIES}）...")
                    time.sleep(delay)
                    continue
            print(f"    [Gemini HTTP {e.code}] 查詢失敗，該批標記 UNCERTAIN")
            return uncertain
        except Exception as e:
            print(f"    [Gemini 錯誤] {e}，該批標記 UNCERTAIN")
            return uncertain

    return uncertain


# === Factory helpers（把金鑰/模型綁定成 enrich/verify 需要的注入介面） ===

def make_classifier(api_key, model_name, home_address=''):
    """回傳 enrich_pending 需要的 classify(items)->list。無 api_key 時退回本地啟發式。"""
    def classify(items):
        if not api_key:
            out = []
            for it in items:
                types, spend = heuristic_classify(it['title'], '')
                out.append({'types': types, 'avg_spending': spend,
                            'lat': None, 'lng': None, 'address': it.get('address', '')})
            return out
        return classify_batch(items, home_address, api_key, model_name)
    return classify


def make_find_place(maps_api_key):
    """回傳 verify_import 需要的 find_place(name,address)->dict；無金鑰回傳 ERROR。

    **同一 (name,address) 於單次執行內記憶化（memoize）**：enrich 與 verify 共用同一顆
    find_place，故每家店的 Find Place 只打一次網路（省 Maps 額度）。回傳含 place_id，
    supplying 兩者所需（verify 用 status、enrich 用 place_id）。
    """
    memo = {}
    transient = {'ERROR', 'UNKNOWN'}

    def find_place(name, address):
        if not maps_api_key:
            return {'status': 'ERROR', 'address': '', 'price_level': None, 'match': 'SKIP', 'place_id': None}
        key = (name, address)
        if key not in memo:
            res = find_place_status(name, address, maps_api_key)
            if res.get('status') in transient:
                return res      # 逾時／API 暫時性錯誤不記憶，否則一次失敗會毒害這家店整輪
            memo[key] = res
        return memo[key]

    def remember(name, address, result):
        """替同一家店的另一組 (name,address) 登記同一筆結果。

        enrich 會把地址換成 Google 版並存回 DB，稍後 verify 以新地址查詢就會 memo miss、
        白打第二次 Find Place。登記別名即可讓每家店維持只打一次網路。
        """
        memo.setdefault((name, address), result)

    find_place.remember = remember
    return find_place


def make_place_details(maps_api_key, find_place=None):
    """回傳 enrich_pending 需要的 place_details(name, address)->dict。

    用共用的 find_place（make_find_place 產生、已記憶化）取正規 place_id
    （hex CID 不能直接查 details），再呼叫 place_details() 取地址+營業時間。
    無金鑰、未提供 find_place、找不到店或相似度不足 → 回空結果。
    """
    empty = {'address': '', 'hours': None, 'hours_text': ''}

    def _resolve(name, address):
        if not maps_api_key or find_place is None:
            return dict(empty)
        fp = find_place(name, address)
        pid = fp.get('place_id') if fp else None
        if not pid:
            return dict(empty)
        det = place_details(pid, maps_api_key)
        new_address = det.get('address') or ''
        if new_address and new_address != address:
            # 呼叫端（enrich）會把地址換成這個 Google 版本並寫回 DB，
            # 先登記別名，稍後 verify 用新地址查同一家店才不會再打一次 Find Place。
            remember = getattr(find_place, 'remember', None)
            if remember:
                remember(name, new_address, fp)
        return det
    return _resolve
