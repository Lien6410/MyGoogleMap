// Google Apps Script - 可直接貼入 Google 試算表內執行 (擴充功能 -> Apps Script)

// API key 改由「指令碼屬性」安全讀取，請勿硬編碼於程式碼（會隨 git/GitHub Pages 外洩）。
// 設定方式：Apps Script 編輯器 → 專案設定(齒輪) → 指令碼屬性 → 新增 GEMINI_API_KEY
const API_KEY = PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY');
const MODEL_NAME = "gemini-2.5-flash";

function main() {
  var ui = SpreadsheetApp.getUi();
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  sheet.clear();
  
  // 設定表頭
  sheet.appendRow(['店名', '地址', '網址', '餐飲類型', '是否曾去過', '距離住家(公里)', '人均消費預估(元)', '備註']);
  
  // 1. 詢問住家地址以計算距離
  var homeAddress = "";
  var homeLat = null, homeLng = null;
  
  var responsePrompt = ui.prompt("設定住家距離", "請輸入您的住家地址（例如：台北市大安區新生南路三段1號）以計算距離：\n（直接按確定或留空將跳過距離計算）", ui.ButtonSet.OK_CANCEL);
  
  if (responsePrompt.getSelectedButton() == ui.Button.OK) {
    homeAddress = responsePrompt.getResponseText().trim();
    if (homeAddress) {
      try {
        var geocode = Maps.newGeocoder().geocode(homeAddress);
        if (geocode.status == "OK" && geocode.results && geocode.results.length > 0) {
          var loc = geocode.results[0].geometry.location;
          homeLat = loc.lat;
          homeLng = loc.lng;
          Logger.log("住家座標定位成功: lat=" + homeLat + ", lng=" + homeLng);
        } else {
          ui.alert("定位住家地址失敗，將跳過距離計算。");
        }
      } catch (err) {
        Logger.log("住家定位出錯: " + err.toString());
      }
    }
  }

  // 2. 尋找 MyGoogleMap 資料夾
  var folders = DriveApp.getFoldersByName("MyGoogleMap");
  if (!folders.hasNext()) {
    ui.alert("在您的雲端硬碟根目錄找不到名為 'MyGoogleMap' 的資料夾。請建立該資料夾並將 CSV 檔案放進去。");
    return;
  }
  
  var folder = folders.next();
  var files = folder.getFiles();
  
  var revisitFile = null;
  var wantFile = null;
  
  while (files.hasNext()) {
    var file = files.next();
    var name = file.getName().toLowerCase();
    if (name.endsWith(".csv")) {
      if (name.includes("回訪") || name.includes("revisit")) {
        revisitFile = file;
      } else if (name.includes("想去") || name.includes("want")) {
        wantFile = file;
      }
    }
  }
  
  if (!revisitFile && !wantFile) {
    ui.alert("在 'MyGoogleMap' 資料夾中找不到包含 '回訪' 或 '想去' 的 CSV 檔案。");
    return;
  }
  
  var mergedPlaces = {};
  
  // 讀取回訪清單
  if (revisitFile) {
    var revisitData = parseCsvFile(revisitFile);
    revisitData.forEach(function(p) {
      var key = p.url ? p.url : p.title + "_" + p.address;
      p.visited = "是";
      mergedPlaces[key] = p;
    });
  }
  
  // 讀取想去地點清單
  if (wantFile) {
    var wantData = parseCsvFile(wantFile);
    wantData.forEach(function(p) {
      var key = p.url ? p.url : p.title + "_" + p.address;
      if (!mergedPlaces[key]) {
        p.visited = "否";
        mergedPlaces[key] = p;
      }
    });
  }
  
  var places = Object.values(mergedPlaces);
  if (places.length === 0) {
    ui.alert("未讀取到任何店家資料。");
    return;
  }
  
  // 3. 批次呼叫 Gemini API 進行詳細資訊與座標估算
  var batchSize = 20;
  for (var i = 0; i < places.length; i += batchSize) {
    var batch = places.slice(i, i + batchSize);
    var details = classifyBatchDetails(batch, homeAddress);
    
    for (var j = 0; j < batch.length; j++) {
      var det = details[j] || { types: "其他", avg_spending: 0, lat: null, lng: null, address: "" };
      batch[j].cuisineType = det.types;
      batch[j].avgSpending = det.avg_spending;
      
      if (!batch[j].address && det.address) {
        batch[j].address = det.address;
      }
      
      // 計算距離
      if (homeLat && homeLng && det.lat && det.lng) {
        batch[j].distanceKm = haversineDistance(homeLat, homeLng, det.lat, det.lng);
      } else {
        batch[j].distanceKm = null;
      }
    }
  }
  
  // 4. 寫入試算表
  places.forEach(function(p) {
    sheet.appendRow([
      p.title, 
      p.address, 
      p.url, 
      p.cuisineType, 
      p.visited, 
      p.distanceKm !== null ? p.distanceKm : "未知", 
      p.avgSpending > 0 ? p.avgSpending : "未知", 
      p.note
    ]);
  });
  
  ui.alert("店家清單整理完成！已新增 " + places.length + " 筆店家到此試算表中。");
}

function parseCsvFile(file) {
  var csvContent = file.getAs("text/plain").getDataAsString("UTF-8");
  var csvData = Utilities.parseCsv(csvContent);
  if (csvData.length <= 1) return [];
  
  var headers = csvData[0];
  var titleIdx = 0;
  var addressIdx = -1;
  var urlIdx = -1;
  var noteIdx = -1;
  
  for (var i = 0; i < headers.length; i++) {
    var h = headers[i].trim().toLowerCase();
    if (h === "title" || h === "標題" || h === "名稱" || h === "name") titleIdx = i;
    else if (h === "address" || h === "地址") addressIdx = i;
    else if (h === "url" || h === "網址" || h === "連結" || h === "link") urlIdx = i;
    else if (h === "note" || h === "備註" || h === "說明" || h === "notes") noteIdx = i;
  }
  
  var places = [];
  for (var r = 1; r < csvData.length; r++) {
    var row = csvData[r];
    if (row.length === 0 || !row[titleIdx]) continue;
    
    places.push({
      title: row[titleIdx] ? row[titleIdx].trim() : "",
      address: addressIdx !== -1 && row[addressIdx] ? row[addressIdx].trim() : "",
      url: urlIdx !== -1 && row[urlIdx] ? row[urlIdx].trim() : "",
      note: noteIdx !== -1 && row[noteIdx] ? row[noteIdx].trim() : ""
    });
  }
  return places;
}

function classifyBatchDetails(items, homeAddress) {
  var url = "https://generativelanguage.googleapis.com/v1beta/models/" + MODEL_NAME + ":generateContent?key=" + API_KEY;
  
  var prompt = "分析以下店家的名稱和輸入地址（輸入地址若為空，請由店名幫忙補足預估的詳細中文地址）。\n" +
               "請為每一筆店家判斷「餐飲類型」、「預估人均消費（台幣）」、「預估經緯度座標」以及「預估中文詳細地址」。\n";
               
  if (homeAddress) {
    prompt += "\n提示：這些店家多數位於「" + homeAddress + "」附近，請以此作為參考縣市來估算店家地址（例如：若您知道該店名，且該店在新竹市有分店，請優先定位於新竹市）。\n";
  }
  
  prompt += "\n餐飲類型選項（可複選，符合多個時請以半角逗號隔開，例如：中式,日式）：\n" +
            "- 中式\n" +
            "- 日式\n" +
            "- 義式\n" +
            "- 美式\n" +
            "- 韓式\n" +
            "- 東南亞式\n" +
            "- 其他\n\n" +
            "說明：\n" +
            "1. 餐飲類型：請根據店名與地址判斷。若非餐飲場所（例如：景點、飯店、公園、商店等），請直接標記為「其他」。\n" +
            "2. 人均消費：請預估該店家的台幣人均消費金額（整數，例如平價小吃預估 80 或 150，中價位餐廳 350 或 500，高檔餐廳 1200，若為非餐飲店或免費景點，請直接標記為 0）。\n" +
            "3. 經緯度座標：請預估該店家最準確的 GPS 緯度 (lat) 與經度 (lng) 座標（用於計算距離）。\n" +
            "4. 詳細地址：請估算寫出該店家的中文詳細地址（例如：'新竹市東區中央路229號'）。如果原本的地址已經不為空，請儘量使用它；若原本地址為空，請根據店名在資料庫中尋找並補齊詳細地址。若完全無法得知，請寫「未知地址」。\n" +
            "5. 請依照提供的 index 對應填寫。\n\n" +
            "請嚴格以下列 JSON 格式回傳，不要包含任何 Markdown 標記或說明文字：\n" +
            "{\n" +
            "  \"results\": [\n" +
            "    {\"index\": 0, \"types\": \"中式\", \"avg_spending\": 150, \"lat\": 25.033, \"lng\": 121.564, \"address\": \"台北市大安區信義路二段194號\"},\n" +
            "    {\"index\": 1, \"types\": \"日式,東南亞式\", \"avg_spending\": 680, \"lat\": 25.021, \"lng\": 121.531, \"address\": \"新竹市東區中央路229號\"}\n" +
            "  ]\n" +
            "}\n\n" +
            "待處理的店家列表：\n";
               
  for (var i = 0; i < items.length; i++) {
    prompt += "Index " + i + ": 店名=\"" + items[i].title + "\", 地址=\"" + items[i].address + "\"\n";
  }
  
  var payload = {
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
  };
  
  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };
  
  try {
    var response = UrlFetchApp.fetch(url, options);
    var resText = response.getContentText();
    var resJson = JSON.parse(resText);
    var resultText = resJson.candidates[0].content.parts[0].text;
    var data = JSON.parse(resultText);
    
    var resultsMap = {};
    data.results.forEach(function(item) {
      resultsMap[item.index] = {
        types: item.types,
        avg_spending: item.avg_spending,
        lat: item.lat,
        lng: item.lng
      };
    });
    
    var finalResults = [];
    for (var i = 0; i < items.length; i++) {
      finalResults.push(resultsMap[i] || { types: "其他", avg_spending: 0, lat: null, lng: null });
    }
    return finalResults;
  } catch (e) {
    Logger.log("API Error: " + e.toString());
    var fallback = [];
    for (var i = 0; i < items.length; i++) {
      fallback.push({ types: "其他", avg_spending: 0, lat: null, lng: null });
    }
    return fallback;
  }
}

function haversineDistance(lat1, lon1, lat2, lon2) {
  if (lat1 === null || lon1 === null || lat2 === null || lon2 === null) return null;
  try {
    var R = 6371.0; // 地球半徑 (公里)
    var toRad = function(degree) { return degree * Math.PI / 180; };
    var dlat = toRad(lat2 - lat1);
    var dlon = toRad(lon2 - lon1);
    var a = Math.sin(dlat / 2) * Math.sin(dlat / 2) +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
            Math.sin(dlon / 2) * Math.sin(dlon / 2);
    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    var dist = R * c;
    return Math.round(dist * 100) / 100; // 四捨五入到小數第二位
  } catch (e) {
    return null;
  }
}
