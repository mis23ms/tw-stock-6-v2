# scripts/update_data.py
# -*- coding: utf-8 -*-
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# =====================
# 基本設定
# =====================

TZ_TW = timezone(timedelta(hours=8))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(ROOT_DIR, "docs")
DATA_JSON_PATH = os.path.join(DOCS_DIR, "data.json")

# 固定 4 檔
STOCKS = [
    {"ticker": "2330", "name": "台積電"},
    {"ticker": "2317", "name": "鴻海"},
    {"ticker": "3231", "name": "緯創"},
    {"ticker": "2382", "name": "廣達"},
]

# === 期貨：大額交易人未沖銷部位（前五大/前十大） ===
TAIFEX_LARGE_TRADER_URL = "https://www.taifex.com.tw/cht/3/largeTraderFutQry"

# 只抓這四檔「股票期貨」
STOCK_FUTURES_NAME_BY_TICKER = {
    "2330": "台積電",
    "2317": "鴻海",
    "3231": "緯創",
    "2382": "廣達",
}

# =====================
# 工具
# =====================

def _now_tw_str() -> str:
    return datetime.now(TZ_TW).strftime("%Y-%m-%d %H:%M:%S %z")

def _safe_write_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def _get_json(url: str, timeout: int = 20) -> dict:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()

def _get_text(url: str, timeout: int = 20) -> str:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text

def _post_text(url: str, data: dict, timeout: int = 30) -> str:
    r = requests.post(url, data=data, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text

def _parse_int_first(text: str):
    if not text:
        return None
    m = re.search(r"-?[\d,]+", str(text))
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except Exception:
        return None

def _parse_float_first(text: str):
    if text is None:
        return None
    m = re.search(r"-?[\d,]+(?:\.\d+)?", str(text))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except Exception:
        return None

def _minguo_to_ymd(minguo: str) -> str | None:
    """
    TWSE STOCK_DAY 的日期常見：114/12/30
    -> 2025-12-30
    """
    m = re.match(r"^\s*(\d{2,3})/(\d{1,2})/(\d{1,2})\s*$", str(minguo))
    if not m:
        return None
    y = int(m.group(1)) + 1911
    mm = int(m.group(2))
    dd = int(m.group(3))
    return f"{y:04d}-{mm:02d}-{dd:02d}"

def _twse_last_two_trading_dates(stock_no: str = "2330") -> tuple[str | None, str | None]:
    """
    用 TWSE STOCK_DAY 抓某支股票「最近兩個交易日」(YYYY-MM-DD)
    先抓當月，不夠再抓上月。
    """
    now = datetime.now(TZ_TW)
    for back_month in range(0, 2):
        dt = now.replace(day=1) - timedelta(days=back_month * 31)
        yyyymm01 = dt.strftime("%Y%m01")
        url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&stockNo={stock_no}&date={yyyymm01}"
        try:
            j = _get_json(url, timeout=20)
            rows = j.get("data") or []
            if len(rows) >= 2:
                last = _minguo_to_ymd(rows[-1][0])
                prev = _minguo_to_ymd(rows[-2][0])
                return last, prev
            if len(rows) == 1:
                last = _minguo_to_ymd(rows[-1][0])
                return last, None
        except Exception:
            continue
    return None, None

# =====================
# TAIFEX：大額交易人（前五大/前十大）— 股票期貨
# =====================

def _normalize_zh(s: str) -> str:
    return str(s or "").replace("臺", "台").strip()

def _find_option_value(soup: BeautifulSoup, keyword: str):
    """
    在所有 <option> 裡找出包含 keyword 的那個 option，
    回傳：(select_name, option_value, option_text)
    """
    kw = _normalize_zh(keyword)
    for opt in soup.select("option"):
        t = _normalize_zh(opt.get_text(" ", strip=True))
        if kw in t:
            sel = opt.find_parent("select")
            if sel and sel.get("name") and opt.get("value") is not None:
                return sel.get("name"), opt.get("value"), t
    return None, None, None

def _extract_form_payload(soup: BeautifulSoup) -> dict:
    """
    把表單內所有 input(hidden/text) 的預設值抓出來，作為 POST base payload
    """
    form = soup.find("form")
    if not form:
        return {}
    payload = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        payload[name] = inp.get("value", "")
    return payload

def _parse_taifex_result(html: str):
    """
    從查詢結果頁裡，抓『所有契約』那列的：
      - 前五大 多/空
      - 前十大 多/空
      - 未平倉量
    """
    out = {"top5": {}, "top10": {}, "open_interest": None}
    soup = BeautifulSoup(html, "lxml")

    # 找主表格：通常是 rows 最多那張
    tables = soup.find_all("table")
    if not tables:
        return None, "TAIFEX 頁面找不到表格"

    main = max(tables, key=lambda t: len(t.find_all("tr")))

    target_row = None
    for tr in main.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tds]
        if len(cells) < 10:
            continue

        # 嘗試辨識「所有契約」：常見出現在 年/月 欄位
        joined = " ".join(cells[:4])
        if "所有契約" in joined or ("所有" in joined and "契約" in joined):
            target_row = cells
            break

    if not target_row:
        return None, "TAIFEX 找不到『所有契約』彙總列（可能版面變更/當天無資料）"

    # 這張表的欄位位置可能會動，但通常可用「抓口數」策略：
    # 依你之前成功版面：多/空/多%/空% 交錯
    # 這裡取第一個表格列中，可能對應到：
    #   前五大：多(口)、多%、空(口)、空%
    #   前十大：多(口)、多%、空(口)、空%
    #   未平倉量：最後
    # 我們直接從整列裡「依序抓出整數」來還原：
    nums = [_parse_int_first(x) for x in target_row]
    nums = [n for n in nums if isinstance(n, int)]

    # 需要至少：top5 long/short、top10 long/short、oi
    if len(nums) < 5:
        return None, "TAIFEX 數字欄位不足，無法解析"

    # 盡量穩：通常最後一個是 OI
    oi = nums[-1]
    # 前面依序取 4 個作為：top5 long, top5 short, top10 long, top10 short
    # 這是最穩的通用假設（比硬卡欄位 index 可靠）
    t5_long = nums[0]
    t5_short = nums[1]
    t10_long = nums[2]
    t10_short = nums[3]

    out["top5"] = {"long": t5_long, "short": t5_short, "net": t5_long - t5_short}
    out["top10"] = {"long": t10_long, "short": t10_short, "net": t10_long - t10_short}
    out["open_interest"] = oi
    return out, None

def fetch_taifex_large_trader_stock_futures() -> dict:
    """
    正確作法：TAIFEX 這頁要走表單查詢（POST），GET 通常拿不到你要的股票期貨結果。
    """
    out = {"date": None, "by_ticker": {}, "error": None}
    try:
        html0 = _get_text(TAIFEX_LARGE_TRADER_URL, timeout=30)
        soup0 = BeautifulSoup(html0, "lxml")

        # 抓日期（能抓到就填）
        m = re.search(r"查詢日期[^0-9]*(\d{4}/\d{2}/\d{2})", html0)
        if m:
            out["date"] = m.group(1)

        base = _extract_form_payload(soup0)

        # 找「商品」select：用 option 文字去反推 select name + option value
        # 期貨商品名稱可能是「台積電期貨」或「台積電股期」之類，所以用公司名去找
        first_kw = list(STOCK_FUTURES_NAME_BY_TICKER.values())[0]
        sel_name, _, _ = _find_option_value(soup0, first_kw)
        if not sel_name:
            # 再用「期貨」字樣做 fallback：找第一個含「期貨」的 option
            for opt in soup0.select("option"):
                t = _normalize_zh(opt.get_text(" ", strip=True))
                if "期貨" in t:
                    sel = opt.find_parent("select")
                    if sel and sel.get("name"):
                        sel_name = sel.get("name")
                        break
        if not sel_name:
            out["error"] = "TAIFEX 無法定位『商品』下拉選單（版面可能變更）"
            return out

        # 逐一查四檔
        for ticker, company in STOCK_FUTURES_NAME_BY_TICKER.items():
            # 優先找含公司名 + 期貨 的 option
            opt_name, opt_val, opt_text = _find_option_value(soup0, company)
            if not opt_val:
                out["by_ticker"][ticker] = None
                continue

            payload = dict(base)
            payload[sel_name] = opt_val

            # 有些表單還有 queryType / type 等欄位，base 已含 hidden 值
            html = _post_text(TAIFEX_LARGE_TRADER_URL, data=payload, timeout=30)

            parsed, err = _parse_taifex_result(html)
            if err:
                out["by_ticker"][ticker] = None
                # 把原因記在總 error（但不要覆蓋前面可能成功的）
                out["error"] = out["error"] or f"{company}：{err}"
                continue

            out["by_ticker"][ticker] = {
                "product": opt_text or company,
                "top5": parsed["top5"],
                "top10": parsed["top10"],
                "open_interest": parsed["open_interest"],
            }

            time.sleep(0.2)

        # 如果四檔都沒拿到
        ok_cnt = sum(1 for v in out["by_ticker"].values() if v)
        if ok_cnt == 0 and not out["error"]:
            out["error"] = "TAIFEX 今日查不到四檔股票期貨資料（可能維護/暫停/版面變更）"

        return out

    except Exception as e:
        out["error"] = f"TAIFEX 抓取失敗：{e}"
        return out

# =====================
# 股票：價格（收盤/漲跌/漲跌%）
# =====================

def fetch_close_and_change_twse(ticker: str, latest_ymd: str | None = None) -> dict:
    """
    用 TWSE STOCK_DAY（月資料）抓最近兩筆收盤 -> 算 change / pct
    """
    try:
        # 用 latest_ymd 所在月份當查詢月份；沒有就用現在月份
        if latest_ymd and re.match(r"^\d{4}-\d{2}-\d{2}$", latest_ymd):
            dt = datetime.strptime(latest_ymd, "%Y-%m-%d")
        else:
            dt = datetime.now(TZ_TW)
        yyyymm01 = dt.strftime("%Y%m01")
        url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&stockNo={ticker}&date={yyyymm01}"
        j = _get_json(url, timeout=20)
        rows = j.get("data") or []
        if not rows:
            return {"close": None, "change": None, "change_pct": None}

        last = rows[-1]
        prev = rows[-2] if len(rows) >= 2 else None

        close = _parse_float_first(last[6])
        prev_close = _parse_float_first(prev[6]) if prev else None

        change = None if close is None or prev_close is None else (close - prev_close)
        change_pct = None if change is None or not prev_close else (change / prev_close * 100)

        return {"close": close, "change": change, "change_pct": change_pct}
    except Exception:
        return {"close": None, "change": None, "change_pct": None}

def fetch_close_and_change(ticker: str, latest_ymd: str | None = None) -> dict:
    # 先走 TWSE（ETF/上市股票都吃得到）
    return fetch_close_and_change_twse(ticker, latest_ymd=latest_ymd)

# =====================
# 外資買賣超(張)：D0 / D1
# =====================

def fetch_foreign_net_shares_for_date(ticker: str, yyyymmdd: str) -> str | None:
    """
    TWSE T86：指定日期抓外資買賣超(張)
    """
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999&date={yyyymmdd}&_=1"
    j = _get_json(url, timeout=25)
    data = j.get("data") or []
    for row in data:
        if str(row[0]).strip() == str(ticker):
            # 外資買賣超(張) 通常在 row[4]
            return row[4] if len(row) > 4 else None
    return None

def fetch_foreign_net_shares(ticker: str, latest_ymd: str | None, prev_ymd: str | None) -> dict:
    """
    外資買賣超(張)：
    - D0: 最新交易日
    - D1: 前一交易日
    """
    out = {"D0": None, "D1": None}
    try:
        if latest_ymd:
            ymd = latest_ymd.replace("-", "")
            out["D0"] = fetch_foreign_net_shares_for_date(ticker, ymd)
        if prev_ymd:
            ymd = prev_ymd.replace("-", "")
            out["D1"] = fetch_foreign_net_shares_for_date(ticker, ymd)
    except Exception:
        pass
    return out

# =====================
# 富邦：ZGB / ZGK_D（保留 raw，交給前端解析）
# =====================

def fubon_zgb():
    url = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "lxml")
    return {"raw": soup.get_text("\n", strip=True)}

def fubon_zgk_d():
    url = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk/zgk_d.djhtm"
    try:
        html = _get_text(url, timeout=30)
        soup = BeautifulSoup(html, "lxml")
        return {"raw": soup.get_text("\n", strip=True)}
    except Exception as e:
        return {"error": str(e)}

# =====================
# 主程式
# =====================

def main():
    # 用 TWSE 抓到的「最近兩個交易日」來當全站基準
    latest, prev = _twse_last_two_trading_dates("2330")
    latest_trading_day = latest or datetime.now(TZ_TW).strftime("%Y-%m-%d")
    prev_trading_day = prev or (datetime.now(TZ_TW) - timedelta(days=1)).strftime("%Y-%m-%d")

    stocks_out = {}
    for s in STOCKS:
        ticker = s["ticker"]
        name = s["name"]

        price = fetch_close_and_change(ticker, latest_ymd=latest_trading_day)
        foreign = fetch_foreign_net_shares(ticker, latest_trading_day, prev_trading_day)

        stocks_out[ticker] = {
            "ticker": ticker,
            "name": name,
            "price": price,
            "foreign_net_shares": foreign,
        }

        time.sleep(0.2)

    out = {
        "generated_at": _now_tw_str(),
        "latest_trading_day": latest_trading_day,
        "prev_trading_day": prev_trading_day,
        "stocks": stocks_out,
        "taifex_large_trader": fetch_taifex_large_trader_stock_futures(),
        "fubon_zgb": fubon_zgb(),
        "fubon_zgk_d": fubon_zgk_d(),
    }

    _safe_write_json(DATA_JSON_PATH, out)
    print(f"[OK] write {DATA_JSON_PATH}")

if __name__ == "__main__":
    main()

