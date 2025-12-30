// 固定 4 檔讀 data.json；自選 2 檔走前端即時抓 + localStorage
const DATA_URL = "./data.json";
const EXTRA_LS_KEY = "tw-stock-06.extraTickers.v1"; // 改這個 key 就會清空舊資料

// 台股習慣：紅=上漲/買超、綠=下跌/賣超
const FUTURES_SUPPORTED = new Set(["2330", "2317", "3231", "2382"]);

/* -------------------- utils -------------------- */
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

function trendInfo(change, changePct) {
  const c = change ?? 0;
  const p = changePct ?? 0;
  const absP = Math.abs(p || 0);
  const lv = absP >= 3 ? "lv3" : absP >= 1 ? "lv2" : "lv1";
  if (c > 0) return { cls: "pos", lv, icon: "📈" };
  if (c < 0) return { cls: "neg", lv, icon: "📉" };
  return { cls: "flat", lv: "lv1", icon: "➖" };
}

function foreignTag(netLots) {
  if (netLots === null || netLots === undefined) return null;
  const absN = Math.abs(netLots);
  if (absN < 800) return null; // <800 不標
  if (netLots >= 3000) return { text: "強買超", cls: "pos", lv: "lv3" };
  if (netLots >= 800) return { text: "買超", cls: "pos", lv: "lv2" };
  if (netLots <= -3000) return { text: "強賣超", cls: "neg", lv: "lv3" };
  return { text: "賣超", cls: "neg", lv: "lv2" };
}

function parseSignedPercent(s) {
  // "+0.65%" -> 0.65 ; "-1.2%" -> -1.2
  const n = toNumber(s);
  return n === null ? null : n;
}

/* -------------------- data load -------------------- */
async function loadData() {
  const r = await fetch(DATA_URL, { cache: "no-store" });
  if (!r.ok) throw new Error("load data.json failed");
  return r.json();
}

/* -------------------- cards -------------------- */
function renderStockCard(s, data, { isExtra = false } = {}) {
  const card = document.createElement("div");
  card.className = "card";

  const price = s.price || {};
  const f = s.foreign_net_shares || {};
  const ticker = String(s.ticker || "");
  const name = String(s.name || ticker);

  const changeVal = toNumber(price.change);
  const changePctVal = parseSignedPercent(price.change_pct);
  const trend = trendInfo(changeVal, changePctVal);

  const foreignLots = toNumber(f.D0); // 這裡已是「張」
  const foreignTagObj = foreignTag(foreignLots);

  const futAll = data?.taifex_large_trader || {};
  const futDate = futAll.date ? String(futAll.date) : "";
  const futError = futAll.error ? String(futAll.error) : "";
  const fut = futAll.by_ticker ? futAll.by_ticker[ticker] : null;

  let futHtml = "";
  if (FUTURES_SUPPORTED.has(ticker)) {
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
  } else {
    futHtml = `
      <div class="fut">
        <div class="fut-head"><small>✅ 期貨未平倉（大額交易人）</small></div>
        <div class="muted">此欄位目前只支援：2330/2317/3231/2382</div>
      </div>
    `;
  }

  card.innerHTML = `
    <div class="row">
      <div style="min-width:0">
        <div class="kv">
          <span class="pill">${escapeHtml(ticker)}</span>
          <strong>${escapeHtml(name)}</strong>
          ${isExtra ? `<span class="pill pill-mini">自選</span>` : ""}
        </div>

        <div style="margin-top:6px">
          <small>收盤</small> <strong>${escapeHtml(price.close ?? "-")}</strong>

          <span class="metric" style="margin-left:10px">
            <small>漲跌</small>
            <span class="badge ${trend.cls} ${trend.lv}">${trend.icon} ${escapeHtml(price.change ?? "-")}</span>
            <small class="muted">(${escapeHtml(price.change_pct ?? "-")})</small>
          </span>
        </div>

        <div style="margin-top:6px">
          <small>外資買賣超(張)</small>
          <div class="kv" style="margin-top:4px">
            <span class="pill ${foreignLots > 0 ? "pill-pos" : foreignLots < 0 ? "pill-neg" : ""}">
              ${escapeHtml(data.latest_trading_day)}: ${escapeHtml(f.D0 ?? "-")}
            </span>
            <span class="pill">
              ${escapeHtml(data.prev_trading_day)}: ${escapeHtml(f.D1 ?? "-")}
            </span>
            ${
              foreignTagObj
                ? `<span class="badge ${foreignTagObj.cls} ${foreignTagObj.lv}">💰 ${escapeHtml(foreignTagObj.text)}</span>`
                : ""
            }
          </div>
        </div>

        ${futHtml}
      </div>

      <div class="tabs">
        <button class="tab active" data-cat="conference">法說</button>
        <button class="tab" data-cat="revenue">營收</button>
        <button class="tab" data-cat="material">重大訊息</button>
        <button class="tab" data-cat="capacity">產能</button>
        <button class="tab" data-cat="export">美國出口管制</button>
      </div>
    </div>

    <div class="news" data-box></div>
  `;

  const tabs = Array.from(card.querySelectorAll(".tab"));
  const box = card.querySelector("[data-box]");

  function renderList(cat) {
    const list = (s.news && s.news[cat]) || [];
    if (!list.length) {
      box.innerHTML = `<div class="muted">這類今天沒有抓到新新聞（或資料源暫時無回應）。</div>`;
      return;
    }
    const html = list
      .map(
        (it) =>
          `<div class="item">• <a href="${escapeHtml(it.url)}" target="_blank" rel="noreferrer">${escapeHtml(
            it.title
          )}</a><div class="muted">${escapeHtml(it.time || "")}</div></div>`
      )
      .join("");
    box.innerHTML = html;
  }

  renderList("conference");
  tabs.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabs.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderList(btn.dataset.cat);
    });
  });

  return card;
}

/* -------------------- ZGB / ZGK render -------------------- */
function renderZGB(data) {
  const el = document.querySelector("#zgb");
  if (!el) return;

  const zgb = data.fubon_zgb || {};
  if (zgb.error) {
    el.innerHTML = `<div class="bad">${escapeHtml(zgb.error)}</div>`;
    return;
  }
  const rows = zgb.rows || [];
  if (!rows.length) {
    el.innerHTML = `<div class="muted">（無資料）</div>`;
    return;
  }

  const datePill = zgb.date ? `<span class="pill pill-mini">資料日 ${escapeHtml(zgb.date)}</span>` : "";
  const trs = rows
    .map(
      (r) => `
    <tr>
      <td>${escapeHtml(r.name ?? "")}</td>
      <td>${escapeHtml(r.buy ?? "-")}</td>
      <td>${escapeHtml(r.sell ?? "-")}</td>
      <td>${escapeHtml(r.diff ?? "-")}</td>
    </tr>`
    )
    .join("");

  el.innerHTML = `
    <div class="kv">${datePill}</div>
    <table>
      <thead>
        <tr><th>券商名稱</th><th>買進金額</th><th>賣出金額</th><th>差額</th></tr>
      </thead>
      <tbody>${trs}</tbody>
    </table>
  `;
}

function renderZGK(data) {
  const el = document.querySelector("#zgk");
  if (!el) return;

  const zgk = data.fubon_zgk_d || {};
  if (zgk.error) {
    el.innerHTML = `<div class="bad">${escapeHtml(zgk.error)}</div>`;
    return;
  }
  const buy = zgk.buy || [];
  const sell = zgk.sell || [];
  if (!buy.length && !sell.length) {
    el.innerHTML = `<div class="muted">（無資料）</div>`;
    return;
  }

  const datePill = zgk.date ? `<span class="pill pill-mini">日期 ${escapeHtml(zgk.date)}</span>` : "";

  const maxRows = Math.max(buy.length, sell.length);
  const trs = [];
  for (let i = 0; i < maxRows; i++) {
    const b = buy[i] || {};
    const s = sell[i] || {};
    trs.push(`
      <tr>
        <td>${escapeHtml(b.rank ?? "")}</td>
        <td>${escapeHtml((b.ticker ? b.ticker + " " : "") + (b.name ?? ""))}</td>
        <td>${escapeHtml(b.net ?? "")}</td>
        <td>${escapeHtml(b.close ?? "")}</td>
        <td>${escapeHtml(b.change ?? "")}</td>

        <td>${escapeHtml(s.rank ?? "")}</td>
        <td>${escapeHtml((s.ticker ? s.ticker + " " : "") + (s.name ?? ""))}</td>
        <td>${escapeHtml(s.net ?? "")}</td>
        <td>${escapeHtml(s.close ?? "")}</td>
        <td>${escapeHtml(s.change ?? "")}</td>
      </tr>
    `);
  }

  el.innerHTML = `
    <div class="kv">${datePill}</div>
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
      <tbody>${trs.join("")}</tbody>
    </table>
  `;
}

/* -------------------- extra UI / fetch -------------------- */
function getExtraTickers() {
  try {
    const raw = localStorage.getItem(EXTRA_LS_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(arr)) return [];
    return arr.map((x) => String(x || "").trim()).filter(Boolean).slice(0, 2);
  } catch {
    return [];
  }
}

function setExtraTickers(list) {
  localStorage.setItem(EXTRA_LS_KEY, JSON.stringify(list.slice(0, 2)));
}

function renderExtraUI(onApply, onClear) {
  const el = document.querySelector("#extra");
  if (!el) return;

  const stored = getExtraTickers();
  const v1 = stored[0] || "";
  const v2 = stored[1] || "";

  el.innerHTML = `
    <div class="kv" style="gap:14px; align-items:center">
      <div>
        <div class="muted" style="font-size:12px; margin-bottom:6px">加股票 1（4 碼）</div>
        <input id="ex1" value="${escapeHtml(v1)}" inputmode="numeric" maxlength="6"
               style="width:120px;padding:8px 10px;border-radius:10px;border:1px solid #2a3c55;background:#0d1420;color:#e8eef6" />
      </div>
      <div>
        <div class="muted" style="font-size:12px; margin-bottom:6px">加股票 2（4 碼）</div>
        <input id="ex2" value="${escapeHtml(v2)}" inputmode="numeric" maxlength="6"
               style="width:120px;padding:8px 10px;border-radius:10px;border:1px solid #2a3c55;background:#0d1420;color:#e8eef6" />
      </div>

      <div style="display:flex; gap:10px; align-items:flex-end; padding-bottom:2px">
        <button id="apply" class="tab" style="padding:8px 12px">套用</button>
        <button id="clear" class="tab" style="padding:8px 12px">清空</button>
      </div>
    </div>
    <div class="muted" style="margin-top:10px">
      這兩支是你「隔天關掉瀏覽器也還會留著」的自選股（存在 localStorage；不影響固定 4 檔的 GitHub Actions 更新）。
    </div>
  `;

  el.querySelector("#apply").addEventListener("click", () => {
    const t1 = (el.querySelector("#ex1").value || "").trim();
    const t2 = (el.querySelector("#ex2").value || "").trim();
    onApply([t1, t2]);
  });

  el.querySelector("#clear").addEventListener("click", () => {
    el.querySelector("#ex1").value = "";
    el.querySelector("#ex2").value = "";
    onClear();
  });
}

function isValidTicker(t) {
  return /^[0-9]{4,6}$/.test(String(t || "").trim());
}

async function fetchTwseCodeName(ticker) {
  // 盡量拿到名稱（拿不到就用 ticker）
  try {
    const url = `https://www.twse.com.tw/rwd/zh/api/codeQuery?query=${encodeURIComponent(ticker)}`;
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) return null;
    const j = await r.json();
    const arr = j.suggestions || [];
    if (!arr.length) return null;
    // suggestions 格式通常是 ["2330\t台積電", ...]
    const first = String(arr[0] || "");
    const parts = first.split("\t");
    if (parts.length >= 2) return parts[1].trim();
    return null;
  } catch {
    return null;
  }
}

function rocToAd(roc) {
  // "114/12/30" => "2025-12-30"
  const m = String(roc).match(/^(\d{2,3})\/(\d{1,2})\/(\d{1,2})$/);
  if (!m) return null;
  const y = Number(m[1]) + 1911;
  const mm = String(m[2]).padStart(2, "0");
  const dd = String(m[3]).padStart(2, "0");
  return `${y}-${mm}-${dd}`;
}

async function fetchPriceChangePct(ticker, latestTradingDay) {
  // 用 TWSE STOCK_DAY（同後端做法）
  try {
    const ymd = latestTradingDay.replaceAll("-", "");
    const url = `https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=${ymd}&stockNo=${ticker}`;
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("TWSE STOCK_DAY failed");
    const j = await r.json();
    const rows = j.data || [];
    if (!rows.length) throw new Error("no rows");

    const parsed = [];
    for (const row of rows) {
      const ad = rocToAd(row[0]);
      const close = toNumber(row[6]);
      const chg = toNumber(row[7]);
      if (ad && close !== null && chg !== null) parsed.push({ ad, close, chg });
    }
    parsed.sort((a, b) => (a.ad > b.ad ? 1 : -1));
    let idx = parsed.findIndex((x) => x.ad === latestTradingDay);
    if (idx < 0) idx = parsed.length - 1;
    const cur = parsed[idx];

    let prevClose = null;
    if (idx - 1 >= 0) prevClose = parsed[idx - 1].close;
    // 如果同月只有一天，這裡就先不補上個月（前端自選股就簡化）
    const pct = prevClose ? ((cur.close - prevClose) / prevClose) * 100 : null;

    const closeStr = Number.isInteger(cur.close) ? String(cur.close) : String(cur.close).replace(/\.0+$/, "");
    const chgStr = (cur.chg > 0 ? "+" : "") + String(cur.chg).replace(/\.0+$/, "");
    const pctStr = pct === null ? null : (pct > 0 ? "+" : "") + pct.toFixed(2) + "%";

    return { close: closeStr, change: chgStr, change_pct: pctStr };
  } catch {
    return { close: null, change: null, change_pct: null };
  }
}

async function fetchForeignLots(ticker, ymd) {
  // ymd: "YYYY-MM-DD"
  try {
    const url = `https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999&date=${ymd.replaceAll("-", "")}`;
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) return null;
    const j = await r.json();
    const data = j.data || [];
    for (const row of data) {
      if (String(row[0]).trim() === String(ticker)) {
        const netShares = toNumber(row[4]);
        if (netShares === null) return null;
        const lots = Math.round(netShares / 1000); // 跟後端一樣（足夠）
        return lots.toLocaleString("en-US");
      }
    }
    return null;
  } catch {
    return null;
  }
}

async function fetchExtraStock(ticker, data) {
  const name = (await fetchTwseCodeName(ticker)) || ticker;
  const price = await fetchPriceChangePct(ticker, data.latest_trading_day);
  const d0 = await fetchForeignLots(ticker, data.latest_trading_day);
  const d1 = await fetchForeignLots(ticker, data.prev_trading_day);

  return {
    ticker,
    name,
    price,
    foreign_net_shares: { D0: d0, D1: d1 },
    news: { conference: [], revenue: [], material: [], capacity: [], export: [] },
  };
}

/* -------------------- main render -------------------- */
async function renderAll() {
  const data = await loadData();

  // meta
  const meta = document.querySelector("#meta");
  if (meta) {
    meta.textContent = `更新時間：${data.generated_at || "-"} ｜ 最新交易日：${data.latest_trading_day || "-"} ｜ 前一交易日：${
      data.prev_trading_day || "-"
    }`;
  }

  // extra UI
  renderExtraUI(
    async (tickers) => {
      const cleaned = tickers.map((t) => t.trim()).filter(Boolean).slice(0, 2);
      const finalList = cleaned.filter(isValidTicker);
      setExtraTickers(finalList);
      await renderStocks(data, finalList);
    },
    async () => {
      setExtraTickers([]);
      await renderStocks(data, []);
    }
  );

  // stocks (fixed 4 + extra 2)
  const extra = getExtraTickers().filter(isValidTicker);
  await renderStocks(data, extra);

  // zgb / zgk
  renderZGB(data);
  renderZGK(data);
}

async function renderStocks(data, extraTickers) {
  const root = document.querySelector("#stocks");
  if (!root) return;
  root.innerHTML = "";

  const fixedStocks = Object.values(data.stocks || {});
  for (const s of fixedStocks) {
    root.appendChild(renderStockCard(s, data, { isExtra: false }));
  }

  // extra
  for (const t of extraTickers) {
    try {
      const ex = await fetchExtraStock(t, data);
      root.appendChild(renderStockCard(ex, data, { isExtra: true }));
    } catch (e) {
      const err = document.createElement("div");
      err.className = "card";
      err.innerHTML = `<div class="bad">自選 ${escapeHtml(t)} 抓取失敗：${escapeHtml(e)}</div>`;
      root.appendChild(err);
    }
  }
}

// 入口
renderAll().catch((e) => {
  const meta = document.querySelector("#meta");
  if (meta) meta.textContent = `載入失敗：${String(e)}`;
  console.error(e);
});


