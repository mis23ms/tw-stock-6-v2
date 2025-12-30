# 盤後一頁式台股戰報（6 支：4 固定 + 2 自選）｜GitHub Pages / 自動更新

這個版本是 **tw-stock-06（6 支）** 的延伸：  
- 固定 4 檔：**2330 台積電、2317 鴻海、3231 緯創、2382 廣達**（由 GitHub Actions 盤後自動更新）  
- 自選 2 檔：你每天手動輸入（存在瀏覽器 localStorage；**不影響固定 4 檔**）

新增兩件事（你要求的「不變，只加」）
1) **顏色標註（只針對漲跌 + 外資）**  
   - 紅色：上漲 / 買超（越深越強）  
   - 綠色：下跌 / 賣超（越深越強）  
   - 外資張數分級（<800 不標）  
     - ≥ 3000：強買超 / 強賣超  
     - 800～2999：買超 / 賣超  
2) **期貨未平倉（TAIFEX 大額交易人：前五大/前十大）**  
   - 只支援：**台積電期貨 / 鴻海期貨 / 緯創期貨 / 廣達期貨**  
   - 顯示「所有契約」彙總列：  
     - 前五大：多 / 空 / 淨（多-空）  
     - 前十大：多 / 空 / 淨（多-空）  
     - 未平倉量  
   - 若抓不到，卡片會直接顯示原因（避免你不知道是「沒資料」還是「壞掉」）

---

# 給一般使用者（不用寫程式，只要照做）

## A. 建 GitHub repo
1. 建 repo（例：`tw-stock-6-v2`）  
2. 把本專案檔案放進去（照下面「你要放的檔案」）

## B. 開啟 GitHub Pages（變成可分享網址）
Settings → Pages  
- Source：Deploy from a branch  
- Branch：`main`  
- Folder：`/docs`  

完成後網址會像：
`https://<你的帳號>.github.io/<repo>/`

## C. 讓它每天盤後自動更新（固定 4 檔）
`.github/workflows/update.yml` 已設定：
- 週一到週五 **17:20（台灣時間）** 自動跑
- 手動也可在 Actions → Update data → Run workflow

> **重要：Playwright 必須安裝瀏覽器**  
> 沒裝會出現：`BrowserType.launch: Executable doesn't exist...`  
> workflow 已加上 `python -m playwright install --with-deps chromium`

---

# 你要放的檔案（v2 版）

把下面檔案覆蓋到你的新 repo：

- `README.md`（就是這份）
- `.github/workflows/update.yml`
- `scripts/update_data.py`
- `docs/index.html`（不用改，維持你原本的）
- `docs/app.js`（改：新增標色 + 期貨區塊）
- `docs/style.css`（改：在最底部加 v2 CSS）
- `requirements.txt`（不變即可）

---

# 顏色規則（白話版）
- **漲跌**  
  - 上漲 → 紅（📈）  
  - 下跌 → 綠（📉）  
  - 震盪/0 → 灰（➖）  
  - 越深越強：用「漲跌% 絕對值」分 lv1/lv2/lv3（你只要看深淺即可）
- **外資買賣超（張）**  
  - < 800：不標籤  
  - 800～2999：買超 / 賣超  
  - ≥ 3000：強買超 / 強賣超  

---

# 期貨（TAIFEX）顯示方式
- 只顯示 4 檔固定股的「股票期貨」：
  - 台積電期貨、鴻海期貨、緯創期貨、廣達期貨
- 只顯示「所有契約」彙總列（不用去看每個到期月份）
- 前五大/前十大：多、空、淨（多-空）  
- 抓不到就顯示原因（例如 TAIFEX 維護、版面變動、網路被擋）

---

# 曾經踩過的坑（務必看）

## 坑 1：ZGB 會突然變成紅字錯誤
原因：Playwright 沒裝 Chromium。  
解法：workflow 一定要有：
`python -m playwright install --with-deps chromium`

## 坑 2：期貨資料「有時候抓不到」
TAIFEX 偶爾維護 / 版面改 / 回應慢。  
這版做法是：
- 抓不到 → 直接把原因顯示在卡片裡（不是整頁壞掉）

## 坑 3：自選 2 檔跟固定 4 檔不是同一條更新路徑
- 固定 4 檔：後端腳本每天跑，寫進 `docs/data.json`  
- 自選 2 檔：你在網頁上輸入，存在你的瀏覽器（localStorage）  
  → 所以你沒輸入就只有 4 檔

---

# 給下一個 AI / 維護者（先自檢，不要來回 debug）

1. 先看 Actions 是否成功（綠燈）  
2. 若 ZGB 出現 `Executable doesn't exist` → 99% 是 Playwright 沒裝 Chromium  
3. 若 TAIFEX 期貨區塊顯示「抓不到」  
   - 先打開 TAIFEX 頁確認今天是否正常  
   - 再看 `scripts/update_data.py` 的 table 解析是否要調整  
4. 永遠不要「猜」：抓不到就把原因顯示給使用者看（本版已做）

---

# 免責
此專案是資訊整理與視覺化，非投資建議。資料來源若有延遲/缺漏，以原站公告為準。
