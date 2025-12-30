# -*- coding: utf-8 -*-
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

TZ_TW = timezone(timedelta(hours=8))

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(ROOT_DIR, "docs")
DATA_JSON_PATH = os.path.join(DOCS_DIR, "data.json")

STOCKS = [
    {"ticker": "2330", "name": "台積電"},
    {"ticker": "2317", "name": "鴻海"},
    {"ticker": "3231", "name": "緯創"},
    {"ticker": "2382", "name": "廣達"},
]

TAIFEX_LARGE_TRADER_URL = "https://www.taifex.com.tw/cht/3/largeTraderFutQry"
STOCK_FUTURES_KEYWORD_BY_TICKER = {
    "2330": "台積電期貨",
    "2317": "鴻海期貨",
    "3231": "緯創期貨",
    "2382": "廣達期貨",
}

FUBON_ZGB_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm"
FUBON_ZGK_D_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk/zgk_d.djhtm"


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
    if r.encoding is None or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    return r


def _get_json(url: str, timeout: int = 30) -> dict:
    return _requests_get(url, timeout=timeout).json()


def _get_text(url: str, timeout: int = 30) -> str:
    return _requests_get(url, timeout=timeout).text


def _strip(x: Any) -> str:
    return str(x).strip()


def _parse_int(text: Any) -> Optional[int]:
    if text is None:
        return None
    s = str(text).strip()
    if s in ("", "-", "--"):
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
    if s in ("", "-", "--"):
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
    s = f"{sign}{n:.{digits}f}"
    return s.rstrip("0").rstrip(".")


def _fmt_signed_pct(n: Optional[float], digits: int = 2) -> Optional[str]:
    if n is None:
        return None
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.{digits}f}%"


def _round_half_away_from_zero(x: float) -> int:
    if x >= 0:
        return int(x + 0.5)
    return -int(abs(x) + 0.5)


def _ymd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _ymd_compact(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _roc_to_ad(roc_yyy_mm_dd: str) -> Optional[str]:
    m = re.match(r"^\s*(\d{2,3})/(\d{1,2})/(\d{1,2})\s*$", roc_yyy_mm_dd)
    if not m:
        return None
    roc_y = int(m.group(1))
    y = roc_y + 1911
    mm = int(m.group(2))
    dd = int(m.group(3))
    return f"{y:04d}-{mm:02d}-{dd:02d}"


def _find_latest_two_trading_days(max_back_days: int = 12) -> Tuple[str, str]:
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

    for i in range(max_back_days):
        d = datetime(base.year, base.month, base.day, tzinfo=TZ_TW) - timedelta(days=i)
        if has_t86(_ymd_compact(d)):
            latest = d
            break
    if latest is None:
        latest = datetime(base.year, base.month, base.day, tzinfo=TZ_TW)

    for i in range(1, max_back_days + 2):
        d = latest - timedelta(days=i)
        if has_t86(_ymd_compact(d)):
            prev = d
            break
    if prev is None:
        prev = latest - timedelta(days=1)

    return _ymd(latest), _ymd(prev)


# ----------------- 股價：close/change/pct -----------------
def _fetch_twse_stock_day_month(ticker: str, any_date_compact: str) -> Optional[dict]:
    url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={any_date_compact}&stockNo={ticker}"
    try:
        j = _get_json(url, timeout=25)
        if j.get("stat") != "OK":
            return None
        return j
    except Exception:
        return None


def fetch_close_change_pct(ticker: str, latest_day: str) -> Dict[str, Optional[str]]:
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
        closes: List[float] = []
        for r in rows2:
            if len(r) < 7:
                continue
            c2 = _parse_float(r[6])
            if c2 is not None:
                closes.append(c2)
        if closes:
            prev_close = closes[-1]

    pct: Optional[float] = None
    if prev_close and prev_close != 0:
        pct = (close - prev_close) / prev_close * 100.0

    close_str = str(int(close)) if abs(close - int(close)) < 1e-9 else f"{close:.2f}".rstrip("0").rstrip(".")
    return {"close": close_str, "change": _fmt_signed(chg, 2), "change_pct": _fmt_signed_pct(pct, 2) if pct is not None else None}


# ----------------- 外資 T86：D0/D1 (張) -----------------
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
    def pick(date_ymd: str) -> Optional[int]:
        data = _fetch_t86_one_day(date_ymd.replace("-", ""))
        if not data:
            return None
        for row in data:
            if row and _strip(row[0]) == ticker:
                net_shares = _parse_int(row[4])
                if net_shares is None:
                    return None
                return _round_half_away_from_zero(net_shares / 1000.0)
        return None

    return {"D0": _fmt_int(pick(latest_day)), "D1": _fmt_int(pick(prev_day))}


# ----------------- 富邦：ZGB / ZGK_D（修正版） -----------------
def _fetch_html(url: str, timeout: int = 40) -> str:
    try:
        return _get_text(url, timeout=timeout)
    except Exception:
        return ""


def _has_zh(s: str) -> bool:
    return re.search(r"[\u4e00-\u9fff]", s) is not None


def fubon_zgb() -> Dict[str, Any]:
    out: Dict[str, Any] = {"date": None, "rows": [], "error": None}
    html = _fetch_html(FUBON_ZGB_URL)
    if not html:
        out["error"] = "ZGB 抓不到頁面（可能被擋或暫時維護）"
        return out

    m = re.search(r"資料日期[:：]\s*(\d{8})", html)
    if m:
        out["date"] = m.group(1)

    soup = BeautifulSoup(html, "html.parser")

    candidates = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tr.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            name = cells[0]
            buy = _parse_int(cells[1])
            sell = _parse_int(cells[2])
            diff = _parse_int(cells[3])
            # ✅ 避免你截圖那種「整頁文字被當券商」：名稱要短 + 有中文 + 數字欄要像金額
            if not name or len(name) > 20 or not _has_zh(name):
                continue
            if buy is None or sell is None or diff is None:
                continue
            candidates.append({"name": name, "buy": _fmt_int(buy), "sell": _fmt_int(sell), "diff": _fmt_int(diff)})

    # 去重 + 取前 6
    seen = set()
    rows = []
    for r in candidates:
        key = (r["name"], r["buy"], r["sell"], r["diff"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)
        if len(rows) >= 6:
            break

    if not rows:
        out["error"] = "ZGB 找不到可用表格列（可能富邦版面變了）"
    else:
        out["rows"] = rows
    return out


def fubon_zgk_d() -> Dict[str, Any]:
    out: Dict[str, Any] = {"date": None, "buy": [], "sell": [], "error": None}
    html = _fetch_html(FUBON_ZGK_D_URL)
    if not html:
        out["error"] = "ZGK_D 抓不到頁面（可能被擋或暫時維護）"
        return out

    m = re.search(r"日期[:：]\s*([0-9]{1,2}/[0-9]{1,2})", html)
    if m:
        out["date"] = m.group(1)

    soup = BeautifulSoup(html, "html.parser")

    buy_list = []
    sell_list = []

    # ✅ 直接找「一列 10 欄」的結構：買超5欄 + 賣超5欄
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tr.find_all(["td", "th"])]
            if len(cells) != 10:
                continue

            b_rank = _parse_int(cells[0])
            b_name = cells[1]
            b_net = _parse_int(cells[2])
            b_close = _parse_float(cells[3])
            b_chg = _parse_float(cells[4])

            s_rank = _parse_int(cells[5])
            s_name = cells[6]
            s_net = _parse_int(cells[7])
            s_close = _parse_float(cells[8])
            s_chg = _parse_float(cells[9])

            if b_rank is None or b_net is None or not b_name:
                pass
            else:
                m2 = re.match(r"^(\d{4,6})\s*(.+)$", b_name)
                b_code = m2.group(1) if m2 else None
                b_nm = m2.group(2).strip() if m2 else b_name
                buy_list.append({
                    "rank": b_rank,
                    "ticker": b_code,
                    "name": b_nm,
                    "net": _fmt_int(b_net),
                    "close": None if b_close is None else (str(int(b_close)) if abs(b_close-int(b_close))<1e-9 else str(b_close)),
                    "change": _fmt_signed(b_chg, 2) if b_chg is not None else None
                })

            if s_rank is None or s_net is None or not s_name:
                pass
            else:
                m3 = re.match(r"^(\d{4,6})\s*(.+)$", s_name)
                s_code = m3.group(1) if m3 else None
                s_nm = m3.group(2).strip() if m3 else s_name
                sell_list.append({
                    "rank": s_rank,
                    "ticker": s_code,
                    "name": s_nm,
                    "net": _fmt_int(s_net),
                    "close": None if s_close is None else (str(int(s_close)) if abs(s_close-int(s_close))<1e-9 else str(s_close)),
                    "change": _fmt_signed(s_chg, 2) if s_chg is not None else None
                })

    if not buy_list and not sell_list:
        out["error"] = "ZGK_D 找不到 10 欄結構表格（可能富邦版面變了）"
    else:
        out["buy"] = buy_list[:50]
        out["sell"] = sell_list[:50]
    return out


# ----------------- TAIFEX：用下拉 option value POST 查詢（修正版） -----------------
def _extract_ints(s: str) -> List[int]:
    return [int(x.replace(",", "")) for x in re.findall(r"-?[\d,]+", s)]


def _parse_taifex_one(html: str, keyword: str) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return None

    # 找「包含 keyword 且包含 所有契約」的那一列
    for table in tables:
        for tr in table.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tr.find_all(["td", "th"])]
            joined = " ".join(cells)
            if keyword not in joined:
                continue
            if "所有契約" not in joined and not ("所有" in joined and "契約" in joined):
                continue

            nums = _extract_ints(joined)
            # 常見會至少有 5 個數字：前五多/空、前十多/空、未平倉
            if len(nums) < 5:
                continue

            top5_long, top5_short, top10_long, top10_short = nums[0], nums[1], nums[2], nums[3]
            open_interest = nums[-1]  # 最後一個通常是未平倉

            return {
                "product": keyword,
                "top5": {"long": top5_long, "short": top5_short, "net": top5_long - top5_short},
                "top10": {"long": top10_long, "short": top10_short, "net": top10_long - top10_short},
                "open_interest": open_interest,
            }
    return None


def fetch_taifex_large_trader_stock_futures() -> Dict[str, Any]:
    out: Dict[str, Any] = {"date": None, "by_ticker": {}, "error": None}

    try:
        s = requests.Session()
        r = s.get(TAIFEX_LARGE_TRADER_URL, timeout=35, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        base_html = r.text

        # 抓日期（不一定有）
        m = re.search(r"(\d{4}/\d{2}/\d{2})", base_html)
        if m:
            out["date"] = m.group(1)

        soup = BeautifulSoup(base_html, "html.parser")
        form = soup.find("form")
        if not form:
            out["error"] = "TAIFEX 找不到查詢表單"
            return out

        # 收集 hidden input
        payload: Dict[str, str] = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            payload[name] = inp.get("value", "")

        # 找「商品」那個 select：看誰的 option 裡面有 台積電期貨/鴻海期貨...
        commodity_select_name = None
        commodity_value_by_ticker: Dict[str, str] = {}

        for sel in form.find_all("select"):
            sel_name = sel.get("name")
            if not sel_name:
                continue
            options = sel.find_all("option")
            texts = [opt.get_text(" ", strip=True) for opt in options]

            hit = 0
            for tkr, kw in STOCK_FUTURES_KEYWORD_BY_TICKER.items():
                for opt in options:
                    txt = opt.get_text(" ", strip=True)
                    if kw in txt:
                        commodity_value_by_ticker[tkr] = opt.get("value", "")
                        hit += 1
                        break
            if hit >= 2:  # 命中至少 2 檔就當它是商品 select
                commodity_select_name = sel_name
                break

        if not commodity_select_name or len(commodity_value_by_ticker) < 2:
            # 退而求其次：直接 parse base_html（有時候頁面已經含資料）
            for tkr, kw in STOCK_FUTURES_KEYWORD_BY_TICKER.items():
                got = _parse_taifex_one(base_html, kw)
                if got:
                    out["by_ticker"][tkr] = got
            if not out["by_ticker"]:
                out["error"] = "TAIFEX 無法解析商品下拉選單（網站版面可能變更）"
            return out

        # 送查詢：逐檔 POST
        query_date = _now_tw().strftime("%Y/%m/%d")
        # 常見欄位名：queryDate
        if "queryDate" in payload:
            payload["queryDate"] = query_date

        # 也可能有「所有契約」的選單，若有就強制選到「所有契約」
        for sel in form.find_all("select"):
            sel_name = sel.get("name")
            if not sel_name or sel_name == commodity_select_name:
                continue
            # 找 option 文字包含「所有契約」
            for opt in sel.find_all("option"):
                if "所有契約" in opt.get_text(" ", strip=True):
                    payload[sel_name] = opt.get("value", "")
                    break

        for tkr, kw in STOCK_FUTURES_KEYWORD_BY_TICKER.items():
            if tkr not in commodity_value_by_ticker:
                continue
            payload[commodity_select_name] = commodity_value_by_ticker[tkr]

            pr = s.post(
                TAIFEX_LARGE_TRADER_URL,
                data=payload,
                timeout=35,
                headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"},
            )
            pr.raise_for_status()
            pr.encoding = pr.apparent_encoding or "utf-8"
            html = pr.text

            m2 = re.search(r"(\d{4}/\d{2}/\d{2})", html)
            if m2:
                out["date"] = m2.group(1)

            got = _parse_taifex_one(html, kw)
            if got:
                out["by_ticker"][tkr] = got

            time.sleep(0.2)

        if not out["by_ticker"]:
            out["error"] = "TAIFEX 查詢成功但解析不到『所有契約』彙總列（可能網站表格欄位改版）"
        return out

    except Exception as e:
        out["error"] = f"TAIFEX 抓取失敗：{e}"
        return out


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
            "foreign_net_shares": foreign,
            "news": {"conference": [], "revenue": [], "material": [], "capacity": [], "export": []},
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


