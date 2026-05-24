# Google Drive 自動上傳設定指南

完成此設定後，每次執行 `python export_to_sheets.py`，整理完成的 `MyGoogleMap_Stores.csv` 將自動上傳至你的 Google Drive 指定資料夾。若同名檔案已存在則自動覆蓋更新，無需手動操作。

---

## 前置需求

- 擁有一個 Google 帳號
- 已安裝 Python 3.7 以上版本
- 能夠開啟瀏覽器（首次授權時需要）

---

## 步驟一：建立 Google Cloud 專案並啟用 Drive API

### 1-1 開啟 Google Cloud Console

前往 [https://console.cloud.google.com/](https://console.cloud.google.com/) 並登入你的 Google 帳號。

### 1-2 建立新專案

1. 點擊頁面左上角的**專案下拉選單**（預設顯示「選取專案」或現有專案名稱）。
2. 在彈出視窗中點擊右上角的「**新增專案**」。
3. 輸入專案名稱，例如 `MyGoogleMap`。
4. 點擊「**建立**」，等待幾秒鐘讓系統建立專案。
5. 確認左上角的專案選單已切換至剛建立的專案。

### 1-3 啟用 Google Drive API

1. 在頂部搜尋列輸入 `Google Drive API`，點擊搜尋結果中的「**Google Drive API**」。
2. 點擊頁面中央的「**啟用**」藍色按鈕。
3. 等待幾秒鐘，頁面跳轉至 API 管理頁面即表示啟用成功。

---

## 步驟二：建立 OAuth 2.0 憑證

### 2-1 建立品牌（OAuth 同意畫面）

> Google Cloud Console 在 2025 年底更新了 UI，原本的「API 和服務 > OAuth 同意畫面」現已整合至「**Google Auth Platform**」，並改稱為「建立品牌」。以下說明對應新版介面。

1. 在左側選單點擊「**Google Auth Platform**」（或搜尋列輸入 `Google Auth Platform`）。
2. 點擊「**開始使用**」或「**建立品牌**」。
3. 填寫必要欄位：
   - **應用程式名稱**：填入不含「Google」字樣的名稱，例如 `地圖清單整理工具` 或 `MapLottery`。

     > ⚠️ **重要**：Google 不允許名稱包含 `Google`、`Gmail`、`YouTube` 等品牌字眼，否則會出現「應用程式名稱不符合 Google 規定」錯誤。

   - **使用者支援電子郵件**：選擇你的 Gmail 地址
   - **開發人員聯絡資訊**：填入你的 Gmail 地址
4. 點擊「**建立**」完成品牌設定，頁面會跳至「**OAuth 總覽**」。

### 2-2 新增測試使用者

1. 在左側選單點擊「**目標對象**」。
2. 找到「**測試使用者**」區塊，點擊「**新增使用者**」。
3. 輸入你的 Gmail 地址，點擊「**儲存**」。

   > 這步驟不可略過。應用程式處於測試模式時，只有加入清單的帳號才能授權。若略過，後續授權時會出現「**存取遭拒 (Error 403)**」。

### 2-3 確認資料存取權（可跳過）

1. 在左側選單點擊「**資料存取權**」。
2. **不需要手動新增任何範圍**，直接跳過此頁面。腳本執行時會自動請求所需的 `drive.file` 權限。

### 2-4 建立 OAuth 用戶端 ID

1. 在左側選單點擊「**用戶端**」，或在「OAuth 總覽」頁面點擊右側的「**建立 OAuth 用戶端**」按鈕。
2. 應用程式類型選擇「**桌面應用程式**」。
3. 名稱填入 `MyGoogleMap Desktop`（或任意名稱）。
4. 點擊「**建立**」。
5. 彈出視窗顯示已建立用戶端，點擊「**下載 JSON**」。

### 2-5 放置憑證檔案

1. 將下載的 JSON 檔案**重新命名**為 `credentials.json`。
2. 將 `credentials.json` 移動至此專案的**根目錄**（與 `export_to_sheets.py` 同一層）。

完成後目錄結構如下：

```
MyGoogleMap/
├── credentials.json    ← 剛才放入的憑證檔案
├── export_to_sheets.py
├── lottery.html
├── .env
└── ...
```

> **安全提醒**：`credentials.json` 包含私密金鑰，請勿上傳至公開的 Git 倉庫。專案的 `.gitignore` 已包含此檔案。

---

## 步驟三：安裝上傳套件

在終端機（命令提示字元 / PowerShell）執行：

```bash
pip install google-api-python-client google-auth-oauthlib
```

安裝完成後可確認版本：

```bash
pip show google-api-python-client google-auth-oauthlib
```

---

## 步驟四：取得 Google Drive 資料夾 ID

1. 開啟 [Google Drive](https://drive.google.com/)，建立或開啟你要上傳的目標資料夾（例如 `MyGoogleMap`）。
2. 進入該資料夾後，查看瀏覽器**網址列**：

   ```
   https://drive.google.com/drive/folders/1aBcDeFgHiJkLmNoPqRsTuVwXyZ12345
   ```

3. 複製 `/folders/` 後方的那一串 ID，例如：`1aBcDeFgHiJkLmNoPqRsTuVwXyZ12345`

### 填入 .env

開啟專案根目錄的 `.env` 檔案，加入或修改以下這行：

```env
GDRIVE_FOLDER_ID="1aBcDeFgHiJkLmNoPqRsTuVwXyZ12345"
```

完整的 `.env` 範例：

```env
HOME_ADDRESS="新竹市北區光華一街18號"
GEMINI_API_KEY="你的_GEMINI_API_KEY"
GDRIVE_FOLDER_ID="1aBcDeFgHiJkLmNoPqRsTuVwXyZ12345"
```

---

## 步驟五：首次執行授權

執行主腳本：

```bash
python export_to_sheets.py
```

腳本在準備上傳時會自動：

1. **開啟系統預設瀏覽器**，顯示 Google 帳號登入與授權頁面。
2. 選擇（或登入）你在步驟 2-1 加入的 Google 帳號。
3. 若出現「**Google 尚未驗證此應用程式**」警告頁面：
   - 點擊「**進階**」（或 Advanced）。
   - 點擊「**前往 MyGoogleMap（不安全）**」。

   > 這是因為應用程式處於測試模式，不代表有任何安全疑慮，只是 Google 尚未審核此自建應用程式。

4. 確認授權存取 Google Drive 的權限，點擊「**允許**」。
5. 瀏覽器顯示「**授權成功，可以關閉此視窗**」即完成。

授權完成後，腳本會在專案根目錄自動產生 `token.json`，儲存你的授權 Token。**往後執行不再需要重複授權**，全程自動完成。

---

## 後續使用

完成以上設定後，每次執行 `python export_to_sheets.py`，腳本結尾會自動：

1. 偵測 `credentials.json` 與 `token.json` 是否存在。
2. 若 Token 尚未過期，直接上傳；若過期，自動靜默刷新。
3. 檢查 Google Drive 目標資料夾內是否已有同名檔案：
   - **有**：覆蓋更新既有檔案（保留原始連結不變）。
   - **無**：建立新檔案。
4. 輸出上傳成功訊息與檔案 ID。

---

## 常見問題

**Q：建立品牌（OAuth 同意畫面）時出現「應用程式名稱不符合 Google 規定」**

應用程式名稱中包含了 Google 保留的品牌字眼（如 `Google`、`Gmail`、`YouTube`）。回到上一步，將名稱改為不含這些字眼的名稱，例如 `地圖清單整理工具` 或 `MapLottery`，再重新點擊「建立」即可。

---

**Q：出現 `ModuleNotFoundError: No module named 'google'`**

代表套件尚未安裝，執行：
```bash
pip install google-api-python-client google-auth-oauthlib
```

---

**Q：授權頁面出現「錯誤 400：redirect_uri_mismatch」**

憑證設定有誤。請回到 Google Cloud Console，確認應用程式類型選擇的是「**桌面應用程式**」而非「Web 應用程式」。若選錯，刪除現有憑證重新建立即可。

---

**Q：授權後出現「此應用程式未經 Google 驗證」**

這是正常現象。自建的 OAuth 應用程式在測試模式下都會出現此警告。點擊「**進階**」>「**前往 MyGoogleMap（不安全）**」繼續即可。若要移除此警告，需向 Google 提交應用程式審核，但個人用途沒有必要。

---

**Q：上傳失敗，出現 `HttpError 403: The user does not have sufficient permissions`**

可能原因：
- `GDRIVE_FOLDER_ID` 填寫錯誤，請重新複製網址中的 ID。
- 授權的 Google 帳號與目標資料夾所屬帳號不同，確認兩者一致。

---

**Q：想要更換上傳帳號或重新授權**

刪除專案根目錄的 `token.json`，下次執行時會重新開啟瀏覽器授權畫面。

---

**Q：token.json 和 credentials.json 要加入 .gitignore 嗎？**

是的，兩者都應加入 `.gitignore`。`credentials.json` 包含 OAuth 用戶端金鑰，`token.json` 包含你的帳號存取權杖，兩者都屬於私密資訊，不應公開。目前專案的 `.gitignore` 已涵蓋這兩個檔案。
