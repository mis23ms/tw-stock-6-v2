# -*- coding: utf-8 -*-
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# Optional (only used as fallback for Fubon pages if requests is blocked)
try:
    from playwright.sync_api import sync_playwright  # type: ignore
except Exception:  # pragma: no cover
    sync_playwright = None  # type: ignore


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
STOCK_FUTURES_KEYWORD_BY_TICKER = {
    "2330": "台積電",
    "2317": "鴻海",
    "3231": "緯創",
    "2382": "廣達",
}

# 富邦 DJ
FUBON_ZGB_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm"
FUBON_ZGK_D_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk/zgk_d.djhtm"


# =====================
# 工具
# =====================

def _now_tw() -> datetime:
    return datetime.now(TZ_TW)

def _now_tw_str() -> str:
    return _now_tw().strftime("%Y-%m-%d %H:%M:%S %z")

def _safe_write_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def _requests_get(url: str, timeout: int = 30) -> requests.Response:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    # Some TW sites need explicit encoding fix
    if r.encoding is None or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    return r

def _get_json(url: str, timeout: int = 30) -> dict:
    return _requests_get(url, timeout=timeout).json()

def _get_text(url: str, timeout: int = 30) -> str:
    return _requests_get(url, timeout=timeout).text

def _strip(s: Any) -> str:
    return str(s).strip()

def _parse_int(text: Any) -> Optional[int]:
    if text is None:
        return None
    s = str(text).strip()
    if s == "" or s == "-" or s == "--":
        return None
    s = s.replace(",", "")
    m = re.search(r"-?\d+", s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None

def _parse_float(text: Any) -> Optional[float]:
    if text is None:
        return None
    s = str(text).strip()
    if s == "" or s == "-" or s == "--":
        return None
    s = s.replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None

def _fmt_int(n: Optional[int]) -> Optional[str]:
    if n is None:
        return None
    return f"{n:,}"

def _fmt_signed(n: Optional[float], digits: int = 2) -> Optional[str]:
    if n is None:
        return None
    sign = "+" if n > 0 else ""
    if digits == 0:
        return f"{sign}{int(round(n)):,}"
    return f"{sign}{n:.{digits}f}"

def _fmt_signed_pct(n: Optional[float], digits: int = 2) -> Optional[str]:
    if n is None:
        return None
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.{digits}f}%"

def _round_half_away_from_zero(x: float) -> int:
    # -2180.67 -> -2181 ; 2180.2 -> 2180
    if x >= 0:
        return int(x + 0.5)
    return -int(abs(x) + 0.5)

def _ymd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")

def _ymd_compact(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")

def _roc_to_ad(roc_yyy_mm_dd: str) -> Optional[str]:
    # "114/12/30" -> "2025-12-30"
    m = re.match(r"^\s*(\d{2,3})/(\d{1,2})/(\d{1,2})\s*$", roc_yyy_mm_dd)
    if not m:
        return None
    roc_y = int(m.group(1))
    y = roc_y + 1911
    mm = int(m.group(2))
    dd = int(m.group(3))
    return f"{y:04d}-{mm:02d}-{dd:02d}"

def _find_latest_two_trading_days(max_back_days: int = 12) -> Tuple[str, str]:
    """
    用 TWSE T86 是否有資料來找：
      - latest_trading_day (YYYY-MM-DD)
      - prev_trading_day   (YYYY-MM-DD)
    """
    def has_t86(date_compact: str) -> bool:
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999&date={date_compact}"
        try:
            j = _get_json(url, timeout=25)
            data = j.get("data") or []
            return len(data) > 0 and j.get("stat", "").upper() == "OK"
        except Exception:
            return False

    base = _now_tw().date()
    latest: Optional[datetime] = None
    prev: Optional[datetime] = None

    # 找 latest
    for i in range(max_back_days):
        d = datetime(base.year, base.month, base.day, tzinfo=TZ_TW) - timedelta(days=i)
        if has_t86(_ymd_compact(d)):
            latest = d
            break
    if latest is None:
        latest = datetime(base.year, base.month, base.day, tzinfo=TZ_TW)

    # 找 prev（從 latest-1 往回）
    for i in range(1, max_back_days + 2):
        d = latest - timedelta(days=i)
        if has_t86(_ymd_compact(d)):
            prev = d
            break
    if prev is None:
        prev = latest - timedelta(days=1)

    return _ymd(latest), _ymd(prev)


# =====================
# 股票：收盤 / 漲跌 / 漲跌%
# =====================

def _fetch_twse_stock_day_month(ticker: str, any_date_compact: str) -> Optional[dict]:
    """
    STOCK_DAY 一次回一個月，date 只要給該月任意日即可。
    """
    url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={any_date_compact}&stockNo={ticker}"
    try:
        j = _get_json(url, timeout=25)
        if j.get("stat") != "OK":
            return None
        return j
    except Exception:
        return None

def fetch_close_change_pct(ticker: str, latest_day: str) -> Dict[str, Optional[str]]:
    """
    取 latest_day 的收盤、漲跌價差，並用「前一交易日收盤」算漲跌%。
    """
    y, m, d = latest_day.split("-")
    month_any = f"{y}{m}{d}"

    j = _fetch_twse_stock_day_month(ticker, month_any)
    rows: List[List[str]] = (j or {}).get("data") or []
    if not rows:
        return {"close": None, "change": None, "change_pct": None}

    parsed: List[Tuple[str, float, float]] = []
    for r in rows:
        if len(r) < 8:
            continue
        ad = _roc_to_ad(_strip(r[0]))
        close = _parse_float(r[6])
        chg = _parse_float(r[7])
        if ad and close is not None and chg is not None:
            parsed.append((ad, close, chg))

    if not parsed:
        return {"close": None, "change": None, "change_pct": None}

    parsed.sort(key=lambda x: x[0])
    idx = next((i for i, (ad, _, __) in enumerate(parsed) if ad == latest_day), None)
    if idx is None:
        idx = len(parsed) - 1

    ad, close, chg = parsed[idx]

    prev_close: Optional[float] = None
    if idx - 1 >= 0:
        prev_close = parsed[idx - 1][1]
    else:
        dt = datetime(int(y), int(m), 1, tzinfo=TZ_TW) - timedelta(days=1)
        prev_month_any = dt.strftime("%Y%m%d")
        j2 = _fetch_twse_stock_day_month(ticker, prev_month_any)
        rows2: List[List[str]] = (j2 or {}).get("data") or []
        parsed2: List[Tuple[str, float]] = []
        for r in rows2:
            if len(r) < 7:
                continue
            ad2 = _roc_to_ad(_strip(r[0]))
            c2 = _parse_float(r[6])
            if ad2 and c2 is not None:
                parsed2.append((ad2, c2))
        if parsed2:
            parsed2.sort(key=lambda x: x[0])
            prev_close = parsed2[-1][1]

    pct: Optional[float] = None
    if prev_close and prev_close != 0:
        pct = (close - prev_close) / prev_close * 100.0

    close_str = str(int(close)) if abs(close - int(close)) < 1e-9 else f"{close:.2f}".rstrip("0").rstrip(".")
    chg_str = _fmt_signed(chg, digits=2).rstrip("0").rstrip(".") if chg is not None else None
    pct_str = _fmt_signed_pct(pct, digits=2) if pct is not None else None

    return {
        "close": close_str,
        "change": chg_str,
        "change_pct": pct_str,
    }


# =====================
# 外資買賣超（張）
# =====================

def _fetch_t86_one_day(date_compact: str) -> Optional[List[List[Any]]]:
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999&date={date_compact}"
    try:
        j = _get_json(url, timeout=25)
        if j.get("stat") != "OK":
            return None
        return j.get("data") or []
    except Exception:
        return None

def fetch_foreign_net_lots(ticker: str, latest_day: str, prev_day: str) -> Dict[str, Optional[str]]:
    """
    外資買賣超(張)：
      - D0: latest_day
      - D1: prev_day
    """
    def pick(date_ymd: str) -> Optional[int]:
        data = _fetch_t86_one_day(date_ymd.replace("-", ""))
        if not data:
            return None
        for row in data:
            if not row:
                continue
            code = _strip(row[0])
            if code == ticker:
                net_shares = _parse_int(row[4])  # 股數
                if net_shares is None:
                    return None
                return _round_half_away_from_zero(net_shares / 1000.0)  # 張
        return None

    d0 = pick(latest_day)
    d1 = pick(prev_day)
    return {"D0": _fmt_int(d0), "D1": _fmt_int(d1)}


# =====================
# 富邦：ZGB / ZGK_D
# =====================

def _fetch_html(url: str, timeout: int = 35) -> str:
    """
    先用 requests；若被擋（或抓到的 HTML 沒有 table），再用 Playwright（若可用）。
    """
    try:
        html = _get_text(url, timeout=timeout)
        if "<table" in html.lower():
            return html
    except Exception:
        html = ""

    if sync_playwright is None:
        if html:
            return html
        raise RuntimeError("requests failed and playwright not available")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1800)
        html2 = page.content()
        browser.close()
        return html2

def _table_rows_by_headers(soup: BeautifulSoup, headers_must_contain: List[str]) -> Optional[List[List[str]]]:
    """
    找到一張 table：其 header row（th/td）包含 headers_must_contain 的所有關鍵字。
    回傳每一列的 cell 文字（已 strip）。
    """
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue

        header_cells = [c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])]
        header_join = " ".join(header_cells)
        if all(h in header_join for h in headers_must_contain):
            rows: List[List[str]] = []
            for tr in trs:
                cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in tr.find_all(["th", "td"])]
                if any(cells):
                    rows.append(cells)
            return rows
    return None

def fubon_zgb() -> Dict[str, Any]:
    """
    券商分點進出金額排行（ZGB）—指定 6 家
    目標表格欄位：券商名稱 / 買進金額 / 賣出金額 / 差額
    """
    out: Dict[str, Any] = {"date": None, "rows": [], "error": None}
    try:
        html = _fetch_html(FUBON_ZGB_URL)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)

        m = re.search(r"資料日期[:：]\s*(\d{8})", text)
        if m:
            out["date"] = m.group(1)

        rows = _table_rows_by_headers(soup, ["券商名稱", "買進", "賣出", "差額"])
        if not rows or len(rows) < 2:
            out["error"] = "ZGB 找不到符合欄位的表格（可能是富邦版面變更/被擋）"
            return out

        header = rows[0]
        def col_idx(key: str) -> Optional[int]:
            for i, h in enumerate(header):
                if key in h:
                    return i
            return None

        i_name = col_idx("券商名稱")
        i_buy = col_idx("買進")
        i_sell = col_idx("賣出")
        i_diff = col_idx("差額")

        if None in (i_name, i_buy, i_sell, i_diff):
            out["error"] = "ZGB 表格欄位解析失敗"
            return out

        for r in rows[1:]:
            if len(r) <= max(i_name, i_buy, i_sell, i_diff):  # type: ignore[arg-type]
                continue
            name = r[i_name]  # type: ignore[index]
            buy = _parse_int(r[i_buy])  # type: ignore[index]
            sell = _parse_int(r[i_sell])  # type: ignore[index]
            diff = _parse_int(r[i_diff])  # type: ignore[index]

            if name and (buy is not None or sell is not None or diff is not None):
                out["rows"].append(
                    {"name": name, "buy": _fmt_int(buy), "sell": _fmt_int(sell), "diff": _fmt_int(diff)}
                )

        if not out["rows"]:
            out["error"] = "ZGB 表格解析後沒有資料列"
        return out

    except Exception as e:
        out["error"] = f"ZGB 抓取失敗：{e}"
        return out

def _parse_zgk_d_from_text(text: str) -> Dict[str, Any]:
    """
    fallback：把純文字（每行一格）解析回 buy/sell。
    """
    out: Dict[str, Any] = {"date": None, "buy": [], "sell": [], "error": None}
    m = re.search(r"日期[:：]\s*([0-9]{1,2}/[0-9]{1,2})", text)
    if m:
        out["date"] = m.group(1)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    try:
        i0 = lines.index("名次")
    except ValueError:
        out["error"] = "ZGK_D fallback 找不到 header"
        return out

    cols = lines[i0:]
    if len(cols) < 20:
        out["error"] = "ZGK_D fallback 資料不足"
        return out
    data_cols = cols[10:]  # skip 10 header cells

    def norm_name(s: str):
        m2 = re.match(r"^(\d{4,6})\s*(.+)$", s)
        if m2:
            return m2.group(1), m2.group(2).strip()
        return None, s.strip()

    for i in range(0, len(data_cols) - 9, 10):
        r = data_cols[i:i+10]
        br = _parse_int(r[0]); braw = r[1]; bnet = _parse_int(r[2]); bclose = _parse_float(r[3]); bchg = _parse_float(r[4])
        sr = _parse_int(r[5]); sraw = r[6]; snet = _parse_int(r[7]); sclose = _parse_float(r[8]); schg = _parse_float(r[9])
        bcode, bname = norm_name(braw)
        scode, sname = norm_name(sraw)
        if br is not None and bnet is not None:
            out["buy"].append({"rank": br, "ticker": bcode, "name": bname, "net": _fmt_int(bnet),
                               "close": None if bclose is None else str(bclose), "change": None if bchg is None else _fmt_signed(bchg,2).rstrip("0").rstrip(".")})
        if sr is not None and snet is not None:
            out["sell"].append({"rank": sr, "ticker": scode, "name": sname, "net": _fmt_int(snet),
                                "close": None if sclose is None else str(sclose), "change": None if schg is None else _fmt_signed(schg,2).rstrip("0").rstrip(".")})
    return out

def fubon_zgk_d() -> Dict[str, Any]:
    """
    外資買賣超排行（ZGK_D）
    目標：同一張表左右兩邊（買超 / 賣超）
    """
    out: Dict[str, Any] = {"date": None, "buy": [], "sell": [], "error": None}
    try:
        html = _fetch_html(FUBON_ZGK_D_URL)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)

        m = re.search(r"日期[:：]\s*([0-9]{1,2}/[0-9]{1,2})", text)
        if m:
            out["date"] = m.group(1)

        rows = _table_rows_by_headers(soup, ["名次", "股票名稱", "超張數", "收盤價", "漲跌"])
        if not rows or len(rows) < 2:
            out["error"] = "ZGK_D 找不到符合欄位的表格（可能是富邦版面變更/被擋）"
            return out

        header = rows[0]
        if len(header) < 10:
            return _parse_zgk_d_from_text(text)

        def norm_name(s: str):
            s = s.strip()
            m2 = re.match(r"^(\d{4,6})\s*(.+)$", s)
            if m2:
                return m2.group(1), m2.group(2).strip()
            return None, s

        for r in rows[1:]:
            if len(r) < 10:
                continue

            b_rank = _parse_int(r[0])
            b_name_raw = r[1]
            b_net = _parse_int(r[2])
            b_close = _parse_float(r[3])
            b_chg = _parse_float(r[4])

            b_code, b_name = norm_name(b_name_raw)
            if b_rank is not None and b_net is not None:
                out["buy"].append(
                    {
                        "rank": b_rank,
                        "ticker": b_code,
                        "name": b_name,
                        "net": _fmt_int(b_net),
                        "close": None if b_close is None else (str(int(b_close)) if abs(b_close-int(b_close))<1e-9 else str(b_close)),
                        "change": None if b_chg is None else _fmt_signed(b_chg, digits=2).rstrip("0").rstrip("."),
                    }
                )

            s_rank = _parse_int(r[5])
            s_name_raw = r[6]
            s_net = _parse_int(r[7])
            s_close = _parse_float(r[8])
            s_chg = _parse_float(r[9])

            s_code, s_name = norm_name(s_name_raw)
            if s_rank is not None and s_net is not None:
                out["sell"].append(
                    {
                        "rank": s_rank,
                        "ticker": s_code,
                        "name": s_name,
                        "net": _fmt_int(s_net),
                        "close": None if s_close is None else (str(int(s_close)) if abs(s_close-int(s_close))<1e-9 else str(s_close)),
                        "change": None if s_chg is None else _fmt_signed(s_chg, digits=2).rstrip("0").rstrip("."),
                    }
                )

        if not out["buy"] and not out["sell"]:
            out["error"] = "ZGK_D 解析後沒有資料列"
        return out

    except Exception as e:
        out["error"] = f"ZGK_D 抓取失敗：{e}"
        return out


# =====================
# TAIFEX：大額交易人（前五大/前十大）
# =====================

def _parse_taifex_tables(html: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"date": None, "by_ticker": {}, "error": None}
    m = re.search(r"查詢日期[^0-9]*(\d{4}/\d{2}/\d{2})", html)
    if not m:
        m = re.search(r"(\d{4}/\d{2}/\d{2})", html)
    if m:
        out["date"] = m.group(1)

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        out["error"] = "TAIFEX 頁面找不到表格"
        return out

    def is_all_contract(cells: List[str]) -> bool:
        joined = " ".join(cells)
        return ("所有" in joined and "契約" in joined) or ("所有契約" in joined)

    def pick_int_at(idx: int, cells: List[str]) -> Optional[int]:
        if idx >= len(cells):
            return None
        s = cells[idx]
        m2 = re.search(r"-?[\d,]+", s)
        if not m2:
            return None
        return int(m2.group(0).replace(",", ""))

    for table in tables:
        for tr in table.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tds]
            if len(cells) < 8:
                continue

            prod = cells[0]
            if "期貨" not in prod:
                continue
            if not is_all_contract(cells):
                continue

            for ticker, kw in STOCK_FUTURES_KEYWORD_BY_TICKER.items():
                if kw in prod:
                    top5_long = pick_int_at(3, cells)
                    top5_short = pick_int_at(5, cells)
                    top10_long = pick_int_at(7, cells)
                    top10_short = pick_int_at(9, cells)
                    oi = pick_int_at(11, cells)

                    if oi is None:
                        ints = [pick_int_at(i, cells) for i in range(len(cells))]
                        ints2 = [x for x in ints if x is not None]
                        if ints2:
                            oi = ints2[-1]

                    out["by_ticker"][ticker] = {
                        "product": prod,
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

def fetch_taifex_large_trader_stock_futures() -> Dict[str, Any]:
    """
    先 GET；若頁面是表單查詢型，會再嘗試「照原表單送 POST」抓回結果。
    """
    out: Dict[str, Any] = {"date": None, "by_ticker": {}, "error": None}
    try:
        html = _get_text(TAIFEX_LARGE_TRADER_URL, timeout=35)
        parsed = _parse_taifex_tables(html)
        if parsed.get("by_ticker"):
            return parsed

        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form")
        if not form:
            return parsed

        payload: Dict[str, str] = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            payload[name] = inp.get("value", "")
        if "queryDate" in payload and not payload["queryDate"]:
            payload["queryDate"] = _now_tw().strftime("%Y/%m/%d")

        post = requests.post(
            TAIFEX_LARGE_TRADER_URL,
            data=payload,
            timeout=35,
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"},
        )
        post.raise_for_status()
        post.encoding = post.apparent_encoding or "utf-8"
        parsed2 = _parse_taifex_tables(post.text)
        return parsed2 if parsed2.get("by_ticker") else parsed

    except Exception as e:
        out["error"] = f"TAIFEX 抓取失敗：{e}"
        return out


# =====================
# 主程式
# =====================

def main():
    latest_trading_day, prev_trading_day = _find_latest_two_trading_days()

    stocks_out: Dict[str, Any] = {}
    for s in STOCKS:
        ticker = s["ticker"]
        name = s["name"]

        price = fetch_close_change_pct(ticker, latest_trading_day)
        foreign = fetch_foreign_net_lots(ticker, latest_trading_day, prev_trading_day)

        stocks_out[ticker] = {
            "ticker": ticker,
            "name": name,
            "price": price,
            "foreign_net_shares": foreign,  # 這裡已是「張」
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

