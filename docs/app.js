// docs/app.js
const DATA_URL = "./data.json";

// 固定：只支援這四檔的 TAIFEX 股票期貨
const FUTURES_SUPPORTED = new Set(["2330", "2317", "3231", "2382"]);

// 自選 2 檔：存在 localStorage（不影響固定 4 檔）
const LS_KEY = "tw-stock-extra-2";

// -------------------- utils --------------------
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toNumber(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).replace(/,/g, "").trim();
  const m = s.match(/-?\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : null;
}

function fmtInt(n) {
  const num = typeof n === "number" ? n : toNumber(n);
  if (num === null || Number.isNaN(num)) return "-";
  return Math.trunc(num).toLocaleString("en-US");
}

function fmtFloat(n, digits = 2) {
  const num = typeof n === "number" ? n : toNumber(n);
  if (num === null || Number.isNaN(num)) return "-";
  return num.toFixed(digits);
}

// 台股習慣：紅=上漲/買超、綠=下跌/賣超
function trendInfo(change, changePct) {
  const c = change ?? 0;
  const p = changePct ?? 0;
  const absP = Math.abs(p || 0);
  const lv = absP >= 3 ? "lv3" : absP >= 1 ? "lv2" : "lv1";
  if (c > 0) return { cls: "pos", lv, icon: "📈" };
  if (c < 0) return { cls: "neg", lv, icon: "📉" };
  return { cls: "flat", lv: "lv1", icon: "➖" };
}

function foreignTag(net) {
  if (net === null || net === undefined) return null;
  const absN = Math.abs(net);
  if (absN < 800) return null; // <800 不標
  if (net >= 3000) return { text: "強買超", cls: "pos", lv: "lv3" };
  if (net >= 800) return { text: "買超", cls: "pos", lv: "lv2" };
  if (net <= -3000) return { text: "強賣超", cls: "neg", lv: "lv3" };
  return { text: "賣超", cls: "neg", lv: "lv2" };
}

// -------------------- load data.json --------------------
async function loadData() {
  const r = await fetch(DATA_URL, { cache: "no-store" });
  if (!r.ok) throw new Error("load data.json failed");
  return r.json();
}

// -------------------- extra tickers (localStorage) --------------------
function readExtraTickers() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return ["", ""];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return ["", ""];
    return [String(arr[0] ?? ""), String(arr[1] ?? "")];
  } catch {
    return ["", ""];
  }
}

function writeExtraTickers(a, b) {
  localStorage.setItem(LS_KEY, JSON.stringify([a, b]));
}

function normTicker(s) {
  const t = String(s ?? "").trim();
  if (!t) return "";
  // 允許 4~6 位（ETF/REIT 也有 4 位；有些市場可能 5~6）
  if (!/^\d{4,6}$/.test(t)) return "";
  return t;
}

// -------------------- client-side fetch for extra tickers --------------------
// 用 TWSE STOCK_DAY（月資料）抓最近兩筆收盤 -> 算 change / pct
async function fetchTwsePrice(ticker) {
  const now = new Date();
  // 用當月 01（TWSE 要 YYYYMMDD）
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const date = `${y}${m}01`;
  const url = `https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&stockNo=${ticker}&date=${date}`;
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error("TWSE 取價失敗");
  const j = await r.json();
  const rows = j?.data || [];
  if (!rows.length) throw new Error("TWSE 無資料");
  // rows: [日期(民國), 成交股數, 成交金額, 開, 高, 低, 收, 漲跌價差, 成交筆數]
  const last = rows[rows.length - 1];
  const prev = rows.length >= 2 ? rows[rows.length - 2] : null;
  const close = toNumber(last?.[6]);
  const prevClose = prev ? toNumber(prev?.[6]) : null;
  const change = prevClose === null || close === null ? null : close - prevClose;
  const changePct = prevClose ? (change / prevClose) * 100 : null;
  return { close, change, change_pct: changePct };
}

// 外資：前端只做「最新日」即可（自選只要求顯示，不要搞到很重）
async function fetchTwseForeignD0(ticker) {
  const url = `https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999&date=&_=1`;
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) return { D0: null };
  const j = await r.json();
  const data = j?.data || [];
  for (const row of data) {
    if (String(row?.[0] ?? "").trim() === String(ticker)) {
      return { D0: row?.[4] ?? null };
    }
  }
  return { D0: null };
}

// -------------------- render: stock card --------------------
function renderStockCard(s, data, { isExtra = false } = {}) {
  const card = document.createElement("div");
  card.className = "card";

  const price = s.price || {};
  const f = s.foreign_net_shares || {};
  const ticker = String(s.ticker || "");
  const name = String(s.name || "");

  const changeVal = toNumber(price.change);
  const changePctVal = toNumber(price.change_pct);
  const trend = trendInfo(changeVal, changePctVal);

  const foreignVal = toNumber(f.D0);
  const foreignTagObj = foreignTag(foreignVal);

  // TAIFEX
  const futAll = data?.taifex_large_trader || {};
  const futDate = futAll.date ? String(futAll.date) : "";
  const futError = futAll.error ? String(futAll.error) : "";
  const fut = futAll.by_ticker ? futAll.by_ticker[ticker] : null;

  let futHtml = "";
  if (FUTURES_SUPPORTED.has(ticker) && !isExtra) {
    if (fut) {
      const t5 = fut.top5 || {};
      const t10 = fut.top10 || {};
      futHtml = `
        <div class="fut">
          <div class="fut-head">
            <small>✅ 期貨未平倉（大額交易人）</small>
            ${futDate ? `<span class="pill pill-mini">資料日 ${escapeHtml(futDate)}</span>` : ""}
          </div>
          <div class="fut-grid">
            <div class="fut-row">
              <span class="pill pill-mini">前五大</span>
              <span class="mono">多 ${fmtInt(t5.long)} / 空 ${fmtInt(t5.short)} / 淨 ${fmtInt(t5.net)}</span>
            </div>
            <div class="fut-row">
              <span class="pill pill-mini">前十大</span>
              <span class="mono">多 ${fmtInt(t10.long)} / 空 ${fmtInt(t10.short)} / 淨 ${fmtInt(t10.net)}</span>
            </div>
            <div class="fut-row">
              <span class="pill pill-mini">未平倉</span>
              <span class="mono">${fmtInt(fut.open_interest)}</span>
            </div>
          </div>
        </div>
      `;
    } else {
      futHtml = `
        <div class="fut">
          <div class="fut-head">
            <small>✅ 期貨未平倉（大額交易人）</small>
            ${futDate ? `<span class="pill pill-mini">資料日 ${escapeHtml(futDate)}</span>` : ""}
          </div>
          <div class="muted">
            目前抓不到資料${futError ? `：${escapeHtml(futError)}` : "（TAIFEX 可能維護或版面變動）"}
          </div>
        </div>
      `;
    }
  } else if (!isExtra) {
    // 固定四檔以外（理論上沒有）
    futHtml = `
      <div class="fut">
        <div class="fut-head"><small>✅ 期貨未平倉（大額交易人）</small></div>
        <div class="muted">此欄位目前只支援：2330/2317/3231/2382</div>
      </div>
    `;
  }

  // 自選：不顯示新聞 tabs（避免變複雜）
  card.innerHTML = `
    <div class="row">
      <div style="flex:1">
        <div class="kv">
          <span class="pill">${escapeHtml(ticker)}</span>
          <strong>${escapeHtml(name || (isExtra ? "自選" : ""))}</strong>
        </div>

        <div style="margin-top:6px">
          <small>收盤</small> <strong>${price.close ?? "-"}</strong>
          <span class="metric" style="margin-left:10px">
            <small>漲跌</small>
            <span class="badge ${trend.cls} ${trend.lv}">${trend.icon} ${price.change ?? "-"}</span>
            <small class="muted">(${price.change_pct ?? "-"})</small>
          </span>
        </div>

        <div style="margin-top:6px">
          <small>外資買賣超(張)</small>
          <div class="kv" style="margin-top:4px">
            <span class="pill ${foreignVal > 0 ? "pill-pos" : foreignVal < 0 ? "pill-neg" : ""}">
              ${escapeHtml(data.latest_trading_day || "")}: ${f.D0 ?? "-"}
            </span>
            ${
              f.D1 !== undefined
                ? `<span class="pill">${escapeHtml(data.prev_trading_day || "")}: ${f.D1 ?? "-"}</span>`
                : ""
            }
            ${
              foreignTagObj
                ? `<span class="badge ${foreignTagObj.cls} ${foreignTagObj.lv}">💰 ${escapeHtml(foreignTagObj.text)}</span>`
                : ""
            }
          </div>
        </div>

        ${futHtml}
      </div>
    </div>
  `;
  return card;
}

// -------------------- render: extra UI --------------------
function renderExtraUI() {
  const wrap = document.querySelector("#extra");
  if (!wrap) return;

  const [a0, b0] = readExtraTickers();

  wrap.innerHTML = `
    <div class="kv" style="gap:10px; align-items:center;">
      <div>
        <small>加股票 1（4碼）</small><br/>
        <input id="ex1" value="${escapeHtml(a0)}" placeholder="例如 2303" style="width:120px;padding:8px;border-radius:10px;border:1px solid #2a3c55;background:#0d1420;color:#cfe0f3;">
      </div>
      <div>
        <small>加股票 2（4碼）</small><br/>
        <input id="ex2" value="${escapeHtml(b0)}" placeholder="例如 0050" style="width:120px;padding:8px;border-radius:10px;border:1px solid #2a3c55;background:#0d1420;color:#cfe0f3;">
      </div>
      <div style="margin-top:18px; display:flex; gap:8px;">
        <button id="apply" class="tab active">套用</button>
        <button id="clear" class="tab">清空</button>
      </div>
    </div>
    <div class="muted" style="margin-top:10px">
      自選股存在 localStorage；不影響固定 4 檔 GitHub Actions 更新。
    </div>
  `;

  wrap.querySelector("#apply")?.addEventListener("click", () => {
    const a = normTicker(wrap.querySelector("#ex1")?.value);
    const b = normTicker(wrap.querySelector("#ex2")?.value);
    writeExtraTickers(a, b);
    location.reload();
  });

  wrap.querySelector("#clear")?.addEventListener("click", () => {
    writeExtraTickers("", "");
    location.reload();
  });
}

// -------------------- parse: ZGB --------------------
// 目標：從 raw 文字中找到「券商名稱/買進金額/賣出金額/差額」那段，且排除「6442光聖」這種股票列
function parseZgb(raw) {
  if (!raw) return { date: null, rows: [], error: "ZGB 無資料" };

  const text = String(raw);
  const mDate = text.match(/資料日期：(\d{8})/);
  const date = mDate ? mDate[1] : null;

  const lines = text
    .split("\n")
    .map((s) => s.trim())
    .filter((s) => s.length);

  const header = ["券商名稱", "買進金額", "賣出金額", "差額"];

  // 找出所有 header 出現的位置
  const idxs = [];
  for (let i = 0; i < lines.length - 4; i++) {
    if (
      lines[i] === header[0] &&
      lines[i + 1] === header[1] &&
      lines[i + 2] === header[2] &&
      lines[i + 3] === header[3]
    ) {
      idxs.push(i);
    }
  }

  function isBrokerName(name) {
    // 排除「代號+股票名」那種（以數字開頭）
    return name && !/^\d/.test(name);
  }

  function parseAt(i) {
    const rows = [];
    let j = i + 4;

    // 往下每 4 行一組：name/buy/sell/diff
    while (j + 3 < lines.length) {
      const name = lines[j];
      const buy = lines[j + 1];
      const sell = lines[j + 2];
      const diff = lines[j + 3];

      // buy/sell/diff 必須是數字
      const nb = toNumber(buy);
      const ns = toNumber(sell);
      const nd = toNumber(diff);
      if (nb === null || ns === null || nd === null) break;

      // 避免吃到股票列：用 name 是否以數字開頭判斷
      if (isBrokerName(name)) {
        rows.push({ name, buy: nb, sell: ns, diff: nd });
      }

      j += 4;

      // 夠 6 家就停
      if (rows.length >= 6) break;
    }
    return rows;
  }

  // 可能有多段 header：挑「解析到最多券商」的那段
  let best = [];
  for (const i of idxs) {
    const rows = parseAt(i);
    if (rows.length > best.length) best = rows;
  }

  if (!best.length) {
    return { date, rows: [], error: "ZGB 找不到『券商』段落（可能版面變更）" };
  }

  return { date, rows: best.slice(0, 6), error: null };
}

function renderZgb(data) {
  const box = document.querySelector("#zgb");
  if (!box) return;

  const z = parseZgb(data?.fubon_zgb?.raw);
  if (z.error) {
    box.innerHTML = `<div class="bad">${escapeHtml(z.error)}</div>`;
    return;
  }

  const rows = z.rows || [];
  const dateText = z.date ? `資料日：${z.date}` : "";

  const html = `
    <div class="kv">
      ${dateText ? `<span class="pill">${escapeHtml(dateText)}</span>` : ""}
    </div>
    <table>
      <thead>
        <tr>
          <th>券商</th><th>買進金額</th><th>賣出金額</th><th>差額</th>
        </tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (r) => `
          <tr>
            <td>${escapeHtml(r.name)}</td>
            <td>${fmtInt(r.buy)}</td>
            <td>${fmtInt(r.sell)}</td>
            <td>${fmtInt(r.diff)}</td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table>
  `;
  box.innerHTML = html;
}

// -------------------- parse+render: ZGK_D --------------------
function parseZgkD(raw) {
  if (!raw) return { date: null, rows: [], error: "ZGK_D 無資料" };
  const text = String(raw);

  // 日期通常長這樣：日期：12/30
  const mDate = text.match(/日期：([0-9]{1,2}\/[0-9]{1,2})/);
  const date = mDate ? mDate[1] : null;

  const lines = text
    .split("\n")
    .map((s) => s.trim())
    .filter((s) => s.length);

  // 找到表頭那一列開始的位置（出現一次就好）
  const headIdx = lines.findIndex(
    (s, i) =>
      s === "名次" &&
      lines[i + 1] === "股票名稱" &&
      lines[i + 2] === "超張數" &&
      lines[i + 3] === "收盤價" &&
      lines[i + 4] === "漲跌"
  );
  if (headIdx < 0) return { date, buy: [], sell: [], error: "ZGK_D 找不到表頭" };

  const buy = [];
  const sell = [];

  // 之後每一筆資料是 10 格：rank,name,vol,close,chg, rank2,name2,vol2,close2,chg2
  let j = headIdx + 5;
  while (j + 9 < lines.length) {
    const r1 = lines[j];
    if (!/^\d+$/.test(r1)) break;

    const rowBuy = {
      rank: toNumber(lines[j]),
      name: lines[j + 1],
      vol: toNumber(lines[j + 2]),
      close: toNumber(lines[j + 3]),
      chg: toNumber(lines[j + 4]),
    };

    const r2 = lines[j + 5];
    const rowSell = {
      rank: toNumber(lines[j + 5]),
      name: lines[j + 6],
      vol: toNumber(lines[j + 7]),
      close: toNumber(lines[j + 8]),
      chg: toNumber(lines[j + 9]),
    };

    buy.push(rowBuy);
    if (/^\d+$/.test(r2)) sell.push(rowSell);

    j += 10;

    // 通常 50 筆就夠了
    if (buy.length >= 50) break;
  }

  return { date, buy, sell, error: null };
}

function renderZgkD(data) {
  const box = document.querySelector("#zgk");
  if (!box) return;

  const z = parseZgkD(data?.fubon_zgk_d?.raw);
  if (z.error) {
    box.innerHTML = `<div class="bad">${escapeHtml(z.error)}</div>`;
    return;
  }

  const dateText = z.date ? `日期：${z.date}` : "";

  box.innerHTML = `
    <div class="kv">
      ${dateText ? `<span class="pill">${escapeHtml(dateText)}</span>` : ""}
    </div>
    <table>
      <thead>
        <tr>
          <th colspan="5">買超</th>
          <th colspan="5">賣超</th>
        </tr>
        <tr>
          <th>#</th><th>股票</th><th>超張數</th><th>收盤</th><th>漲跌</th>
          <th>#</th><th>股票</th><th>超張數</th><th>收盤</th><th>漲跌</th>
        </tr>
      </thead>
      <tbody>
        ${Array.from({ length: Math.max(z.buy.length, z.sell.length) })
          .map((_, i) => {
            const b = z.buy[i];
            const s = z.sell[i];
            return `
              <tr>
                <td>${b ? b.rank ?? "" : ""}</td>
                <td>${b ? escapeHtml(b.name) : ""}</td>
                <td>${b ? fmtInt(b.vol) : ""}</td>
                <td>${b ? (b.close ?? "") : ""}</td>
                <td>${b ? (b.chg ?? "") : ""}</td>
                <td>${s ? s.rank ?? "" : ""}</td>
                <td>${s ? escapeHtml(s.name) : ""}</td>
                <td>${s ? fmtInt(s.vol) : ""}</td>
                <td>${s ? (s.close ?? "") : ""}</td>
                <td>${s ? (s.chg ?? "") : ""}</td>
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
}

// -------------------- init --------------------
(async function init() {
  try {
    const data = await loadData();

    // meta
    const meta = document.querySelector("#meta");
    if (meta) {
      meta.textContent = `更新時間：${data.generated_at || "-"} ｜ 最新交易日：${data.latest_trading_day || "-"} ｜ 前一交易日：${
        data.prev_trading_day || "-"
      }`;
    }

    // extra UI
    renderExtraUI();

    // stocks grid
    const grid = document.querySelector("#stocks");
    if (grid) {
      grid.innerHTML = "";

      // 固定 4 檔（由 data.json）
      const fixed = Object.values(data.stocks || {});
      fixed.forEach((s) => grid.appendChild(renderStockCard(s, data)));

      // 自選 2 檔（前端即時抓，不影響固定 4 檔）
      const [a, b] = readExtraTickers().map(normTicker);
      const extras = [a, b].filter((x) => x && !fixed.some((s) => String(s.ticker) === String(x)));

      for (const t of extras) {
        try {
          const price = await fetchTwsePrice(t);
          const foreign = await fetchTwseForeignD0(t);
          const obj = {
            ticker: t,
            name: "",
            price: {
              close: price.close,
              change: price.change,
              change_pct: price.change_pct,
            },
            foreign_net_shares: { D0: foreign.D0 },
          };
          grid.appendChild(renderStockCard(obj, data, { isExtra: true }));
        } catch (e) {
          const errCard = document.createElement("div");
          errCard.className = "card";
          errCard.innerHTML = `<div class="kv"><span class="pill">${escapeHtml(t)}</span><strong>自選</strong></div>
            <div class="bad" style="margin-top:8px">抓不到資料：${escapeHtml(e?.message || e)}</div>`;
          grid.appendChild(errCard);
        }
      }
    }

    // ZGB / ZGK_D
    renderZgb(data);
    renderZgkD(data);
  } catch (e) {
    const meta = document.querySelector("#meta");
    if (meta) meta.textContent = "載入失敗";
    const stocks = document.querySelector("#stocks");
    if (stocks) stocks.innerHTML = `<div class="card"><strong>載入失敗</strong><div class="muted">${escapeHtml(e)}</div></div>`;
  }
})();




