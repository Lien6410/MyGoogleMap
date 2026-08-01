# lottery.html 篩選優化 + UI/UX 美化 設計

- 日期：2026-08-01
- 範圍：純前端（`lottery.html`、新增 `lottery_logic.js` + 測試）。不動 Python 管線、不改 `window.STORES_DATA` 欄位契約、不改 `hours_logic.js`。
- 相關記憶：[[project-mygooglemap]]、[[gh-pages-deploy]]、[[postgres-pipeline]]

## 1. 背景與問題

`lottery.html` 是從 `data/output/stores_data.js`（`window.STORES_DATA`，781 家）抽美食的隨機工具。目前資料實際覆蓋率：

| 欄位 | 覆蓋率 |
|---|---|
| `avg_spending` | 96% |
| `cuisine_type` | 100%（但 43% 是「其他」、42%「中式」） |
| `distance_km` | 33% |
| `hours` | 0% |

**現存 bug：** 預設篩選勾了「營業中」（hours 過濾）與「1km/1~3km」（距離過濾），但都沒勾「未知」。`matchesHoursFilter` 對無 hours 的店只會被「未知」命中 → 用預設值幾乎 0 家符合，每次抽籤都走「從全部抽」的 fallback，篩選器形同虛設。

**根因：** 篩選器把「覆蓋率極低的欄位（hours/距離）」當**硬篩**，資料還沒補齊就把整池砍空。

## 2. 目標 / 非目標

**目標**
1. 修掉空池 bug，讓預設值在**任何資料覆蓋率**下都給出合理、非空的候選池（自適應）。
2. 針對主要情境「**現在決定去哪吃**」給一組推薦預設，並提供一鍵情境快捷。
3. 加權抽籤：離家近、營業中的店抽中機率更高（可一鍵切回等機率）。
4. UI 美化：暖食慾配色（方向 B）＋一鍵情境版面（方向 L3）。
5. 把可測的核心邏輯抽成純函式模組，比照 `hours_logic.js` 加 `node --test`。

**非目標**
- 不改 Python enrichment/管線、不改資料契約、不改 `hours_logic.js`。
- 不做後端、不做使用者帳號、不持久化使用者偏好（重整即回預設；未來可選）。
- 不新增地圖嵌入、不改抽籤動畫的基本機制（僅換配色）。

## 3. 核心設計理念

**覆蓋率高的欄位當硬篩、覆蓋率低或偏好性的欄位當加權。**

- 硬篩（有勾才進池）：縣市、人均、菜系、回訪 —— 覆蓋率足夠。
- 加權（不砍店、只調機率）：距離、營業中 —— 覆蓋率低，硬篩會空池。
- 自適應：載入時算實際覆蓋率，覆蓋率低的維度預設放寬（全勾）。

## 4. 加權公式（預設 ON）

```
weight(store) = wDist(store) × wOpen(store)
```

- `wDist`：`distance_km == null → 1.0`（中性不懲罰）；否則 `≤1km→3.0, ≤3→2.0, ≤5→1.3, ≤10→0.8, >10→0.4`
- `wOpen`：無 hours 資料 `→ 1.0`（中性）；有資料且現在營業 `→ 1.8`；有資料但已打烊 `→ 0.5`

單一全域權重曲線；各情境鍵只調「硬篩」與「加權開關」，不各自定義權重曲線（降複雜度）。抽選以累積權重法（cumulative-weight）在候選池挑一位贏家；`rng` 可注入以利測試。加權關閉時退化為等機率。

## 5. 自適應預設

載入時 `computeCoverage(stores)` 算出 `hours`、`distance` 覆蓋率。門檻 `HOURS_COVERAGE_THRESHOLD = 0.5`。

- **hours 硬篩預設**：覆蓋率 `< 0.5` → 全勾（open-now + 各餐時段 + 未知，等於不限）；`≥ 0.5` → 只勾 `{open-now, 未知}`（沒資料的店仍留池靠加權排）。
- **距離**：智慧推薦一律全勾（純靠加權偏好近），不因覆蓋率預設收窄。
- 「未知」在會收窄的情境（現在營業、附近）**永遠一併勾選**，作為空池保險。

## 6. 一鍵情境（L3 頂部快捷鍵，橫向可滑）

每個鍵 = 一組硬篩狀態 + 加權開關，點下即套用（可直接抽）。宣告式定義於 `PRESET_SPECS`。

| 鍵 | 相對「智慧推薦」的差異 |
|---|---|
| 🎯 **智慧推薦**（載入即套） | 基準：縣市={新竹市，新竹縣(若資料有)}、人均={≤200,≤500,未知}、菜系=全、回訪=全部、距離=全勾、hours=自適應、加權=ON |
| 📍 **附近** | 距離硬篩改為 {≤1, ≤3, 未知} |
| 🆕 **沒去過** | 回訪=未去過 |
| 🍜 **現在營業** | hours 硬篩改為 {open-now, 未知} |
| 🎲 **全部隨機** | 縣市/人均/菜系/回訪/距離/hours 全勾（含未知/非台灣）、加權=OFF |

**自訂狀態：** 使用者在進階面板手動改任何條件 → 高亮鍵清除、顯示「自訂」，表示目前非套用中的情境。

## 7. 版面（L3）與視覺（B 暖食慾）

- **頂部**：標題 + 一排情境快捷鍵（可橫向滑）+「篩選 ▾」展開鈕。
- **主體（hero）**：置中大抽籤區。抽籤鈕上方顯示「符合 N 家」。`N=0` 走現有 fallback（從全部抽並標示 badge）。轉動動畫沿用現有 slot-machine 機制、僅換配色。
- **進階面板「篩選 ▾」**（預設收合）：現有全部細部條件（回訪／營業時間／菜系／距離／人均／縣市，重新美化）+「⚡ 加權抽籤」開關（預設 ON）。
- **結果卡**：暖色化。標籤=菜系／營業狀態／距離／均消／回訪；欄位=地址·來源清單·備註；按鈕=「在 Google 地圖開啟」「再抽一次」。
- **自適應提示**：偵測到 hours 覆蓋率低時，於「現在營業」鍵旁顯示小字「營業時間資料未匯入，已用寬鬆模式」。
- **配色**：炭黑背景（`#1a1210`→`#2b1a12`）、琥珀/番茄橘主色（`#f97316`/`#ef4444`/`#fb923c`）、暖白文字（`#fff7ed`）；沿用 Google Fonts。RWD：桌機情境鍵一排、手機橫向捲動；進階面板手機為全寬展開。

## 8. 元件切分（可測性）

現有 `lottery.html` 內嵌 ~400 行 script，職責過雜。抽出純邏輯模組（比照 `hours_logic.js` 瀏覽器/Node 雙用）：

**新增 `lottery_logic.js`（純函式，無 DOM，`window.LotteryLogic` + `module.exports`；Node 端 `require('./hours_logic.js')`，瀏覽器用 `window.HoursLogic`）：**
- `TAIWAN_COUNTIES` / `extractCounty(address)`
- `CUISINE_ALIASES` / `normalizeCuisine(raw)`
- `distanceBucket(km)` → `'1'|'3'|'5'|'10'|'far'|'unknown'`
- `priceBucket(spending)` → `'200'|'500'|'1000'|'expensive'|'free'`
- `storeMatches(store, filters, now)` → bool（吃 `filters` 的 Set 集合，含 hours 委派 `HoursLogic.matchesHoursFilter`）
- `computeCoverage(stores)` → `{hours, distance, total}`
- `HOURS_COVERAGE_THRESHOLD`、`adaptiveHoursDefault(coverage)` → Set
- `storeWeight(store, now, weightOn)` → number（§4）
- `weightedPick(pool, now, weightOn, rng=Math.random)` → store
- `PRESET_SPECS`、`resolvePreset(name, coverage, dataCounties)` → 正規化 filter state（§6）

**`lottery.html`（僅 DOM glue）：** 渲染情境鍵與進階面板、綁事件、套用/讀取 filter state、動畫、結果卡渲染、計數。呼叫 `LotteryLogic` 與 `HoursLogic`。

**依賴關係：** `lottery.html` → `LotteryLogic` → `HoursLogic`。`stores_data.js` 資料契約不變。

## 9. 測試

新增 `lottery_logic.test.js`（`node:test` + `node:assert`，`node --test` 執行，注入假 `now`（getDay/getHours/getMinutes）與假 `rng`）：
- `distanceBucket` / `priceBucket` 邊界（0、200、500、1000、null）。
- `extractCounty`（臺→台正規化、找不到→null）、`normalizeCuisine`（台式→中式）。
- `computeCoverage`（全空→0、部分→比例）。
- `adaptiveHoursDefault`（<0.5 全勾含各餐、≥0.5 僅 open-now+unknown）。
- `storeWeight`（近/遠、營業/打烊/無資料的乘積；weightOn=false→1）。
- `weightedPick`（注入 rng 落在特定累積區間 → 命中預期店；空池行為）。
- `storeMatches`（各硬篩維度命中/排除；無 hours 僅經「未知」）。
- `resolvePreset`（五個情境的 filter state 正確；附近收距離、現在營業收 hours 且都含未知）。
- 迴歸：既有 `hours_logic.test.js` 續綠。

## 10. 風險與緩解

- **改動 `lottery.html` 大**：抽邏輯到 `lottery_logic.js` 有回歸風險 → 先寫 `lottery_logic.test.js`（TDD），DOM glue 以現有行為為對照逐段搬。
- **部署**：`gh-pages` 需 force-add `stores_data.js`（被 gitignore）；本次不動該檔。新增 `lottery_logic.js` 需一併 commit 並在 `lottery.html` 以 `<script src>` 引入。
- **覆蓋率門檻 0.5 為經驗值**：集中成常數，日後易調。

## 11. 交付物

- `lottery_logic.js`（新）、`lottery_logic.test.js`（新）
- `lottery.html`（改：版面 L3 + 視覺 B + 改用 LotteryLogic）
- 不動：`hours_logic.js`、`stores_data.js` 契約、Python 管線
