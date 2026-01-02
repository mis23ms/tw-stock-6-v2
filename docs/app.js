/* 盤後一頁式戰報 - 前端
 * - 固定 4 檔：讀 data.json（由 GitHub Actions 產）
 * - 自選 2 檔：localStorage；前端即時抓 TWSE（同樣算 close/change/pct + 外資(張)）
 * - 顏色標註：只針對「漲跌」「外資」
 */

const DATA_URL = "./data.json";

const FIXED = ["2330", "2317", "3231", "2382"];
const LS_KEY_1 = "twstock_custom_1";
const LS_KEY_2 = "twstock_custom_2";

/** 你原本固定 4 檔的股期才顯示 TAIFEX */
const TAIFEX_SUPPORTED = new Set(FIXED);

function $(sel) { return document.querySelector(sel); }
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function fmtNum(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  return x.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
function fmtInt(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  return Math.trunc(x).toLocaleString("en-US");
}
function fmtSigned(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  const s = x > 0 ? "+" : "";
  return s + fmtNum(x, digits);
}

function badgeForChange(chg) {
  const x = Number(chg);
  if (!Number.isFinite(x) || x === 0) return { cls: "badge flat", label: "—" };
  // 漲跌：越深越強（用變動幅度粗分）
  const abs = Math.abs(x);
  const lv = abs >= 5 ? "lv3" : abs >= 1 ? "lv2" : "lv1";
  return { cls: `badge ${x > 0 ? "pos" : "neg"} ${lv}`, label: fmtSigned(x, 2) };
}

function badgeForForeignLots(netLots) {
  const x = Number(netLots);
  if (!Number.isFinite(x) || Math.abs(x) < 800) return null; // <800 不標
  const lv = Math.abs(x) >= 3000 ? "lv3" : "lv2"; // 800~2999 / >=3000
  const cls = `badge ${x > 0 ? "pos" : "neg"} ${lv}`;
  const label = `${x > 0 ? "買超" : "賣超"} ${fmtNum(Math.abs(x), 0)} 張`;
  return { cls, label };
}

function stockTitle(name, ticker) {
  if (name && name.trim()) return name.trim();
  return "—";
}

/* ---------------------------
 * 自選：前端抓 TWSE
 * ---------------------------
 * close/change/pct：STOCK_DAY（用 data.json 的 latest_trading_day_ymd 當月份）
 * foreign：T86（同一個交易日）
 */

async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}

function ymdToRoc(ymd) {
  const y = parseInt(ymd.slice(0, 4), 10) - 1911;
  const m = ymd.slice(4, 6);
  const d = ymd.slice(6, 8);
  return `${y}/${m}/${d}`;
}

async function fetchTwseStockDay(ymd, ticker) {
  const url = `https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=${ymd}&stockNo=${ticker}`;
  const j = await fetchJson(url);
  if ((j.stat || "").toUpperCase() !== "OK") throw new Error(`STOCK_DAY stat=${j.stat}`);

  const roc = ymdToRoc(ymd);
  const data = j.data || [];
  let row = data.find(r => (r && String(r[0]).trim() === roc));
  if (!row && data.length) row = data[data.length - 1];
  if (!row) throw new Error("STOCK_DAY empty data");

  const close = Number(String(row[6]).replace(/,/g, ""));
  const change = Number(String(row[7]).replace(/,/g, ""));
  const prevClose = close - change;
  const pct = prevClose ? (change / prevClose * 100.0) : 0;

  // title 常見： "114年12月2330 台積電各日成交資訊"
  const title = j.title || "";
  let name = "";
  const m = title.match(new RegExp(`${ticker}\\s*([^\\s]+)`));
  if (m && m[1]) name = m[1].trim();

  return { ticker, name, close, change, pct };
}

async function fetchTwseT86Map(ymd) {
  const url = `https://www.twse.com.tw/fund/T86?response=json&date=${ymd}&selectType=ALL`;
  const j = await fetchJson(url);
  if ((j.stat || "").toUpperCase() !== "OK") throw new Error(`T86 stat=${j.stat}`);

  const fields = j.fields || [];
  const data = j.data || [];

  const idx = (needleList) => {
    for (const nd of needleList) {
      const i = fields.findIndex(f => String(f).includes(nd));
      if (i >= 0) return i;
    }
    return -1;
  };

  const iCode = idx(["證券代號"]);
  const iBuy  = idx(["外陸資買進股數", "外資買進股數"]);
  const iSell = idx(["外陸資賣出股數", "外資賣出股數"]);
  const iNet  = idx(["外陸資買賣超股數", "外資買賣超股數"]);

  if (iCode < 0 || iBuy < 0 || iSell < 0) throw new Error("T86 fields not found");

  const mp = new Map();
  for (const row of data) {
    const code = String(row[iCode]).trim();
    const buy = Number(String(row[iBuy]).replace(/,/g, "")) || 0;
    const sell = Number(String(row[iSell]).replace(/,/g, "")) || 0;
    const net = (iNet >= 0 ? (Number(String(row[iNet]).replace(/,/g, "")) || 0) : (buy - sell));
    mp.set(code, {
      buy_shares: buy,
      sell_shares: sell,
      net_shares: net,
      net_lots: net / 1000.0,
    });
  }
  return mp;
}

/* ---------------------------
 * UI render
 * --------------------------- */

function renderHeader(data) {
  $("#updatedAt").textContent = data?.generated_at || "—";
  $("#latestDay").textContent = data?.latest_trading_day || "—";
  $("#prevDay").textContent = data?.prev_trading_day || "—";
}

function renderCustomInputs() {
  const v1 = localStorage.getItem(LS_KEY_1) || "";
  const v2 = localStorage.getItem(LS_KEY_2) || "";
  $("#custom1").value = v1;
  $("#custom2").value = v2;

  $("#applyCustom").onclick = () => {
    localStorage.setItem(LS_KEY_1, ($("#custom1").value || "").trim());
    localStorage.setItem(LS_KEY_2, ($("#custom2").value || "").trim());
    location.reload();
  };
  $("#clearCustom").onclick = () => {
    localStorage.removeItem(LS_KEY_1);
    localStorage.removeItem(LS_KEY_2);
    location.reload();
  };
}

function stockCardFromData(stock, taifexInfo) {
  const card = el("div", "card");
  const top = el("div", "row");
  const left = el("div");

  const pill = el("span", "pill", stock.ticker);
  left.appendChild(pill);

  const h = el("h3", null, stockTitle(stock.name, stock.ticker));
  left.appendChild(h);

  // close
  const kv = el("div", "kv");
  kv.appendChild(el("div", null, `收盤 ${fmtNum(stock.close, 2)}`));

  // change + pct
  const chgBadge = badgeForChange(stock.change);
  const chgWrap = el("div");
  const chgP = el("span", chgBadge.cls, chgBadge.label);
  chgWrap.appendChild(chgP);
  chgWrap.appendChild(el("span", "muted", ` ${fmtSigned(stock.pct, 2)}%`));
  kv.appendChild(chgWrap);

  left.appendChild(kv);
  top.appendChild(left);

  // right tabs (你原本的按鈕群)
  const right = el("div", "tabs");
  ["法說", "營收", "重大訊息", "產能", "美國出口管制"].forEach(t => {
    const b = el("button", "tab", t);
    b.type = "button";
    right.appendChild(b);
  });
  top.appendChild(right);

  card.appendChild(top);

  // 外資
  const foreign = stock.foreign || {};
  const foreignRow = el("div", "row");
  foreignRow.appendChild(el("div", null, "外資買賣超(張)"));

  if (foreign.error) {
    foreignRow.appendChild(el("div", "muted", foreign.error));
  } else {
    const lots = Number(foreign.net_lots);
    const pillToday = el("span", "pill", `${stock.ticker}-${fmtNum(lots, 0)}`);
    // 只針對外資做顏色
    if (lots > 0) pillToday.classList.add("pill-pos");
    else if (lots < 0) pillToday.classList.add("pill-neg");
    foreignRow.appendChild(pillToday);

    const b = badgeForForeignLots(lots);
    if (b) {
      const bb = el("span", b.cls, b.label);
      foreignRow.appendChild(bb);
    }
  }
  card.appendChild(foreignRow);

  // TAIFEX（只對固定 4 檔）
  if (TAIFEX_SUPPORTED.has(stock.ticker)) {
    const tfBox = el("div", "row");
    const title = el("div", null, "期貨未平倉（大額交易人）");
    tfBox.appendChild(title);

    const body = el("div");
    if (!taifexInfo || taifexInfo.error) {
      body.appendChild(el("div", "muted", taifexInfo?.error || "目前抓不到資料"));
    } else {
      const top5 = taifexInfo.top5 || {};
      const top10 = taifexInfo.top10 || {};
      body.appendChild(el("div", "muted", `所有契約｜前五大：多 ${fmtInt(top5.long)} / 空 ${fmtInt(top5.short)} / 淨 ${fmtInt(top5.net)}`));
      body.appendChild(el("div", "muted", `所有契約｜前十大：多 ${fmtInt(top10.long)} / 空 ${fmtInt(top10.short)} / 淨 ${fmtInt(top10.net)}`));
      body.appendChild(el("div", "muted", `未平倉量：${fmtInt(taifexInfo.oi)}`));
    }
    tfBox.appendChild(body);
    card.appendChild(tfBox);
  }

  return card;
}

function renderStocks(data, customStocks) {
  const grid = $("#stockGrid");
  grid.innerHTML = "";

  // 固定 4 檔
  for (const tk of FIXED) {
    const s = data.stocks?.[tk];
    if (!s) continue;
    grid.appendChild(stockCardFromData(s, data.taifex?.[tk]));
  }

  // 自選 2 檔（放在固定 4 檔後面）
  for (const s of customStocks) {
    const card = stockCardFromData(s, null);
    // 自選標記（讓你一眼看出來）
    const tag = card.querySelector(".pill");
    if (tag) tag.textContent = s.ticker + "  自選";
    grid.appendChild(card);
  }
}

function renderZGB(data) {
  const box = $("#zgbBox");
  box.innerHTML = "";

  const zgb = data.fubon_zgb || {};
  if (zgb.error) {
    box.appendChild(el("div", "card", zgb.error));
    return;
  }
  const rows = zgb.rows || [];
  if (!rows.length) {
    box.appendChild(el("div", "card", "ZGB 無資料"));
    return;
  }

  const card = el("div", "card");
  card.appendChild(el("div", null, "券商分點進出金額排行（ZGB）—指定 6 家"));

  const table = el("table");
  const thead = el("thead");
  const trh = el("tr");
  ["券商", "買進金額", "賣出金額", "差額"].forEach(h => trh.appendChild(el("th", null, h)));
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el("tbody");
  for (const r of rows) {
    const tr = el("tr");
    tr.appendChild(el("td", null, r.broker));
    tr.appendChild(el("td", null, fmtInt(r.buy)));
    tr.appendChild(el("td", null, fmtInt(r.sell)));
    tr.appendChild(el("td", null, fmtInt(r.diff)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  card.appendChild(table);
  box.appendChild(card);
}

function renderZGK(data) {
  const box = $("#zgkBox");
  box.innerHTML = "";

  const zgk = data.fubon_zgk_d || {};
  if (zgk.error) {
    box.appendChild(el("div", "card", zgk.error));
    return;
  }

  const buy = zgk.buy || [];
  const sell = zgk.sell || [];

  const card = el("div", "card");
  const title = el("div", null, `外資買賣超排行（ZGK_D）${zgk.date ? `（日期：${zgk.date}）` : ""}`);
  card.appendChild(title);

  const table = el("table");
  const thead = el("thead");
  const trh = el("tr");
  ["#", "股票", "超張數", "收盤", "漲跌", "#", "股票", "超張數", "收盤", "漲跌"].forEach(h => trh.appendChild(el("th", null, h)));
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el("tbody");
  const n = Math.max(buy.length, sell.length);
  for (let i = 0; i < n; i++) {
    const b = buy[i];
    const s = sell[i];
    const tr = el("tr");

    if (b) {
      tr.appendChild(el("td", null, String(b.rank)));
      tr.appendChild(el("td", null, b.name));
      tr.appendChild(el("td", null, fmtNum(b.lots, 0)));
      tr.appendChild(el("td", null, fmtNum(b.close, 2)));

      const bd = badgeForChange(b.chg);
      const td = el("td");
      td.appendChild(el("span", bd.cls, bd.label));
      tr.appendChild(td);
    } else {
      for (let k = 0; k < 5; k++) tr.appendChild(el("td", null, ""));
    }

    if (s) {
      tr.appendChild(el("td", null, String(s.rank)));
      tr.appendChild(el("td", null, s.name));
      tr.appendChild(el("td", null, fmtNum(s.lots, 0)));
      tr.appendChild(el("td", null, fmtNum(s.close, 2)));

      const bd = badgeForChange(s.chg);
      const td = el("td");
      td.appendChild(el("span", bd.cls, bd.label));
      tr.appendChild(td);
    } else {
      for (let k = 0; k < 5; k++) tr.appendChild(el("td", null, ""));
    }

    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  card.appendChild(table);
  box.appendChild(card);
}

/* ---------------------------
 * 穩定強化版 Boot 邏輯
 * --------------------------- */
async function main() {
  renderCustomInputs();

  // 1. 優先讀取 data.json
  const data = await fetchJson(DATA_URL);
  renderHeader(data);

  // 2. 【核心修正】先渲染固定 4 檔，確保畫面第一時間有數據
  renderStocks(data, []); 

  // 3. 異步處理自選股，不讓它卡死主畫面
  const c1 = (localStorage.getItem(LS_KEY_1) || "").trim();
  const c2 = (localStorage.getItem(LS_KEY_2) || "").trim();
  const customTickers = [c1, c2].filter(x => x);

  if (customTickers.length > 0) {
    const custom = [];
    const latestYmd = data.latest_trading_day_ymd;
    
    // 建立一個 Map 預抓 T86 數據
    let t86Map = null;
    try { t86Map = await fetchTwseT86Map(latestYmd); } catch (e) { t86Map = null; }

    for (const tk of customTickers) {
      try {
        const s = await fetchTwseStockDay(latestYmd, tk);
        const f = t86Map?.get(tk);
        s.foreign = f ? f : { error: "無外資資料" };
        custom.push(s);
      } catch (e) {
        custom.push({ ticker: tk, name: "載入失敗", close: null, foreign: { error: "抓取失敗" } });
      }
    }
    // 自選股抓完後，更新畫面
    renderStocks(data, custom);
  }

  // 4. 最後畫排行榜
  renderZGB(data);
  renderZGK(data);
}

  const custom = [];
  const c1 = (localStorage.getItem(LS_KEY_1) || "").trim();
  const c2 = (localStorage.getItem(LS_KEY_2) || "").trim();
  const customTickers = [c1, c2].filter(x => x);

  for (const tk of customTickers) {
    try {
      const s = await fetchTwseStockDay(latestYmd, tk);
      const f = t86Map?.get(tk);
      s.foreign = f ? f : { error: (t86Map ? "T86 找不到該代碼" : "T86 取得失敗") };
      custom.push(s);
    } catch (e) {
      custom.push({
        ticker: tk,
        name: "自選",
        close: null,
        change: null,
        pct: null,
        foreign: { error: String(e.message || e) },
      });
    }
  }

  renderStocks(data, custom);
  renderZGB(data);
  renderZGK(data);
}

main().catch(err => {
  console.error(err);
  const root = $("#root");
  if (root) root.innerHTML = `<div class="card">載入失敗：${String(err.message || err)}</div>`;
});
