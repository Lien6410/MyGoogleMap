import os
import csv
import sys
import json
import math
import urllib.request

# 設定 Gemini API Key 與模型
API_KEY = "AIzaSyD2U8zFDMD6JBp7Bk6rxP7VRcJRsvabeX8"
MODEL_NAME = "gemini-2.5-flash"

# 您可以在此處填寫預設的住家地址（例如：台北市信義區信義路五段7號）
# 填寫後執行腳本時就不會每次都詢問。若留空，腳本會在啟動時詢問您。
DEFAULT_HOME_ADDRESS = ""

def find_csv_file(keywords):
    """
    尋找檔名包含關鍵字的 CSV 檔案
    """
    files = [f for f in os.listdir('.') if f.endswith('.csv')]
    for f in files:
        f_lower = f.lower()
        if any(kw.lower() in f_lower for kw in keywords):
            return f
    return None

def detect_headers(header_row):
    """
    自動偵測 CSV 欄位索引，相容中英文與不同匯出欄位名稱
    """
    mapping = {'title': None, 'note': None, 'url': None, 'address': None}
    for i, col in enumerate(header_row):
        col_clean = col.strip().lower()
        if col_clean in ['title', '標題', '名稱', 'name']:
            mapping['title'] = i
        elif col_clean in ['note', '備註', '說明', '備忘錄', 'notes']:
            mapping['note'] = i
        elif col_clean in ['url', '網址', '連結', 'link']:
            mapping['url'] = i
        elif col_clean in ['address', '地址']:
            mapping['address'] = i
            
    if mapping['title'] is None:
        mapping['title'] = 0
    if mapping['address'] is None and len(header_row) > 1:
        for i, col in enumerate(header_row):
            if '地' in col or 'add' in col.lower():
                mapping['address'] = i
                break
    return mapping

def read_csv(filename):
    """
    讀取 CSV 檔案並解析出店家資訊
    """
    places = []
    try:
        with open(filename, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                return []
            
            mapping = detect_headers(headers)
            
            for row in reader:
                if not row or len(row) <= max(filter(lambda x: x is not None, mapping.values())):
                    continue
                
                title = row[mapping['title']].strip() if mapping['title'] is not None else ""
                note = row[mapping['note']].strip() if mapping['note'] is not None else ""
                url = row[mapping['url']].strip() if mapping['url'] is not None else ""
                address = row[mapping['address']].strip() if mapping['address'] is not None else ""
                
                if title:
                    places.append({
                        'title': title,
                        'address': address,
                        'url': url,
                        'note': note
                    })
    except Exception as e:
        print(f"讀取檔案 {filename} 時出錯: {e}")
    return places

def geocode_address(address):
    """
    使用 Gemini API 解析單一地址/地標的經緯度座標（住家用）
    """
    if not address:
        return None, None
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={API_KEY}"
    prompt = f"請提供台灣地址或著名地標的預估經緯度：'{address}'。\n" \
             "請嚴格以 JSON 格式回傳，不可有任何額外說明文字：\n" \
             "{\"lat\": 25.033, \"lng\": 121.564}"
             
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "lat": { "type": "NUMBER" },
                    "lng": { "type": "NUMBER" }
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
    
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            res = json.loads(response.read().decode('utf-8'))
            text_response = res['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(text_response)
            return data.get("lat"), data.get("lng")
    except Exception as e:
        print(f"解析住家地址座標失敗: {e}")
        return None, None

def classify_cuisine_and_details(items):
    """
    使用 Gemini 2.5 Flash 批次判斷餐飲類型、預估人均消費，以及解析店家的經緯度座標
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={API_KEY}"
    
    prompt = """
分析以下店家的名稱和地址，判斷它們的「餐飲類型」、「預估人均消費（台幣）」，以及「預估經緯度座標」。

餐飲類型選項（可複選，符合多個時請以半角逗號隔開，例如：中式,日式）：
- 中式
- 日式
- 義式
- 美式
- 韓式
- 東南亞式
- 其他

說明：
1. 餐飲類型：請根據店名與地址判斷。若非餐飲場所（例如：景點、飯店、公園、商店等），請直接標記為「其他」。
2. 人均消費：請預估該店家的台幣人均消費金額（整數，例如平價小吃預估 80 或 150，中價位餐廳 350 或 500，高檔餐廳 1200，若為非餐飲店或免費景點，請直接標記為 0）。
3. 經緯度座標：請預估該店家最準確的 GPS 緯度 (lat) 與經度 (lng) 座標（用於計算距離）。
4. 請依照提供的 index 對應填寫。

請嚴格以下列 JSON 格式回傳，不要包含任何 Markdown 標記或說明文字：
{
  "results": [
    {"index": 0, "types": "中式", "avg_spending": 150, "lat": 25.033, "lng": 121.564},
    {"index": 1, "types": "日式,東南亞式", "avg_spending": 680, "lat": 25.021, "lng": 121.531}
  ]
}

待處理的店家列表：
"""
    for idx, item in enumerate(items):
        prompt += f'Index {idx}: 店名="{item["title"]}", 地址="{item["address"]}"\n'

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
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
                                "index": { "type": "INTEGER" },
                                "types": { "type": "STRING" },
                                "avg_spending": { "type": "INTEGER" },
                                "lat": { "type": "NUMBER" },
                                "lng": { "type": "NUMBER" }
                            },
                            "required": ["index", "types", "avg_spending", "lat", "lng"]
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
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res = json.loads(response.read().decode('utf-8'))
            text_response = res['candidates'][0]['content']['parts'][0]['text']
            data = json.loads(text_response)
            
            # 對應 index
            results_map = {}
            for res_item in data.get("results", []):
                idx = res_item.get("index")
                results_map[idx] = {
                    'types': res_item.get("types", "其他"),
                    'avg_spending': res_item.get("avg_spending", 0),
                    'lat': res_item.get("lat"),
                    'lng': res_item.get("lng")
                }
            
            final_results = []
            for idx in range(len(items)):
                final_results.append(results_map.get(idx, {
                    'types': "其他",
                    'avg_spending': 0,
                    'lat': None,
                    'lng': None
                }))
            return final_results
            
    except Exception as e:
        print(f"呼叫 Gemini API 失敗: {e}")
        if hasattr(e, 'read'):
            try:
                print("API 錯誤細節:", e.read().decode('utf-8'))
            except:
                pass
        return [{
            'types': "其他",
            'avg_spending': 0,
            'lat': None,
            'lng': None
        }] * len(items)

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    計算半球面大圓距離（公里數）
    """
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        R = 6371.0 # 地球半徑
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(R * c, 2)
    except:
        return None

def main():
    print("====== Google Maps Saved Lists 整理與抽籤資料產生工具 ======")
    
    # 偵測 CSV 檔案
    revisit_file = find_csv_file(['回訪', 'revisit'])
    want_file = find_csv_file(['想去', 'want'])
    
    if not revisit_file and not want_file:
        print("\n[錯誤] 在目前資料夾中找不到 '回訪' 或 '想去的地點' 的 CSV 檔案！")
        print("請先將 Google Takeout 匯出的 CSV 檔案移至此資料夾。")
        sys.exit(1)
        
    # 住家地址處理
    home_address = DEFAULT_HOME_ADDRESS
    home_lat, home_lng = None, None
    if not home_address:
        try:
            home_address = input("\n請輸入您的住家地址（例如：台北市大安區新生南路三段1號）以計算距離：\n（直接按 Enter 將跳過距離與定位計算）: ").strip()
        except (KeyboardInterrupt, EOFError):
            home_address = ""
            
    if home_address:
        print(f"\n正在定位住家地址：{home_address} ...")
        home_lat, home_lng = geocode_address(home_address)
        if home_lat and home_lng:
            print(f"住家定位成功：(緯度 {home_lat}, 經度 {home_lng})")
        else:
            print("無法成功定位您的住家地址，將跳過距離計算。")
            
    merged_places = {}
    
    # 1. 讀取回訪清單
    if revisit_file:
        print(f"\n偵測到回訪清單: {revisit_file}")
        revisit_places = read_csv(revisit_file)
        print(f"讀取到 {len(revisit_places)} 筆資料。")
        for p in revisit_places:
            key = p['url'] if p['url'] else f"{p['title']}_{p['address']}"
            p['visited'] = "是"
            merged_places[key] = p
            
    # 2. 讀取想去地點清單
    if want_file:
        print(f"\n偵測到想去地點清單: {want_file}")
        want_places = read_csv(want_file)
        print(f"讀取到 {len(want_places)} 筆資料。")
        for p in want_places:
            key = p['url'] if p['url'] else f"{p['title']}_{p['address']}"
            if key in merged_places:
                pass
            else:
                p['visited'] = "否"
                merged_places[key] = p
                
    total_places = list(merged_places.values())
    total_count = len(total_places)
    print(f"\n合併完成，共 {total_count} 筆不重複店家。")
    
    if total_count == 0:
        print("沒有需要處理的店家資料。")
        sys.exit(0)
        
    # 3. 批次使用 Gemini 判斷餐飲類型、預估消費、取得店家座標
    print("\n開始進行店家詳細資訊估算與定位 (使用 Gemini 2.5 Flash)...")
    batch_size = 20
    
    for i in range(0, total_count, batch_size):
        batch = total_places[i:i+batch_size]
        print(f"正在處理第 {i+1} 至 {min(i+batch_size, total_count)} 筆...")
        details = classify_cuisine_and_details(batch)
        
        for idx, det in enumerate(details):
            # 填入餐飲類型與消費
            batch[idx]['cuisine_type'] = det['types']
            batch[idx]['avg_spending'] = det['avg_spending']
            batch[idx]['lat'] = det['lat']
            batch[idx]['lng'] = det['lng']
            
            # 計算距離
            if home_lat and home_lng and det['lat'] and det['lng']:
                dist = haversine_distance(home_lat, home_lng, det['lat'], det['lng'])
                batch[idx]['distance_km'] = dist
            else:
                batch[idx]['distance_km'] = None
                
    # 4. 輸出至 CSV 檔案 (採用 UTF-8 BOM 避免 Excel 亂碼)
    output_csv = "MyGoogleMap_Stores.csv"
    try:
        with open(output_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['店名', '地址', '網址', '餐飲類型', '是否曾去過', '距離住家(公里)', '人均消費預估(元)', '備註'])
            for p in total_places:
                writer.writerow([
                    p['title'],
                    p['address'],
                    p['url'],
                    p.get('cuisine_type', '其他'),
                    p['visited'],
                    p['distance_km'] if p.get('distance_km') is not None else "未知",
                    p.get('avg_spending', 0) if p.get('avg_spending', 0) > 0 else "未知",
                    p['note']
                ])
        print(f"\n[成功] CSV 整理完成！已儲存至：{output_csv}")
    except Exception as e:
        print(f"\n[錯誤] 寫入 CSV 檔案失敗: {e}")
        
    # 5. 輸出至 stores_data.js 用於抽籤網頁
    output_js = "stores_data.js"
    try:
        # 將資料庫包裝成 Web lottery 能載入的 JS array
        js_data = []
        for p in total_places:
            js_data.append({
                'title': p['title'],
                'address': p['address'],
                'url': p['url'],
                'cuisine_type': p.get('cuisine_type', '其他'),
                'visited': p['visited'],
                'distance_km': p.get('distance_km'),
                'avg_spending': p.get('avg_spending', 0),
                'note': p['note']
            })
            
        with open(output_js, 'w', encoding='utf-8') as f:
            f.write("// 自動產生的店家資料檔，請勿手動修改。\n")
            f.write("window.STORES_DATA = ")
            json.dump(js_data, f, ensure_ascii=False, indent=2)
            f.write(";\n")
        print(f"[成功] 抽籤資料庫已儲存至：{output_js}")
        print("\n現在您可以開啟 'lottery.html' 進行篩選抽籤了！")
    except Exception as e:
        print(f"\n[錯誤] 寫入 JS 檔案失敗: {e}")

if __name__ == '__main__':
    main()
