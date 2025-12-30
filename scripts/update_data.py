# -*- coding: utf-8 -*-
"""
盤後一頁式戰報 - data.json 產生器
- 固定 4 檔：2330/2317/3231/2382（盤後自動更新）
- 產出：
  1) stocks：收盤 / 漲跌 / 漲跌%（以 TWSE STOCK_DAY 取最新交易日那天）
  2) foreign：外資買超(張)（以 TWSE fund/T86 取最新交易日）
  3) fubon_zgb：券商分點進出金額排行（ZGB 指定 6 家）
  4) fubon_zgk_d：外資買賣超排行（ZGK_D）
  5) taifex：大額交易人未平倉（前五/前十 + OI；只支援 4 檔股期）
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


TZ_TPE = timezone(timedelta(hours=8))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

FIXED_TICKERS = ["2330", "2317", "3231", "2382"]
TAIFEX_PRODUCTS = {
    "2330": "台積電",
    "2317": "鴻海",
    "3231": "緯創",
    "2382": "廣達",
}

# 指定 6 家（你原本那張表）
ZGB_TARGET_BROKERS = [
    "摩根大通",
    "台灣摩根士丹利",
    "新加坡商瑞銀",
    "美林",
    "花旗環球",
    "美商高盛",
]

# -----------------------
# 基礎工具
# -----------------------
def now_iso():
    return datetime.now(TZ_TPE).replace(microsecond=0).isoformat()


def to_int(s: str) -> int:
    s = (s or "").strip()
    if not s:
        return 0
    s = s.replace(",", "")
    m = re.search(r"-?\d+", s)
    return int(m.group(0)) if m else 0


def to_float(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0
    s = s.replace(",", "")
    # 漲跌價差可能是 "+20.00" / "-5.00" / "0.00"
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else 0.0


def ymd_to_roc(ymd: str) -> str:
    # ymd: YYYYMMDD -> "114/12/30"
    y = int(ymd[0:4]) - 1911
    m = int(ymd[4:6])
    d = int(ymd[6:8])
    return f"{y}/{m:02d}/{d:02d}"


def http_get(url: str, timeout=30) -> requests.Response:
    return requests.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
            "Connection": "keep-alive",
        },
        timeout=timeout,
    )


def decode_html(resp: requests.Response) -> str:
    """
    富邦/金額排行常見 Big5/CP950；TWSE 通常 UTF-8。
    用 content 嘗試多種 decode。
    """
    raw = resp.content or b""
    for enc in ("utf-8", "big5", "cp950"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")


# -----------------------
# 1) 找最新/前一交易日（用 MI_INDEX：非交易日會 No data）
# -----------------------
def find_latest_trading_day(max_lookback_days=20):
    base = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALLBUT0999&date="
    today = datetime.now(TZ_TPE).date()

    def is_trading(ymd: str) -> bool:
        try:
            r = http_get(base + ymd, timeout=30)
            j = r.json()
            stat = (j.get("stat") or "").lower()
            return "ok" in stat
        except Exception:
            return False

    latest = None
    for i in range(max_lookback_days):
        d = today - timedelta(days=i)
        ymd = d.strftime("%Y%m%d")
        if is_trading(ymd):
            latest = ymd
            break

    if not latest:
        # fallback：今天
        latest = today.strftime("%Y%m%d")

    prev = None
    latest_date = datetime.strptime(latest, "%Y%m%d").date()
    for i in range(1, max_lookback_days + 1):
        d = latest_date - timedelta(days=i)
        ymd = d.strftime("%Y%m%d")
        if is_trading(ymd):
            prev = ymd
            break

    if not prev:
        prev = (latest_date - timedelta(days=1)).strftime("%Y%m%d")

    return latest, prev


# -----------------------
# 2) 個股收盤 / 漲跌 / 漲跌%
#    用 STOCK_DAY（月資料）抓到「最新交易日那天」那一列
# -----------------------
def fetch_stock_close_change(ymd: str, ticker: str):
    url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={ymd}&stockNo={ticker}"
    r = http_get(url, timeout=30)
    j = r.json()

    if (j.get("stat") or "").upper() != "OK":
        return {
            "ticker": ticker,
            "name": "",
            "close": None,
            "change": None,
            "pct": None,
            "error": f"TWSE STOCK_DAY stat={j.get('stat')}",
        }

    roc = ymd_to_roc(ymd)
    data = j.get("data") or []
    row = None
    for it in data:
        if it and str(it[0]).strip() == roc:
            row = it
            break

    if not row:
        # 找不到當天，就取最後一列（偶發）
        row = data[-1] if data else None

    if not row:
        return {
            "ticker": ticker,
            "name": "",
            "close": None,
            "change": None,
            "pct": None,
            "error": "TWSE STOCK_DAY empty data",
        }

    # row: 日期, 成交股數, 成交金額, 開盤, 最高, 最低, 收盤, 漲跌價差, 成交筆數, 註記(可能有)
    close = to_float(row[6])
    chg = to_float(row[7])

    prev_close = close - chg
    pct = (chg / prev_close * 100.0) if prev_close not in (0, None) else 0.0

    # title 通常含： "114年12月2330 台積電各日成交資訊"
    title = j.get("title") or ""
    name = ""
    m = re.search(rf"{re.escape(ticker)}\s*([^\s]+)", title)
    if m:
        name = m.group(1).strip()

    return {
        "ticker": ticker,
        "name": name,
        "close": close,
        "change": chg,
        "pct": pct,
    }


# -----------------------
# 3) 外資買賣超（張）- TWSE T86
# -----------------------
def fetch_foreign_t86_map(ymd: str):
    url = f"https://www.twse.com.tw/fund/T86?response=json&date={ymd}&selectType=ALL"
    r = http_get(url, timeout=60)
    j = r.json()

    if (j.get("stat") or "").upper() != "OK":
        return {"_error": f"TWSE T86 stat={j.get('stat')}"}

    fields = j.get("fields") or []
    data = j.get("data") or []

    def find_idx(patterns):
        for p in patterns:
            for i, f in enumerate(fields):
                if p in str(f):
                    return i
        return None

    idx_code = find_idx(["證券代號"])
    idx_buy = find_idx(["外陸資買進股數", "外資買進股數"])
    idx_sell = find_idx(["外陸資賣出股數", "外資賣出股數"])
    idx_net = find_idx(["外陸資買賣超股數", "外資買賣超股數"])

    if idx_code is None or idx_buy is None or idx_sell is None:
        return {"_error": "TWSE T86 fields not found"}

    mp = {}
    for row in data:
        if not row or idx_code >= len(row):
            continue
        code = str(row[idx_code]).strip()
        buy = to_int(row[idx_buy]) if idx_buy < len(row) else 0
        sell = to_int(row[idx_sell]) if idx_sell < len(row) else 0
        net = to_int(row[idx_net]) if (idx_net is not None and idx_net < len(row)) else (buy - sell)

        # 1 張 = 1000 股（這裡用「張」做分級）
        net_lots = net / 1000.0

        mp[code] = {
            "buy_shares": buy,
            "sell_shares": sell,
            "net_shares": net,
            "net_lots": net_lots,
        }

    return mp


# -----------------------
# 4) MoneyDJ - ZGB（券商分點進出金額排行：改用 ZGB.djhtm）
#    取指定 6 家（若抓不到就回 error）
# -----------------------
def fetch_fubon_zgb():
    url = "https://fubon-ebrokerdj.fbs.com.tw/Z/ZG/ZGB/ZGB.djhtm"
    r = http_get(url, timeout=60)
    html = decode_html(r)
    soup = BeautifulSoup(html, "html.parser")

    # 找到包含「券商名稱」的表
    target_table = None
    for tb in soup.find_all("table"):
        ths = [th.get_text(strip=True) for th in tb.find_all("th")]
        if any("券商" in x for x in ths) and any("差額" in x or "買賣" in x for x in ths):
            target_table = tb
            break

    if not target_table:
        return {"error": "ZGB 找不到表格（可能版面變更）", "rows": []}

    rows = []
    for tr in target_table.find_all("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 4:
            continue

        broker = tds[0].strip()
        buy = to_int(tds[1])
        sell = to_int(tds[2])
        diff = to_int(tds[3])

        if not broker:
            continue

        rows.append({"broker": broker, "buy": buy, "sell": sell, "diff": diff})

    # 指定 6 家：依頁面順序過濾
    picked = []
    for b in ZGB_TARGET_BROKERS:
        hit = next((x for x in rows if b in x["broker"]), None)
        if hit:
            picked.append(hit)

    if len(picked) < 1:
        return {"error": "ZGB 有表格但找不到指定 6 家券商（可能名稱不同）", "rows": []}

    return {"rows": picked, "source": url}


# -----------------------
# 5) MoneyDJ - ZGK_D（外資買賣超排行）
#    直接解析表格（不要用 raw 文本，避免 .../截斷）
# -----------------------
def fetch_fubon_zgk_d(limit=30):
    url = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk/zgk_d.djhtm"
    r = http_get(url, timeout=60)
    html = decode_html(r)
    soup = BeautifulSoup(html, "html.parser")

    # 抓日期（通常有 "日期：12/30"）
    txt = soup.get_text("\n", strip=True)
    date_hint = None
    m = re.search(r"日期[:：]\s*(\d{1,2}/\d{1,2})", txt)
    if m:
        date_hint = m.group(1)

    # 找到「名次/股票名稱/超張數」的表格
    target_table = None
    for tb in soup.find_all("table"):
        ths = [th.get_text(strip=True) for th in tb.find_all("th")]
        if "名次" in ths and any("股票名稱" in x for x in ths) and any("超張數" in x for x in ths):
            target_table = tb
            break

    if not target_table:
        return {"error": "ZGK_D 找不到表格（可能版面變更）", "buy": [], "sell": [], "source": url}

    buy = []
    sell = []

    for tr in target_table.find_all("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        # 典型一列 10 格：買超(5格) + 賣超(5格)
        if len(tds) < 10:
            continue
        # rank 可能是空白或非數字
        if not re.match(r"^\d+$", (tds[0] or "").strip()):
            continue

        b_rank = to_int(tds[0])
        b_name = tds[1].strip()
        b_lots = to_float(tds[2])
        b_close = to_float(tds[3])
        b_chg = to_float(tds[4])

        s_rank = to_int(tds[5])
        s_name = tds[6].strip()
        s_lots = to_float(tds[7])
        s_close = to_float(tds[8])
        s_chg = to_float(tds[9])

        if b_name:
            buy.append(
                {"rank": b_rank, "name": b_name, "lots": b_lots, "close": b_close, "chg": b_chg}
            )
        if s_name:
            sell.append(
                {"rank": s_rank, "name": s_name, "lots": s_lots,_


