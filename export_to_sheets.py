import os
import re
import csv
import sys
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

# === 設定常數 ===
INPUT_FOLDER    = "input"    # 存放來源 CSV 的資料夾
OUTPUT_CSV      = "MyGoogleMap_Stores.csv"
OUTPUT_JS       = "stores_data.js"
CACHE_FILE      = "export_cache.json"   # 斷點續跑快取
DEFAULT_MODEL   = "gemini-2.5-flash"    # 可在 .env 設定 GEMINI_MODEL 覆寫
BATCH_DELAY     = 7          # 批次間隔秒數（控速，避免超過 10 RPM）
MAX_RETRIES     = 5          # 429 最大重試次數


# === 讀取 .env 設定 ===
def load_env():
    env = {}
    if os.path.exists('.env'):
        try:
            with open('.env', 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, val = line.split('=', 1)
                        env[key.strip()] = val.strip().strip('"').strip("'")
        except Exception as e:
            print(f"讀取 .env 失敗: {e}")
    return env


# === 進度快取（斷點續跑） ===
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[警告] 快取儲存失敗: {e}")


def cache_key(place):
    return place['url'] if place['url'] else f"{place['title']}|{place['address']}"


# === 掃描輸入資料夾內所有 CSV ===
def find_all_input_csvs(input_folder):
    """
    回傳 (filepath, list_name, is_visited) 清單。
    檔名含「回訪」的清單標記為已去過，其餘標記為未去過。
    """
    if not os.path.isdir(input_folder):
        return []
    results = []
    for f in sorted(os.listdir(input_folder)):
        if f.lower().endswith('.csv'):
            is_visited = '回訪' in f
            list_name  = f[:-4]  # 去除 .csv 副檔名
            results.append((os.path.join(input_folder, f), list_name, is_visited))
    return results


# === 自動偵測 CSV 欄位 ===
def detect_headers(header_row):
    mapping = {'title': None, 'note': None, 'url': None, 'address': None}
    for i, col in enumerate(header_row):
        col_clean = col.strip().lower()
        if col_clean in ['title', '標題', '名稱', 'name']:
            mapping['title'] = i
        elif col_clean in ['note', '備註', '說明', '備忘錄', 'notes', '筆記']:
            mapping['note'] = i
        elif col_clean in ['url', '網址', '連結', 'link']:
            mapping['url'] = i
        elif col_clean in ['address', '地址']:
            mapping['address'] = i

    if mapping['title'] is None:
        mapping['title'] = 0
    if mapping['address'] is None:
        for i, col in enumerate(header_row):
            if '地' in col or 'add' in col.lower():
                mapping['address'] = i
                break
    return mapping


# === 讀取單一 CSV ===
def read_csv(filename):
    places = []
    try:
        with open(filename, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                return []

            mapping = detect_headers(headers)
            max_idx = max((v for v in mapping.values() if v is not None), default=0)

            for row in reader:
                if not row or len(row) <= max_idx:
                    continue
                title   = row[mapping['title']].strip()   if mapping['title']   is not None else ''
                note    = row[mapping['note']].strip()    if mapping['note']    is not None and mapping['note'] < len(row) else ''
                url     = row[mapping['url']].strip()     if mapping['url']     is not None and mapping['url'] < len(row) else ''
                address = row[mapping['address']].strip() if mapping['address'] is not None and mapping['address'] < len(row) else ''

                if title:
                    places.append({'title': title, 'address': address, 'url': url, 'note': note})
    except Exception as e:
        print(f"讀取 {filename} 時出錯: {e}")
    return places


# === 住家地址定位 ===
def geocode_with_maps_api(address, maps_api_key):
    """使用 Google Maps Geocoding API 取得精確座標，回傳 (lat, lng) 或 (None, None)。"""
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


def geocode_address(address, api_key, maps_api_key=None):
    if not address:
        return None, None
    # 優先用 Google Maps Geocoding API（精確）
    if maps_api_key:
        lat, lng = geocode_with_maps_api(address, maps_api_key)
        if lat is not None:
            return lat, lng
    # 退回 Gemini AI 估算
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
    prompt = (
        f"請提供台灣地址或著名地標的預估經緯度：'{address}'。\n"
        "請嚴格以 JSON 格式回傳，不可有任何額外說明文字：\n"
        '{"lat": 25.033, "lng": 121.564}'
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "lat": {"type": "NUMBER"},
                    "lng": {"type": "NUMBER"}
                },
                "required": ["lat", "lng"]
            }
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={"Content-Type": "application/json"}
    )
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                res  = json.loads(resp.read().decode('utf-8'))
                data = json.loads(res['candidates'][0]['content']['parts'][0]['text'])
                return data.get('lat'), data.get('lng')
        except urllib.error.HTTPError as e:
            if e.code == 429:
                delay = _parse_retry_delay(e)
                if attempt < MAX_RETRIES:
                    print(f"  [429] 等待 {delay} 秒後重試住家定位...")
                    time.sleep(delay)
                    continue
            print(f"定位住家地址失敗: HTTP {e.code}")
            return None, None
        except Exception as e:
            print(f"定位住家地址失敗: {e}")
            return None, None
    return None, None


# === 從 Google Maps URL 提取 CID，並用 Place Details API 查詢精確地址 ===
def extract_cid_from_maps_url(url):
    """從 Google Maps URL 的 data= 參數中提取 CID（格式：0xA:0xB）。"""
    if not url:
        return None
    match = re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', url, re.IGNORECASE)
    return match.group(1) if match else None


def lookup_address_from_cid(cid_hex, maps_api_key):
    """用 Google Maps URL 中的 CID 十六進位（0xA:0xB）呼叫 Place Details API 取得精確地址。
    需要 MAPS_API_KEY 且已啟用 Places API。"""
    if not cid_hex or not maps_api_key:
        return ''
    try:
        params = urllib.parse.urlencode({
            'place_id': cid_hex,          # Place Details API 接受原始 0x...:0x... 格式
            'fields':   'formatted_address,name',
            'language': 'zh-TW',
            'key':      maps_api_key,
        })
        api_url = f"https://maps.googleapis.com/maps/api/place/details/json?{params}"
        with urllib.request.urlopen(api_url, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            status = data.get('status', '')
            if status == 'OK':
                return data.get('result', {}).get('formatted_address', '')
            if status == 'REQUEST_DENIED':
                raise RuntimeError('Places API 未啟用，請在 Google Cloud Console 開啟 Places API')
    except RuntimeError:
        raise
    except Exception as e:
        print(f"  [CID 查詢] 失敗: {e}")
    return ''


# === Google Maps Find Place API：依店名查詢正確地址 ===
def lookup_address_from_place_api(title, maps_api_key):
    """使用 Find Place from Text API 取得店家的正式中文地址。"""
    if not title or not maps_api_key:
        return ''
    params = urllib.parse.urlencode({
        'input':        title,
        'inputtype':    'textquery',
        'fields':       'formatted_address,name',
        'locationbias': 'rectangle:21.5,119.3|25.5,122.1',
        'language':     'zh-TW',
        'key':          maps_api_key,
    })
    url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('status') == 'OK' and data.get('candidates'):
                return data['candidates'][0].get('formatted_address', '')
    except Exception as e:
        print(f"  [Find Place] 查詢 '{title}' 失敗: {e}")
    return ''


# === 批次 AI 分類（餐飲類型、消費、座標、地址） ===
def classify_cuisine_and_details(items, home_address, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
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
                                "index":       {"type": "INTEGER"},
                                "types":       {"type": "STRING"},
                                "avg_spending":{"type": "INTEGER"},
                                "lat":         {"type": "NUMBER"},
                                "lng":         {"type": "NUMBER"},
                                "address":     {"type": "STRING"}
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

    fallback = [
        {'types': '其他', 'avg_spending': 0, 'lat': None, 'lng': None, 'address': items[i]['address']}
        for i in range(len(items))
    ]

    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                res  = json.loads(resp.read().decode('utf-8'))
                data = json.loads(res['candidates'][0]['content']['parts'][0]['text'])
                results_map = {r['index']: r for r in data.get('results', [])}
                return [
                    {
                        'types':        results_map[i]['types']           if i in results_map else '其他',
                        'avg_spending': results_map[i]['avg_spending']    if i in results_map else 0,
                        'lat':          results_map[i].get('lat')         if i in results_map else None,
                        'lng':          results_map[i].get('lng')         if i in results_map else None,
                        'address':      results_map[i].get('address', '') if i in results_map else ''
                    }
                    for i in range(len(items))
                ]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503):
                delay = _parse_retry_delay(e) if e.code == 429 else 30
                if attempt < MAX_RETRIES:
                    label = '超過速率限制' if e.code == 429 else f'服務暫時不可用 (HTTP {e.code})'
                    print(f"    [{e.code}] {label}，等待 {delay} 秒後重試（第 {attempt + 1}/{MAX_RETRIES} 次）...")
                    time.sleep(delay)
                    continue
                print(f"    [錯誤] 達到最大重試次數，跳過此批次。")
            else:
                print(f"    [錯誤] API 回傳 HTTP {e.code}，跳過此批次。")
            return fallback
        except Exception as e:
            print(f"    [錯誤] 呼叫 Gemini API 失敗: {e}")
            return fallback

    return fallback


def _parse_retry_delay(http_error):
    """從 429 回應中解析建議的等待秒數，預設 65 秒。"""
    try:
        body = json.loads(http_error.read().decode('utf-8'))
        for detail in body.get('error', {}).get('details', []):
            if detail.get('@type') == 'type.googleapis.com/google.rpc.RetryInfo':
                delay_str = detail.get('retryDelay', '60s')
                return int(delay_str.rstrip('s')) + 5
    except Exception:
        pass
    return 65


# === Haversine 距離計算 ===
def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        R    = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a    = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)
    except Exception:
        return None


# === Google Drive 上傳（需額外安裝套件） ===
def upload_to_gdrive(filepath, folder_id):
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("\n[跳過 Google Drive 上傳] 套件未安裝。")
        print("若要啟用，請執行：pip install google-api-python-client google-auth-oauthlib")
        return False

    SCOPES     = ['https://www.googleapis.com/auth/drive.file']
    CREDS_FILE = 'credentials.json'
    TOKEN_FILE = 'token.json'

    if not os.path.exists(CREDS_FILE):
        print(f"\n[跳過 Google Drive 上傳] 找不到 '{CREDS_FILE}'。")
        print("請參閱 README.md「Google Drive 自動上傳設定」段落。")
        return False

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    service  = build('drive', 'v3', credentials=creds)
    filename = os.path.basename(filepath)

    # 若同名檔案已存在則更新，否則新建
    query = f"name='{filename}' and trashed=false"
    if folder_id:
        query += f" and '{folder_id}' in parents"
    existing = service.files().list(q=query, fields='files(id,name)').execute().get('files', [])

    file_meta = {'name': filename}
    if folder_id:
        file_meta['parents'] = [folder_id]
    media = MediaFileUpload(filepath, mimetype='text/csv', resumable=True)

    try:
        print(f"  正在上傳 {filename}...")
        if existing:
            service.files().update(fileId=existing[0]['id'], media_body=media).execute()
            print(f"[成功] 已更新 Google Drive 上的檔案：{filename}")
        else:
            file = service.files().create(body=file_meta, media_body=media, fields='id').execute()
            print(f"[成功] 已上傳至 Google Drive（ID: {file.get('id')}）：{filename}")
        return True
    except KeyboardInterrupt:
        print("\n[中斷] Google Drive 上傳被取消。本地檔案已完整儲存。")
        return False
    except Exception as e:
        print(f"\n[失敗] Google Drive 上傳時發生錯誤: {e}")
        return False


# === 主程式 ===
def main():
    print("====== MyGoogleMap 清單整理與抽籤資料產生工具 ======")

    env = load_env()
    api_key = env.get('GEMINI_API_KEY', '')
    if not api_key:
        print("[警告] .env 中未設定 GEMINI_API_KEY，AI 分類功能將無法使用。")

    maps_api_key = env.get('MAPS_API_KEY', '') or api_key
    if maps_api_key:
        print("[資訊] 將嘗試使用 Google Maps Geocoding API 取得精確座標（MAPS_API_KEY 或 GEMINI_API_KEY）。")

    # 支援從 .env 覆寫模型（例如改用 gemini-2.0-flash 以獲得較寬鬆的免費配額）
    global MODEL_NAME
    MODEL_NAME = env.get('GEMINI_MODEL', DEFAULT_MODEL)
    print(f"使用模型：{MODEL_NAME}")

    # --- 掃描 input/ 資料夾 ---
    input_csvs = find_all_input_csvs(INPUT_FOLDER)
    if not input_csvs:
        print(f"\n[錯誤] 在 '{INPUT_FOLDER}/' 資料夾中找不到任何 CSV 檔案！")
        print(f"請將 Google Takeout 匯出的 CSV 清單放入 '{INPUT_FOLDER}/' 資料夾後再執行。")
        sys.exit(1)

    print(f"\n偵測到 {len(input_csvs)} 份輸入清單：")
    for fp, name, is_v in input_csvs:
        tag = "（已去過）" if is_v else "（未去過）"
        print(f"  - {name}.csv {tag}")

    # --- 住家地址 ---
    home_address = env.get('HOME_ADDRESS', '')
    if home_address:
        print(f"\n偵測到 .env 中的住家地址：{home_address}")

    home_lat, home_lng = None, None
    if not home_address:
        try:
            home_address = input(
                "\n請輸入住家地址以計算距離（直接按 Enter 跳過）: "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            home_address = ''

    if home_address and api_key:
        _home_cache_key      = f"__home_coords__{home_address}"
        _home_maps_cache_key = f"__maps_geo__{home_address}"
        _pre_cache = load_cache()

        # 優先從 Maps API 快取取得精確住家座標
        if _home_maps_cache_key in _pre_cache:
            home_lat = _pre_cache[_home_maps_cache_key]['lat']
            home_lng = _pre_cache[_home_maps_cache_key]['lng']
            print(f"\n住家座標從 Maps API 快取讀取：(緯度 {home_lat}, 經度 {home_lng})")
        elif maps_api_key:
            print(f"\n正在用 Google Maps Geocoding API 定位住家地址：{home_address} ...")
            home_lat, home_lng = geocode_with_maps_api(home_address, maps_api_key)
            if home_lat and home_lng:
                print(f"住家定位成功（Maps API）：(緯度 {home_lat}, 經度 {home_lng})")
                _pre_cache[_home_maps_cache_key] = {'lat': home_lat, 'lng': home_lng}
                save_cache(_pre_cache)
            else:
                # Maps API 失敗，退回舊快取或 Gemini
                if _home_cache_key in _pre_cache:
                    home_lat = _pre_cache[_home_cache_key].get('lat')
                    home_lng = _pre_cache[_home_cache_key].get('lng')
                    print(f"  Maps API 失敗，改用舊快取：(緯度 {home_lat}, 經度 {home_lng})")
                else:
                    home_lat, home_lng = geocode_address(home_address, api_key)
                    if home_lat and home_lng:
                        print(f"  改用 Gemini 估算：(緯度 {home_lat}, 經度 {home_lng})")
                        _pre_cache[_home_cache_key] = {'lat': home_lat, 'lng': home_lng}
                        save_cache(_pre_cache)
                    else:
                        print("無法定位住家地址，將跳過距離計算。")
        elif _home_cache_key in _pre_cache:
            home_lat = _pre_cache[_home_cache_key].get('lat')
            home_lng = _pre_cache[_home_cache_key].get('lng')
            print(f"\n住家座標從快取讀取：(緯度 {home_lat}, 經度 {home_lng})")
        else:
            print(f"\n正在定位住家地址：{home_address} ...")
            home_lat, home_lng = geocode_address(home_address, api_key)
            if home_lat and home_lng:
                print(f"住家定位成功：(緯度 {home_lat}, 經度 {home_lng})")
                _pre_cache[_home_cache_key] = {'lat': home_lat, 'lng': home_lng}
                save_cache(_pre_cache)
            else:
                print("無法定位住家地址，將跳過距離計算。")

    # --- 合併所有清單 ---
    merged_places = {}
    for filepath, list_name, is_visited in input_csvs:
        places = read_csv(filepath)
        print(f"\n讀取「{list_name}」：{len(places)} 筆")
        for p in places:
            key = p['url'] if p['url'] else f"{p['title']}_{p['address']}"
            if key in merged_places:
                # 若同一地點同時出現在回訪清單，優先標記為已去過
                if is_visited:
                    merged_places[key]['visited'] = '是'
            else:
                p['visited']     = '是' if is_visited else '否'
                p['source_list'] = list_name
                merged_places[key] = p

    total_places = list(merged_places.values())
    print(f"\n合併完成，共 {len(total_places)} 筆不重複地點。")
    if not total_places:
        print("沒有需要處理的資料。")
        sys.exit(0)

    # --- 使用 Place Details / Find Place API 預先填入缺少地址的店家 ---
    # 需要 MAPS_API_KEY（獨立的 Google Maps Platform key），且已啟用：
    #   - Places API（CID 精確查詢）
    #   - Geocoding API（住家座標定位）
    # 若只有 GEMINI_API_KEY 而無 MAPS_API_KEY，此段會靜默跳過，地址改由 Gemini AI 補齊。
    places_api_available = None   # None=未知, True=可用, False=不可用
    if maps_api_key:
        need_lookup = [p for p in total_places if not p.get('address')]
        if need_lookup:
            pre_cache = load_cache()
            print(f"\n有 {len(need_lookup)} 筆地點缺少地址，嘗試使用 Google Maps API 查詢...")
            filled = 0
            for p in need_lookup:
                if places_api_available is False:
                    break   # API 不可用，跳過剩餘，交給 Gemini 補

                addr = ''

                # 1. 優先：從 URL 內嵌的 CID 精確查詢（需 Places API）
                cid_hex = extract_cid_from_maps_url(p.get('url', ''))
                if cid_hex:
                    cid_ck = f"__cid_addr__{cid_hex}"
                    if cid_ck in pre_cache:
                        addr = pre_cache[cid_ck].get('address', '')
                    else:
                        try:
                            addr = lookup_address_from_cid(cid_hex, maps_api_key)
                            pre_cache[cid_ck] = {'address': addr}
                            if places_api_available is None:
                                places_api_available = True
                                print("  [Places API] 已啟用，使用 CID 精確查詢地址。")
                        except RuntimeError as e:
                            print(f"\n  [警告] {e}")
                            print("  → 後續地址將改由 Gemini AI 補齊（準確度較低，同名多店可能誤判）。")
                            print("  → 若需精確地址，請在 .env 設定獨立的 MAPS_API_KEY 並啟用 Places API。")
                            places_api_available = False
                            break

                # 2. 退回：以店名搜尋（需 Places API，同名多店可能誤判）
                if not addr and places_api_available is not False:
                    ck = f"__find_place__{p['title']}"
                    if ck in pre_cache:
                        addr = pre_cache[ck].get('address', '')
                    else:
                        addr = lookup_address_from_place_api(p['title'], maps_api_key)
                        pre_cache[ck] = {'address': addr}

                if addr:
                    p['address'] = addr
                    filled += 1

            save_cache(pre_cache)
            if places_api_available is not False:
                print(f"  Google Maps API 成功取得 {filled} / {len(need_lookup)} 筆地址。")
            else:
                print(f"  Places API 不可用，{len(need_lookup)} 筆地址將由 Gemini AI 補齊。")

    # --- AI 批次分析（含進度快取與斷點續跑） ---
    if api_key:
        cache      = load_cache()
        batch_size = 20
        total      = len(total_places)
        cached_cnt = sum(1 for p in total_places if cache_key(p) in cache)

        print(f"\n開始使用 Gemini 2.5 Flash 進行 AI 分析（共 {total} 筆）...")
        if cached_cnt:
            print(f"  快取命中 {cached_cnt} 筆，跳過已處理項目。")

        try:
            for i in range(0, total, batch_size):
                batch      = total_places[i:i + batch_size]
                to_process = [(idx, p) for idx, p in enumerate(batch) if cache_key(p) not in cache]

                if to_process:
                    end = min(i + batch_size, total)
                    print(f"  正在處理第 {i+1}～{end} 筆（本批需呼叫 API {len(to_process)} 項）...")
                    sub_items  = [p for _, p in to_process]
                    sub_result = classify_cuisine_and_details(sub_items, home_address, api_key)

                    for (orig_idx, p), det in zip(to_process, sub_result):
                        cache[cache_key(p)] = det
                        batch[orig_idx].update({
                            'cuisine_type': det['types'],
                            'avg_spending': det['avg_spending'],
                            'lat':          det['lat'],
                            'lng':          det['lng'],
                        })
                        if not batch[orig_idx]['address'] and det.get('address'):
                            batch[orig_idx]['address'] = det['address']

                    save_cache(cache)

                    # 批次間主動控速（非最後一批才等）
                    if i + batch_size < total:
                        time.sleep(BATCH_DELAY)

                # 從快取補齊本批已命中的項目
                for idx, p in enumerate(batch):
                    ck = cache_key(p)
                    if ck in cache:
                        det = cache[ck]
                        batch[idx].setdefault('cuisine_type', det['types'])
                        batch[idx].setdefault('avg_spending', det['avg_spending'])
                        batch[idx].setdefault('lat',          det['lat'])
                        batch[idx].setdefault('lng',          det['lng'])
                        if not batch[idx]['address'] and det.get('address'):
                            batch[idx]['address'] = det['address']

                # 計算距離（優先用 Maps API 取得精確座標）
                for p in batch:
                    addr = p.get('address', '')
                    if maps_api_key and addr:
                        geo_cache_key = f"__maps_geo__{addr}"
                        if geo_cache_key in cache:
                            p['lat'] = cache[geo_cache_key]['lat']
                            p['lng'] = cache[geo_cache_key]['lng']
                        else:
                            mlat, mlng = geocode_with_maps_api(addr, maps_api_key)
                            if mlat is not None:
                                p['lat'], p['lng'] = mlat, mlng
                                cache[geo_cache_key] = {'lat': mlat, 'lng': mlng}
                    if home_lat and home_lng:
                        p['distance_km'] = haversine_distance(home_lat, home_lng, p.get('lat'), p.get('lng'))
                    else:
                        p.setdefault('distance_km', None)

        except KeyboardInterrupt:
            print("\n\n[中斷] 使用者中止執行，已儲存目前進度至快取。")
            print("重新執行腳本時將從中斷點繼續。")
            save_cache(cache)
            # 確保已處理的資料仍輸出至檔案
            for p in total_places:
                p.setdefault('cuisine_type', '其他')
                p.setdefault('avg_spending', 0)
                p.setdefault('lat', None)
                p.setdefault('lng', None)
                p.setdefault('distance_km', None)

    else:
        print("\n[跳過] 未設定 GEMINI_API_KEY，跳過 AI 分析步驟。")
        for p in total_places:
            p.setdefault('cuisine_type', '其他')
            p.setdefault('avg_spending', 0)
            p.setdefault('lat', None)
            p.setdefault('lng', None)
            p.setdefault('distance_km', None)

    # --- 輸出 CSV ---
    try:
        with open(OUTPUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['店名', '地址', '網址', '餐飲類型', '來源清單', '是否曾去過', '距離住家(公里)', '人均消費預估(元)', '備註'])
            for p in total_places:
                writer.writerow([
                    p['title'],
                    p['address'],
                    p['url'],
                    p.get('cuisine_type', '其他'),
                    p.get('source_list', ''),
                    p['visited'],
                    p['distance_km'] if p.get('distance_km') is not None else '未知',
                    p.get('avg_spending', 0) if p.get('avg_spending', 0) > 0 else '未知',
                    p['note']
                ])
        print(f"\n[成功] CSV 整理完成：{OUTPUT_CSV}")
    except Exception as e:
        print(f"\n[錯誤] 寫入 CSV 失敗: {e}")

    # --- 輸出 stores_data.js ---
    try:
        js_data = [
            {
                'title':        p['title'],
                'address':      p['address'],
                'url':          p['url'],
                'cuisine_type': p.get('cuisine_type', '其他'),
                'source_list':  p.get('source_list', ''),
                'visited':      p['visited'],
                'distance_km':  p.get('distance_km'),
                'avg_spending': p.get('avg_spending', 0),
                'note':         p['note']
            }
            for p in total_places
        ]
        with open(OUTPUT_JS, 'w', encoding='utf-8') as f:
            f.write("// 自動產生的店家資料檔，請勿手動修改。\n")
            f.write("window.STORES_DATA = ")
            json.dump(js_data, f, ensure_ascii=False, indent=2)
            f.write(";\n")
        print(f"[成功] 抽籤資料庫已儲存：{OUTPUT_JS}")
    except Exception as e:
        print(f"\n[錯誤] 寫入 JS 失敗: {e}")

    # --- Google Drive 上傳 ---
    folder_id = env.get('GDRIVE_FOLDER_ID', '')
    if folder_id or os.path.exists('credentials.json'):
        print("\n嘗試上傳至 Google Drive...")
        upload_to_gdrive(OUTPUT_CSV, folder_id)
    else:
        print("\n[提示] 若要自動上傳 CSV 至 Google Drive，請參閱 README.md 進行設定。")

    print("\n現在可以開啟 'lottery.html' 進行篩選抽籤！")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[中斷] 程式已結束。")
