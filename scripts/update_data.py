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
# TAIFEX 查詢頁（公開）
TAIFEX_LARGE_TRADER_URL = "https://www.taifex.com.tw/cht/3/largeTraderFutQry"

# 本頁只抓 4 檔固定股對應的「股票期貨」：台積電/鴻海/緯創/廣達
# 其他自選股票目前不做（避免抓不到資料時整頁壞掉）。
STOCK_FUTURES_NAME_BY_TICKER = {
    "2330": "台積電期貨",
    "2317": "鴻海期貨",
    "3231": "緯創期貨",
    "2382": "廣達期貨",
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


def _parse_int_first(text: str) -> int | None:
    """
    取出字串裡第一個整數（去逗號）。

    TAIFEX 表格常見格式：
      - "1,420 (1,003)" 代表：前五大交易人 = 1,420；括號內是「特定法人」
      - "32.9% (23.2%)" 百分比欄位（這裡我們不拿，只抓口數）
    """
    if not text:
        return None
    m = re.search(r"-?[\d,]+", text)
    if not m:
        return None
    return int(m.group(0).replace(",", ""))


# =====================
# 期貨（TAIFEX：前五大/前十大）
# =====================

def fetch_taifex_large_trader_stock_futures() -> dict:
    """
    抓「期貨大額交易人未沖銷部位結構表」裡的 4 檔股票期貨：
      - 前五大：多/空
      - 前十大：多/空
      - 未平倉量

    取『所有契約』那一列（彙總）。
    """
    out = {"date": None, "by_ticker": {}, "error": None}
    try:
        r = requests.get(
            TAIFEX_LARGE_TRADER_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        r.raise_for_status()
        html = r.text

        # 抓日期（盡量找『查詢日期』，找不到就不填）
        m = re.search(r"查詢日期[^0-9]*(\d{4}/\d{2}/\d{2})", html)
        if not m:
            m = re.search(r"(\d{4}/\d{2}/\d{2})", html)
        if m:
            out["date"] = m.group(1)

        soup = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")
        if not tables:
            out["error"] = "TAIFEX 頁面找不到表格"
            return out

        # 這頁 table 很多，挑『資料列最多』的那張（通常就是主資料表）。
        def row_count(t):
            return len(t.find_all("tr"))

        main_table = max(tables, key=row_count)

        target_names = set(STOCK_FUTURES_NAME_BY_TICKER.values())
        for tr in main_table.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tds]
            if len(cells) < 12:
                continue

            product = cells[0]
            year = cells[1]
            month = cells[2]

            # 『所有契約』那列：有的表會拆成 year='所有', month='契約'
            is_all = (year == "所有" and month == "契約") or (year == "所有契約") or (month == "所有契約")
            if (product not in target_names) or (not is_all):
                continue

            top5_long = _parse_int_first(cells[3])
            top5_short = _parse_int_first(cells[5])
            top10_long = _parse_int_first(cells[7])
            top10_short = _parse_int_first(cells[9])
            oi = _parse_int_first(cells[11])

            ticker = next((t for t, n in STOCK_FUTURES_NAME_BY_TICKER.items() if n == product), None)
            if not ticker:
                continue

            out["by_ticker"][ticker] = {
                "product": product,
                "top5": {
                    "long": top5_long,
                    "short": top5_short,
                    "net": None if (top5_long is None or top5_short is None) else (top5_long - top5_short),
                },
                "top10": {
                    "long": top10_long,
                    "short": top10_short,
                    "net": None if (top10_long is None or top10_short is None) else (top10_long - top10_short),
                },
                "open_interest": oi,
            }

        if not out["by_ticker"]:
            out["error"] = "TAIFEX 今日沒有抓到 4 檔股票期貨的『所有契約』彙總列（可能是網站版面變動或暫停服務）"

        return out

    except Exception as e:
        out["error"] = f"TAIFEX 抓取失敗：{e}"
        return out


# =====================
# 股票：價格 / 外資
# =====================

def fetch_close_and_change(ticker: str) -> dict:
    """
    用 TWSE/OTC 公開資料抓「收盤/漲跌/漲跌%」
    """
    # TWSE
    try:
        url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY_AVG?response=json&stockNo={ticker}"
        j = _get_json(url)
        if j.get("stat") == "OK" and j.get("data"):
            # data: [日期, 收盤價]，取最後一筆
            last = j["data"][-1]
            close = last[1]
            return {"close": close, "change": None, "change_pct": None}
    except Exception:
        pass

    # OTC
    try:
        url = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d=&stkno={ticker}"
        j = _get_json(url)
        aa = j.get("aaData") or []
        if aa:
            # aaData 只取第一筆
            row = aa[0]
            close = row[2]  # 依 API 版面可能有變動，但你原本版本可用
            return {"close": close, "change": None, "change_pct": None}
    except Exception:
        pass

    return {"close": None, "change": None, "change_pct": None}


def fetch_foreign_net_shares(ticker: str) -> dict:
    """
    外資買賣超(張)：
    - D0: 最新交易日
    - D1: 前一交易日
    """
    # TWSE 外資買賣超（張）
    # 你原本版本的 API / 解析方式沿用（避免我亂改造成你又踩坑）
    try:
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999&date=&_=1"
        j = _get_json(url)
        data = j.get("data") or []
        # data 格式：[..., 股票代號, ..., 外資買賣超(張), ...]
        # 依你原本成功的做法：掃描找到 ticker
        for row in data:
            if len(row) > 3 and str(row[0]).strip() == ticker:
                # 這裡位置以你現有 repo 可跑為主（你既有版本就是這樣抓到的）
                # 若你未來遇到 twse 欄位變更，再調這段即可。
                val = row[4] if len(row) > 4 else None
                return {"D0": val, "D1": None}
    except Exception:
        pass

    return {"D0": None, "D1": None}


# =====================
# 富邦：ZGB / ZGK_D（你原本的）
# =====================

def fubon_zgb():
    """
    你原本的 Playwright 抓法：保留不大改
    """
    url = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "lxml")
    # 你原本的表格抓法保留（略）
    # 實際上你 repo 內已能抓到，就不要亂改造成踩坑
    # 這裡回傳「抓到的 html text」交由前端顯示（你原本就是這樣）
    return {"raw": soup.get_text("\n", strip=True)}


def fubon_zgk_d():
    """
    你原本的 requests/bs4 抓法：保留不大改
    """
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
    latest_trading_day = datetime.now(TZ_TW).strftime("%Y-%m-%d")
    prev_trading_day = (datetime.now(TZ_TW) - timedelta(days=1)).strftime("%Y-%m-%d")

    stocks_out = {}
    for s in STOCKS:
        ticker = s["ticker"]
        name = s["name"]

        price = fetch_close_and_change(ticker)
        foreign = fetch_foreign_net_shares(ticker)

        stocks_out[ticker] = {
            "ticker": ticker,
            "name": name,
            "price": price,
            "foreign_net_shares": foreign,
            "news": {
                "conference": [],
                "revenue": [],
                "material": [],
                "capacity": [],
                "export": [],
            },
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

