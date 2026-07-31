/* Equity Decision Engine — dashboard renderer */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
let charts = [];
let currentReport = null;
let compareData = [];

/* ---------- formatting ---------- */
const fmtUSD = v => {
  if (v == null) return "n/a";
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  for (const [u, d] of [["T", 1e12], ["B", 1e9], ["M", 1e6], ["K", 1e3]])
    if (a >= d) return `${sign}$${(a / d).toFixed(1)}${u}`;
  return `${sign}$${a.toFixed(0)}`;
};
const fmtPct = (v, signed = false) =>
  v == null ? "n/a" : `${signed && v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
const fmtX = v => (v == null ? "n/a" : `${v.toFixed(1)}x`);
const fmtVal = (v, fmt) => {
  if (v == null) return "n/a";
  if (fmt === "pct") return fmtPct(v);
  if (fmt === "usd") return fmtUSD(v);
  if (fmt === "x") return typeof v === "number" ? v.toFixed(2) : v;
  if (fmt === "flag") return v ? "yes" : "no";
  return typeof v === "number" ? v.toFixed(2) : v;
};
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cls = r => "rating-" + String(r || "hold").toLowerCase().replace(/\s+/g, "-");
/* Theme palette — series colors validated for CVD separation + contrast on
   the dark card surface (dataviz method); status colors are semantic only. */
const PAL = {
  s1: "#0899b5",   // cyan    — categorical slot 1
  s2: "#8b5cf6",   // violet  — slot 2
  s3: "#bd8506",   // amber   — slot 3
  s4: "#e0489a",   // magenta — slot 4
  accent: "#2de0f7",
  good: "#1fa876", goodText: "#3ddc97",
  bad: "#e24c44", badText: "#ff7f76",
  warnText: "#f0b429",
  grid: "#16223a", tick: "#7e90ab", legend: "#b9c7da",
};
const scoreColor = s => (s >= 70 ? PAL.goodText : s >= 50 ? PAL.warnText : PAL.badText);
/* SeekingAlpha-style letter grades from 0-100 factor scores */
function gradeOf(s) {
  if (s == null) return { g: "—", c: "" };
  const map = [[90, "A+"], [80, "A"], [75, "A-"], [70, "B+"], [65, "B"], [60, "B-"],
               [55, "C+"], [50, "C"], [45, "C-"], [40, "D+"], [35, "D"], [30, "D-"], [-1, "F"]];
  const g = map.find(([t]) => s >= t)[1];
  const c = g[0] === "A" ? "g-a" : g[0] === "B" ? "g-b" : g[0] === "C" ? "g-c" : "g-d";
  return { g, c };
}

/* ---------- shell ---------- */
function setStatus(msg, kind = "loading") {
  const el = $("#status");
  if (!msg) { el.classList.add("hidden"); return; }
  el.textContent = msg;
  el.className = `status ${kind}`;
}

$$(".tab").forEach(t => t.addEventListener("click", () => {
  $$(".tab").forEach(x => x.classList.toggle("active", x === t));
  $$(".view").forEach(v => v.classList.add("hidden"));
  $(`#view-${t.dataset.view}`).classList.remove("hidden");
  if (t.dataset.view === "watchlist") loadWatchlist();
}));

$("#search-form").addEventListener("submit", e => {
  e.preventDefault();
  const active = $(".ac-item.active");
  const tk = active ? active.dataset.sym : $("#ticker-input").value.trim().toUpperCase();
  hideAC();
  if (tk) analyzeTicker(tk);
});

/* ---------- ticker/name autocomplete ---------- */
let acTimer = null, acIndex = -1;
const acList = $("#ac-list");
const hideAC = () => { acList.classList.add("hidden"); acList.innerHTML = ""; acIndex = -1; };

$("#ticker-input").addEventListener("input", e => {
  clearTimeout(acTimer);
  const q = e.target.value.trim();
  if (q.length < 2) { hideAC(); return; }
  acTimer = setTimeout(async () => {
    try {
      const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
      if (!data.results.length) { hideAC(); return; }
      acList.innerHTML = data.results.map(r => `
        <div class="ac-item" data-sym="${esc(r.symbol)}">
          <span class="sym">${esc(r.symbol)}</span>
          <span class="nm">${esc(r.name)}</span>
          <span class="ex">${esc(r.exchange)}${r.type === "ETF" ? " · ETF" : ""}</span>
        </div>`).join("");
      acList.classList.remove("hidden");
      acIndex = -1;
      $$(".ac-item", acList).forEach(item => item.addEventListener("mousedown", ev => {
        ev.preventDefault();
        $("#ticker-input").value = item.dataset.sym;
        hideAC();
        analyzeTicker(item.dataset.sym);
      }));
    } catch { hideAC(); }
  }, 280);
});
$("#ticker-input").addEventListener("keydown", e => {
  const items = $$(".ac-item", acList);
  if (!items.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    acIndex = (acIndex + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((it, i) => it.classList.toggle("active", i === acIndex));
  } else if (e.key === "Escape") hideAC();
});
$("#ticker-input").addEventListener("blur", () => setTimeout(hideAC, 150));
for (const id of ["#example-chips", "#recent-chips"]) {
  const el = $(id);
  if (el) el.addEventListener("click", e => {
    if (e.target.classList.contains("chip")) {
      $("#ticker-input").value = e.target.textContent;
      analyzeTicker(e.target.textContent);
    }
  });
}
$("#search-clear").addEventListener("click", () => {
  const inp = $("#ticker-input");
  inp.value = "";
  hideAC();
  inp.focus();
});
renderRecent();
// surface whether the optional FMP data upgrade is active
api("/api/config").then(cfg => {
  if (!cfg.fmp_enabled) {
    const el = document.createElement("p");
    el.className = "muted";
    el.style.cssText = "margin-top:14px;font-size:.8rem";
    el.textContent = "Optional: paste a free Financial Modeling Prep API key into "
      + "stock-analyzer/.env to unlock 10-year history and earnings-call tone analysis.";
    $("#report-empty")?.appendChild(el);
  }
}).catch(() => {});

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

/* recently viewed tickers (localStorage) — function declarations only:
   renderRecent() is invoked above this point during initial wiring */
function getRecent() {
  try { return JSON.parse(localStorage.getItem("ede_recent_tickers")) || []; } catch { return []; }
}
function pushRecent(tk) {
  const list = [tk, ...getRecent().filter(t => t !== tk)].slice(0, 8);
  try { localStorage.setItem("ede_recent_tickers", JSON.stringify(list)); } catch { /* private mode */ }
  renderRecent();
}
function renderRecent() {
  const el = $("#recent-chips");
  if (!el) return;
  const list = getRecent();
  el.innerHTML = list.length
    ? `<span class="muted" style="align-self:center">Recent:</span>` +
      list.map(t => `<button class="chip">${esc(t)}</button>`).join("")
    : "";
}

async function analyzeTicker(tk) {
  $$(".tab").forEach(x => x.classList.toggle("active", x.dataset.view === "report"));
  $$(".view").forEach(v => v.classList.add("hidden"));
  $("#view-report").classList.remove("hidden");
  setStatus(`Analyzing ${tk} — fetching financials, peers and prices…`);
  $("#analyze-btn").disabled = true;
  try {
    const r = await api(`/api/analyze/${encodeURIComponent(tk)}`);
    currentReport = r;
    if (location.hash.slice(1).toUpperCase() !== r.ticker)
      history.pushState(null, "", "#" + r.ticker);
    document.title = `${r.ticker} · ${r.final_rating} — Equity Decision Engine`;
    pushRecent(r.ticker);
    renderReport(r);
    setStatus("");
  } catch (err) {
    setStatus(`Could not analyze ${tk}: ${err.message}`, "error");
    // an invalid ticker should leave a usable page, not a half-rendered one
    if (!currentReport) {
      $("#report-empty").classList.remove("hidden");
      $("#report").classList.add("hidden");
    }
  } finally {
    $("#analyze-btn").disabled = false;
  }
}

/* deep links: #TICKER is analyzable, bookmarkable, back/forward-friendly */
function analyzeFromHash() {
  const tk = location.hash.slice(1).trim().toUpperCase();
  if (tk && /^[A-Z0-9.\-]{1,10}$/.test(tk) && tk !== currentReport?.ticker) {
    $("#ticker-input").value = tk;
    analyzeTicker(tk);
  }
}
window.addEventListener("popstate", analyzeFromHash);
// DOMContentLoaded may already have fired by the time this script runs
// (cached reload) — in that case run the deep-link handler immediately
if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", analyzeFromHash);
} else {
  analyzeFromHash();
}

/* ---------- report ---------- */
function renderReport(r) {
  $("#report-empty").classList.add("hidden");
  const root = $("#report");
  root.classList.remove("hidden");
  charts.forEach(c => c.destroy());
  charts = [];

  const v = r.valuation;
  const conf = r.confidence;
  const confPill = conf === "High" ? "good" : conf === "Medium" ? "warn" : "bad";
  const timingPill = r.timing_rating === "Good Entry" ? "good" : r.timing_rating === "Wait" ? "warn" : "bad";
  const rrPill = ["Excellent", "Favorable"].includes(r.risk_reward_grade) ? "good"
    : r.risk_reward_grade === "Balanced" ? "warn" : "bad";

  root.innerHTML = `
  ${r.offline_snapshot ? `<div class="status error" style="margin-bottom:16px">
    📡 ${esc(r.offline_note)}</div>` : ""}
  <div class="card">
    <div class="headline">
      <div class="rating-badge ${cls(r.final_rating)}">${esc(r.final_rating)}</div>
      <div class="score-dial">
        <div class="num" style="color:${scoreColor(r.total_score)}">${r.total_score.toFixed(0)}</div>
        <div class="lbl">Score / 100</div>
      </div>
      <div class="headline-meta">
        <h2>${esc(r.name)} <span class="muted">(${esc(r.ticker)})</span></h2>
        <div class="muted">${esc(r.sector || "")} · ${esc(r.industry || "")} ·
          $${r.price ? r.price.toFixed(2) : "n/a"} ${esc(r.currency || "")}</div>
        <div class="badge-row">
          <span class="pill ${confPill}"><span class="k">Confidence:</span> ${esc(conf)}</span>
          <span class="pill ${timingPill}"><span class="k">Timing:</span> ${esc(r.timing_rating)}</span>
          <span class="pill ${rrPill}"><span class="k">Risk/Reward:</span> ${esc(r.risk_reward_grade)}</span>
          ${r.wall_street?.consensus ? `<span class="pill"><span class="k">Wall St:</span>
            ${esc(r.wall_street.consensus.replace(/_/g, " ").replace(/\b\w/g, ch => ch.toUpperCase()))}
            (${r.wall_street.analysts || "?"} analysts)</span>` : ""}
          ${r.data_quality.score < 60 ? `<span class="pill bad"><span class="k">Data Quality:</span>
            ${r.data_quality.score}/100</span>` : ""}
        </div>
        <div class="grade-strip">${[
          ["valuation", "Valuation"], ["revenue_growth", "Growth"],
          ["profitability", "Profitability"], ["momentum", "Momentum"],
          ["forward", "Revisions"], ["sentiment", "Sentiment"],
        ].map(([k, label]) => {
          const f = r.factors[k];
          const { g, c } = gradeOf(f?.score);
          return `<div class="grade-chip" title="${esc(f?.label || label)}: ${f ? f.score.toFixed(0) : "n/a"}/100">
            <span class="gc-letter ${c}">${g}</span><span class="gc-label">${esc(label)}</span></div>`;
        }).join("")}</div>
      </div>
    </div>
    ${r.margin_of_safety_note ? `<div class="note-box">${esc(r.margin_of_safety_note)}</div>` : ""}
    ${r.insufficient_data ? `<div class="note-box">⚠ Data quality below 40 — no Buy/Sell/Hold rating is given.</div>` : ""}
    <p style="margin-top:14px">${esc(r.final_explanation)}</p>
    <div class="section-actions" style="margin-top:14px">
      <button class="secondary" id="btn-watch">☆ Add to watchlist</button>
      <a href="/api/export/${esc(r.ticker)}.csv"><button class="secondary">⬇ Export CSV</button></a>
      <button class="secondary" onclick="window.print()">🖨 Print / PDF</button>
      <button class="secondary" id="btn-backtest">▶ Run backtest</button>
      <button class="secondary" id="btn-history">🕘 Rating history</button>
    </div>
  </div>

  <nav class="report-nav" id="report-nav">
    ${[["overview", "Overview"], ["valuation", "Valuation"], ["score", "Score & Risk"],
       ["market", "Market & Peers"], ["charts", "Charts"], ["data", "Data & History"]]
      .map(([k, label]) => `<button class="rtab${k === "overview" ? " active" : ""}"
        data-rtab="${k}">${label}</button>`).join("")}
  </nav>

  <div class="card" data-tab="overview"><h2>Verdict at a glance</h2>
    ${v ? buildRangeBar(r, v) : `<p class="muted">${esc(r.valuation_summary)}</p>`}
    ${v ? `<div class="badge-row" style="margin-top:4px">
      <span class="pill bad"><span class="k">Bear</span> $${v.scenarios.bear.fair_value.toFixed(0)}
        (${fmtPct(v.scenarios.bear.upside, true)})</span>
      <span class="pill"><span class="k">Base</span> $${v.scenarios.base.fair_value.toFixed(0)}
        (${fmtPct(v.scenarios.base.upside, true)})</span>
      <span class="pill good"><span class="k">Bull</span> $${v.scenarios.bull.fair_value.toFixed(0)}
        (${fmtPct(v.scenarios.bull.upside, true)})</span>
      <span class="pill"><span class="k">Expected</span> ${fmtPct(v.expected_upside, true)}</span>
    </div>` : ""}
    <p style="margin-top:12px"><span class="muted">Suitability:</span>
      <strong>${esc(r.position_suitability)}</strong> — ${esc(r.position_suitability_explanation)}</p>
    <p style="margin-top:8px">${flagSummaryLine(r)}</p>
  </div>

  <div class="card" data-tab="overview"><h2>Key stats</h2>
    <div class="grid cols-3">${keyStats(r).map(([k, val]) =>
      `<div><span class="muted">${esc(k)}:</span> <strong>${esc(val)}</strong></div>`).join("")}
    </div>
  </div>

  <div class="grid cols-2" data-tab="score">
    <div class="card"><h2>Timing — ${esc(r.timing_rating)}</h2><p>${esc(r.timing_reason)}</p>
      <h3 class="sub">Risk/Reward — ${esc(r.risk_reward_grade)}</h3><p>${esc(r.risk_reward_explanation)}</p>
      <h3 class="sub">Position suitability — ${esc(r.position_suitability)}</h3>
      <p>${esc(r.position_suitability_explanation)}</p></div>
    <div class="card"><h2>Company type — ${esc(r.company_type)}</h2>
      <ul class="plain">${r.company_type_reasons.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      <h3 class="sub">Confidence — ${esc(conf)}</h3>
      <ul class="plain">${r.confidence_reasons.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
  </div>

  <div class="card" data-tab="data"><h2>Financial snapshot</h2>
    <div class="grid cols-3">${r.financial_snapshot.map(x =>
      `<div><span class="muted">${esc(x.label)}:</span> <strong>${esc(x.value)}</strong></div>`).join("")}
    </div>
    ${r.sector_specific && r.sector_specific.notes ? `<p class="muted" style="margin-top:10px;font-size:.8rem">
      Sector-specific metrics (${esc(r.sector_specific.kind)}): ${r.sector_specific.notes.map(esc).join(" ")}</p>` : ""}
  </div>

  <div class="card" data-tab="score"><h2>Score breakdown <span class="muted" style="text-transform:none">
    (weights adjusted for ${esc(r.company_type)})</span></h2>
    <div id="factors"></div>
    ${r.score_penalties.length ? `<h3 class="sub">Post-score safeguard penalties</h3>
      <ul class="plain cross">${r.score_penalties.map(p =>
        `<li>${esc(p.reason)}: ${p.points} points</li>`).join("")}</ul>` : ""}
    ${r.imputed_weight > 0 ? `<p class="imputed-tag">${r.imputed_weight}% of weight had insufficient
      data and was scored neutrally (50).</p>` : ""}
  </div>

  ${v ? renderValuationCard(r, v) : `<div class="card" data-tab="valuation"><h2>Valuation</h2><p>${esc(r.valuation_summary)}</p></div>`}

  ${renderNewsCard(r)}

  <div class="grid cols-2" data-tab="overview">
    <div class="card"><h2>Key strengths</h2>
      <ul class="plain check">${r.strengths.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
    <div class="card"><h2>Key weaknesses</h2>
      <ul class="plain cross">${r.weaknesses.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
  </div>

  <div class="card" data-tab="score"><h2>Red flags (${r.red_flags.length})</h2>
    ${r.red_flags.length ? r.red_flags.map(f => `<div class="flag">
      <span class="sev sev-${f.severity.toLowerCase()}">${esc(f.severity)}</span>
      <div><strong>${esc(f.flag)}</strong> — ${esc(f.explanation)}
        <div class="muted">${esc(f.why_it_matters)}${f.affects_rating ? "" : " (informational; does not affect the rating)"}</div>
      </div></div>`).join("")
    : `<p class="muted">No red flags detected in the available data.</p>`}
    <h3 class="sub">Risk summary</h3><p>${esc(r.risk_summary)}</p></div>

  <div class="card" data-tab="score"><h2>Quality scores</h2>
    <div class="mini-scores">
      <div class="mini-score"><div class="v" style="color:${scoreColor(r.accounting_quality.score)}">
        ${r.accounting_quality.score}</div><div class="k">Accounting quality (${esc(r.accounting_quality.verdict)})</div></div>
      <div class="mini-score"><div class="v" style="color:${scoreColor(r.moat.score)}">
        ${r.moat.score.toFixed(0)}</div><div class="k">Moat — ${esc(r.moat.class)}</div></div>
      <div class="mini-score"><div class="v" style="color:${scoreColor(r.management_quality.score)}">
        ${r.management_quality.score.toFixed(0)}</div><div class="k">Management quality</div></div>
      <div class="mini-score"><div class="v" style="color:${scoreColor(r.data_quality.score)}">
        ${r.data_quality.score}</div><div class="k">Data quality</div></div>
    </div>
    <div class="two-col" style="margin-top:14px">
      <div><h3 class="sub">Accounting quality detail</h3>
        ${r.accounting_quality.note ? `<div class="note-box">${esc(r.accounting_quality.note)}</div>` : ""}
        <table><tr><th>Check</th><th class="num">Value</th><th class="num">Score</th></tr>
        ${r.accounting_quality.rows.map(x => `<tr><td>${esc(x.metric)}</td>
          <td class="num">${typeof x.value === "number" ? x.value.toFixed(2) : "n/a"}</td>
          <td class="num" style="color:${scoreColor(x.score)}">${x.score}</td></tr>`).join("")}</table></div>
      <div><h3 class="sub">Moat reasoning</h3><p style="font-size:.88rem">${esc(r.moat.reasoning)}</p>
        <h3 class="sub">Data quality checks</h3>
        <table>${r.data_quality.checks.map(c => `<tr><td>${c.ok ? "✅" : "❌"} ${esc(c.check)}</td>
          <td class="num muted">${c.weight}pt</td></tr>`).join("")}</table>
        <p class="muted" style="margin-top:6px">${esc(r.data_quality.note)}</p></div>
    </div></div>

  ${renderQuantChecks(r)}

  <div class="card" data-tab="market"><h2>Peer comparison</h2>
    <p style="margin-bottom:10px">${esc(r.peer_comparison.summary)}</p>
    ${renderPeerTable(r)}</div>

  <div class="grid cols-2" data-tab="market">
    <div class="card"><h2>Catalysts</h2>
      <p class="muted">${esc(r.catalyst_summary)}</p>
      ${r.catalysts.map(c => `<div class="flag">
        <span class="sev ${c.direction === "Positive" ? "sev-positive" : c.direction === "Negative" ? "sev-high" : "sev-low"}">${esc(c.direction)}</span>
        <div><strong>${esc(c.catalyst)}</strong>
          <div class="muted">${esc(c.note)} · Catalyst risk: ${esc(c.risk)}</div></div></div>`).join("")}</div>
    <div class="card"><h2>Macro sensitivity</h2>
      <p style="margin-bottom:8px">${esc(r.macro.summary)}</p>
      ${r.macro.rows.map(x => `<div class="flag">
        <span class="sev ${x.direction === "help" ? "sev-positive" : x.direction === "hurt" ? "sev-high" : "sev-low"}">${esc(x.direction)}</span>
        <div><strong>${esc(x.factor)}</strong><div class="muted">${esc(x.note)}</div></div></div>`).join("")}
      <h3 class="sub">Earnings call commentary</h3>
      ${renderCommentary(r.earnings_commentary)}</div>
  </div>

  <div class="card" id="price-chart-box" data-tab="charts"><h2>Price &amp; moving averages (2y)</h2>
    <div class="chart-wrap"><canvas id="ch-price"></canvas></div></div>

  <div class="card" data-tab="charts"><h2>Financial trends</h2><div class="chart-grid" id="chart-grid"></div></div>

  <div class="grid cols-2" data-tab="score">
    <div class="card"><h2>What would change the rating?</h2>
      <h3 class="sub">Upgrade if</h3><ul class="plain check">${r.what_would_change.upgrade_if.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      <h3 class="sub">Downgrade if</h3><ul class="plain cross">${r.what_would_change.downgrade_if.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      <h3 class="sub">Would become a Sell if</h3><ul class="plain cross">${r.what_would_change.sell_if.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      <h3 class="sub">Would become a Strong Buy if</h3><ul class="plain check">${r.what_would_change.strong_buy_if.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      <h3 class="sub">Monitor next quarter</h3>
      <p class="muted">Metrics: ${r.what_would_change.monitor_metrics.map(esc).join(" · ")}<br>
      Risks: ${r.what_would_change.monitor_risks.map(esc).join(" · ")}<br>
      Catalysts: ${r.what_would_change.monitor_catalysts.map(esc).join(" · ")}</p></div>
    <div class="card"><h2>Why this rating could be wrong</h2>
      <ul class="plain">${r.why_wrong.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
  </div>

  <div class="card hidden" id="backtest-card" data-tab="data"><h2>Backtest — historical simulation</h2>
    <div id="backtest-body"></div></div>
  <div class="card hidden" id="history-card" data-tab="data"><h2>Rating history</h2><div id="history-body"></div></div>

  <div class="card" data-tab="data"><h2>Raw data &amp; model provenance</h2>
    <div class="provenance">
      <span>Model version: <strong>${esc(r.model_version)}</strong></span>
      <span>Generated: ${esc(r.generated_at)}</span>
      <span>Source: ${esc(r.data_source)}</span>
      <span>Last statement: ${esc(r.last_statement_date || "n/a")}</span>
    </div>
    <div class="provenance" style="margin-top:6px">
      <span>Weights: ${Object.entries(r.scoring_formula).map(([k, w]) => `${esc(k)} ${esc(w)}`).join(", ")}</span>
    </div>
    ${r.missing_data_warnings.length ? `<p class="muted" style="margin-top:8px">Missing data:
      ${r.missing_data_warnings.map(esc).join("; ")}</p>` : ""}
    <details class="raw"><summary>Show full raw JSON (every metric used)</summary>
      <pre class="raw-json">${esc(JSON.stringify(r, null, 2))}</pre></details>
  </div>`;

  renderFactors(r);
  void root.offsetHeight; // force layout so Chart.js measures real container widths
  renderCharts(r);

  // report tabs: show one section group at a time (print shows everything)
  $$(".rtab", root).forEach(b =>
    b.addEventListener("click", () => switchReportTab(b.dataset.rtab)));
  root.addEventListener("click", e => {
    const t = e.target.closest("[data-goto-tab]");
    if (t) { switchReportTab(t.dataset.gotoTab); window.scrollTo({ top: 0 }); }
  });
  switchReportTab("overview");

  $("#btn-watch").addEventListener("click", async () => {
    await api(`/api/watchlist/${r.ticker}`, { method: "POST" });
    $("#btn-watch").textContent = "★ On watchlist";
  });
  // reflect existing watchlist membership instead of always showing "Add"
  api("/api/watchlist").then(d => {
    if (d.watchlist.some(w => w.ticker === r.ticker))
      $("#btn-watch").textContent = "★ On watchlist";
  }).catch(() => {});
  $("#btn-backtest").addEventListener("click", () => {
    switchReportTab("data");
    runBacktest(r.ticker);
  });
  $("#btn-history").addEventListener("click", () => {
    switchReportTab("data");
    loadHistory(r.ticker);
  });
  window.scrollTo({ top: 0 });
}

function switchReportTab(key) {
  $$("#report [data-tab]").forEach(el =>
    el.classList.toggle("tab-hidden", el.dataset.tab !== key));
  $$(".rtab").forEach(b => b.classList.toggle("active", b.dataset.rtab === key));
  // charts may have been sized while hidden — force a re-measure on reveal
  if (key === "charts") requestAnimationFrame(() => charts.forEach(c => c.resize()));
}

function renderFactors(r) {
  const box = $("#factors");
  box.innerHTML = Object.values(r.factors).map(f => `
    <div class="factor-row" data-k="${esc(f.key)}">
      <div class="factor-head">
        <span class="name">${esc(f.label)}${f.imputed ? ' <span class="imputed-tag">(no data — neutral)</span>' : ""}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${f.score}%;background:${scoreColor(f.score)};color:${scoreColor(f.score)}"></div></div>
        <span class="val" style="color:${scoreColor(f.score)}">${f.score.toFixed(0)}</span>
        <span class="wt">${f.weight}% wt</span>
      </div>
      <div class="factor-details">${f.details.length ? `
        <table><tr><th>Metric</th><th class="num">Value</th><th class="num">Score</th><th>Note</th></tr>
        ${f.details.map(d => `<tr><td>${esc(d.metric)}</td>
          <td class="num">${fmtVal(d.value, d.format)}</td>
          <td class="num" style="color:${scoreColor(d.score)}">${d.score}</td>
          <td class="muted">${esc(d.note || "")}</td></tr>`).join("")}</table>`
        : `<p class="muted">No underlying data available; factor scored neutrally.</p>`}
      </div>
    </div>`).join("");
  $$(".factor-row", box).forEach(row =>
    row.addEventListener("click", () => row.classList.toggle("open")));
}

function buildRangeBar(r, v) {
  const price = r.price;
  const mc = v.monte_carlo;
  const an = v.analyst_targets;
  const pts = [v.scenarios.bear.fair_value, v.scenarios.bull.fair_value, price,
               v.expected_value];
  if (mc) pts.push(mc.p10, mc.p90);
  if (an?.mean) pts.push(an.mean);
  const lo = Math.min(...pts) * 0.94, hi = Math.max(...pts) * 1.06;
  const pos = x => ((x - lo) / (hi - lo) * 100).toFixed(1) + "%";
  return `
    <div class="fv-range">
      <div class="fv-track">
        ${mc ? `<div class="fv-band outer" style="left:${pos(mc.p10)};width:${((mc.p90 - mc.p10) / (hi - lo) * 100).toFixed(1)}%"></div>
                <div class="fv-band inner" style="left:${pos(mc.p25)};width:${((mc.p75 - mc.p25) / (hi - lo) * 100).toFixed(1)}%"></div>` : ""}
        <div class="fv-tick bear" style="left:${pos(v.scenarios.bear.fair_value)}"><span>Bear $${v.scenarios.bear.fair_value.toFixed(0)}</span></div>
        <div class="fv-tick base" style="left:${pos(v.scenarios.base.fair_value)}"><span>Base $${v.scenarios.base.fair_value.toFixed(0)}</span></div>
        <div class="fv-tick bull" style="left:${pos(v.scenarios.bull.fair_value)}"><span>Bull $${v.scenarios.bull.fair_value.toFixed(0)}</span></div>
        ${an?.mean ? `<div class="fv-tick analyst" style="left:${pos(an.mean)}"><span>Analysts $${an.mean.toFixed(0)}</span></div>` : ""}
        <div class="fv-tick price" style="left:${pos(price)}"><span>Price $${price.toFixed(0)}</span></div>
      </div>
      ${mc ? `<div class="fv-legend muted">Shaded band: Monte Carlo P10–P90 (inner: P25–P75) of ${mc.n.toLocaleString()}
        fair-value draws · ${fmtPct(mc.prob_above_price)} of draws land above the current price</div>` : ""}
    </div>`;
}

function keyStats(r) {
  const m = r.metrics, mom = r.momentum;
  const stats = [
    ["Market cap", fmtUSD(m.market_cap)],
    [m.forward_pe ? "Forward P/E" : "P/S", m.forward_pe ? fmtX(m.forward_pe) : fmtX(m.ps)],
    ["Revenue growth (1y)", fmtPct(m.rev_growth_1y)],
    ["FCF yield", fmtPct(m.fcf_yield)],
    ["Net debt / EBITDA", fmtX(m.net_debt_to_ebitda)],
    ["Dividend yield", fmtPct(m.dividend_yield)],
    ["From 52-wk high", fmtPct(mom.drawdown_from_high, true)],
    ["Volatility (ann.)", fmtPct(mom.volatility_annualized)],
    ["Next earnings", r.calendar?.next_earnings_date ? String(r.calendar.next_earnings_date).slice(0, 10) : "n/a"],
  ];
  return stats.filter(([, val]) => val !== "n/a");
}

function flagSummaryLine(r) {
  const high = r.red_flags.filter(f => f.severity === "High").length;
  const med = r.red_flags.filter(f => f.severity === "Medium").length;
  if (!high && !med) return `<span class="muted">No high- or medium-severity red flags detected.</span>`;
  const parts = [];
  if (high) parts.push(`<span class="neg"><strong>${high} high-severity</strong></span>`);
  if (med) parts.push(`${med} medium-severity`);
  return `⚑ ${parts.join(" and ")} red flag${high + med > 1 ? "s" : ""} —
    <button class="link-btn" data-goto-tab="score">see Score &amp; Risk →</button>`;
}

function renderValuationCard(r, v) {
  const mc = v.monte_carlo;
  const rangeBar = buildRangeBar(r, v);

  const scen = `<div class="scenarios">${["bear", "base", "bull"].map(k => {
    const s = v.scenarios[k];
    return `<div class="scenario ${k}">
      <strong>${esc(s.name)} case</strong> <span class="muted">(${fmtPct(s.probability)} est. probability)</span>
      <div class="fv">$${s.fair_value.toFixed(2)}</div>
      <div class="${s.upside >= 0 ? "pos" : "neg"}">${fmtPct(s.upside, true)} vs current price</div>
      <ul><li>Growth (yr 1, fading): ${fmtPct(s.assumption_growth, true)}</li>
      <li>Margins: ${esc(s.assumption_margin)}</li>
      <li>Exit multiple: ${esc(s.assumption_multiple)}</li></ul>
      ${s.path ? `<table class="fv-path"><tr><th>Yr</th><th class="num">${esc(s.path_label)}</th><th class="num">Implied</th></tr>
        ${s.path.map(p => `<tr><td>${p.year}</td><td class="num">${p.value}</td>
          <td class="num">$${p.implied_price}</td></tr>`).join("")}</table>` : ""}
      ${s.anchors ? `<div class="muted" style="margin-top:8px;font-size:.78rem">Blend: ${s.anchors.map(a =>
        `${esc(a.name)} $${a.fair_value.toFixed(0)} (${fmtPct(a.weight)})`).join(" · ")}</div>` : ""}
    </div>`;
  }).join("")}</div>`;

  return `<div class="card" data-tab="valuation"><h2>Bull / Base / Bear valuation
      <span class="muted" style="text-transform:none">— ${esc(v.method)}</span></h2>
    ${rangeBar}
    ${scen}
    <div class="mini-scores" style="margin-top:14px">
      <div class="mini-score"><div class="v">$${v.expected_value.toFixed(2)}</div>
        <div class="k">Probability-weighted fair value</div></div>
      <div class="mini-score"><div class="v ${v.expected_upside >= 0 ? "pos" : "neg"}">${fmtPct(v.expected_upside, true)}</div>
        <div class="k">Expected upside</div></div>
      ${mc ? `<div class="mini-score"><div class="v">${fmtPct(mc.prob_above_price)}</div>
        <div class="k">Draws above current price</div></div>` : ""}
      <div class="mini-score"><div class="v">${fmtPct(v.required_return)}</div>
        <div class="k">Discount rate used</div></div>
    </div>
    ${v.sanity_note ? `<div class="note-box">${esc(v.sanity_note)}</div>` : ""}
    <p class="muted" style="margin-top:10px;font-size:.82rem">${esc(v.basis_note || "")}
      Discount rate: ${esc((v.required_return_reasons || []).join("; "))}.
      ${v.dcf ? `DCF anchor: $${v.dcf.fair_value.toFixed(2)} — ${esc(v.dcf.assumptions)}` : ""}
      ${(v.probability_reasons || []).length ? `Probability shifts: ${esc(v.probability_reasons.join("; "))}.` : ""}</p>
    <p class="muted" style="margin-top:6px">${esc(v.disclaimer)}</p>
    <h3 class="sub">Valuation summary</h3><p>${esc(r.valuation_summary)}</p></div>`;
}

function renderNewsCard(r) {
  const s = r.sentiment;
  if (!s) return "";
  const news = s.news || {}, market = s.market || {}, ind = s.industry || {};
  const toneCol = t => t === "Bullish" || t === "Leaning bullish" ? PAL.goodText
    : t === "Bearish" || t === "Leaning bearish" ? PAL.badText : PAL.warnText;
  const regimeCol = rg => rg === "Risk-on" ? PAL.goodText : rg === "Risk-off" ? PAL.badText : PAL.warnText;
  const sentPill = t => t === "Bullish" ? "sev-positive" : t === "Bearish" ? "sev-high" : "sev-low";
  const items = (news.items || []).slice(0, 10).map(n => `
    <div class="flag">
      <span class="sev ${sentPill(n.sentiment)}">${esc(n.sentiment)}</span>
      <div>${n.url ? `<a class="news-link" href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>`
                   : `<strong>${esc(n.title)}</strong>`}
        <div class="muted">${esc(n.publisher || "")} ${esc(n.date || "")}${
          n.matched?.length ? ` · matched: ${n.matched.map(esc).join(", ")}` : ""}</div>
      </div>
    </div>`).join("");
  return `<div class="card" data-tab="market"><h2>News &amp; sentiment
      <span class="muted" style="text-transform:none">— feeds the rating at ${r.factors.sentiment?.weight ?? "~4"}% weight</span></h2>
    <div class="mini-scores">
      <div class="mini-score"><div class="v" style="color:${toneCol(news.label)}">${esc(news.label || "n/a")}</div>
        <div class="k">Headline tone (${news.bullish ?? 0}▲ / ${news.bearish ?? 0}▼ / ${news.neutral ?? 0}— of ${news.count ?? 0})</div></div>
      <div class="mini-score"><div class="v" style="color:${regimeCol(market.regime)}">${esc(market.regime || "n/a")}</div>
        <div class="k">Market regime (S&amp;P 500 trend + VIX)</div></div>
      <div class="mini-score"><div class="v" style="color:${toneCol(ind.trend === "Uptrend" ? "Bullish" : ind.trend === "Downtrend" ? "Bearish" : "Neutral")}">${esc(ind.trend || "n/a")}</div>
        <div class="k">Industry trend${ind.etf ? ` (${esc(ind.etf)})` : ""}</div></div>
    </div>
    <p class="muted" style="margin:10px 0 6px;font-size:.85rem">${esc(s.summary || "")}</p>
    ${items || `<p class="muted">No recent headlines returned for this ticker.</p>`}
    <p class="muted" style="margin-top:8px;font-size:.78rem">${esc(news.note || "")}</p>
  </div>`;
}

function renderQuantChecks(r) {
  const q = r.quant_checks;
  if (!q) return "";
  const p = q.piotroski, z = q.altman, vh = q.valuation_history;
  if (!p && !z && !vh) return "";
  const zoneColor = zn => zn === "Safe" ? PAL.goodText : zn === "Grey" ? PAL.warnText : PAL.badText;
  const fColor = fp => fp.score >= 7 ? PAL.goodText : fp.score >= 5 ? PAL.warnText : PAL.badText;
  const pctColor = v => v <= 0.45 ? PAL.goodText : v <= 0.7 ? PAL.warnText : PAL.badText;

  const tiles = [];
  if (p) tiles.push(`<div class="mini-score"><div class="v" style="color:${fColor(p)}">${p.score}/${p.out_of}</div>
    <div class="k">Piotroski F-Score (${esc(p.verdict)})</div></div>`);
  if (z && !z.skipped && z.score != null) tiles.push(`<div class="mini-score">
    <div class="v" style="color:${zoneColor(z.zone)}">${z.score}</div>
    <div class="k">Altman Z-Score — ${esc(z.zone)} zone</div></div>`);
  for (const key of ["pe", "ps"]) {
    if (vh && vh[key + "_percentile"] != null) {
      const pct = vh[key + "_percentile"];
      tiles.push(`<div class="mini-score"><div class="v" style="color:${pctColor(pct)}">${Math.round(pct * 100)}%</div>
        <div class="k">${key.toUpperCase()} percentile vs own ${vh.years}-yr range
        (${vh[key + "_range"][0]}–${vh[key + "_range"][1]}, now ${vh[key + "_current"]})</div></div>`);
    }
  }
  if (!tiles.length && !(z && z.skipped)) return "";

  return `<div class="card" data-tab="score"><h2>Quant health checks</h2>
    <div class="mini-scores">${tiles.join("")}</div>
    <div class="two-col" style="margin-top:14px">
      <div>${p ? `<h3 class="sub">F-Score components</h3>
        <table>${p.checks.map(c => `<tr><td>${c.pass ? "✅" : "❌"} ${esc(c.check)}</td>
          <td class="muted">${esc(c.group)}</td></tr>`).join("")}</table>
        <p class="muted" style="margin-top:6px;font-size:.8rem">${esc(p.note)}</p>` : ""}</div>
      <div>${z && !z.skipped && z.components ? `<h3 class="sub">Z-Score components</h3>
        <table><tr><th>Component</th><th class="num">Value</th><th class="num">Weighted</th></tr>
        ${z.components.map(c => `<tr><td>${esc(c.component)}</td>
          <td class="num">${c.value ?? "n/a"}</td><td class="num">${c.weighted ?? "—"}</td></tr>`).join("")}</table>` : ""}
        ${z ? `<p class="muted" style="margin-top:6px;font-size:.8rem">${esc(z.note)}</p>` : ""}</div>
    </div></div>`;
}

function renderCommentary(ec) {
  if (!ec || !ec.available) {
    return `<p class="muted" style="font-size:.85rem">${esc(ec?.note || "Not available.")}</p>`;
  }
  const toneClass = ec.tone === "Bullish" ? "good" : ec.tone === "Bearish" ? "bad"
    : ec.tone === "Cautious" ? "warn" : "";
  const topics = Object.entries(ec.topics || {}).slice(0, 6)
    .map(([k, v]) => `${esc(k)} (${v})`).join(" · ");
  return `
    <div class="badge-row" style="margin-bottom:8px">
      <span class="pill ${toneClass}"><span class="k">Tone:</span> ${esc(ec.tone)}</span>
      <span class="pill"><span class="k">Call:</span> ${esc(ec.quarter)} ${esc(ec.date || "")}</span>
      ${ec.tone_change ? `<span class="pill"><span class="k">Vs prior:</span> ${esc(ec.tone_change)}</span>` : ""}
    </div>
    <p class="muted" style="font-size:.85rem">${ec.bullish_signals} bullish vs ${ec.cautious_signals}
      cautious keyword signals.${topics ? " Hot topics: " + topics + "." : ""}</p>
    ${(ec.guidance_excerpts || []).map(x =>
      `<p style="font-size:.85rem;border-left:2px solid var(--border);padding-left:10px;margin-top:6px">“${esc(x)}”</p>`).join("")}
    <p class="muted" style="font-size:.78rem;margin-top:6px">${esc(ec.note)}</p>`;
}

function renderPeerTable(r) {
  const pc = r.peer_comparison;
  if (!pc.rows || !pc.rows.length) return `<p class="muted">No peer data available.</p>`;
  const peerTks = pc.peers.map(p => p.ticker);
  return `<div style="overflow-x:auto"><table>
    <tr><th>Metric</th><th class="num">${esc(r.ticker)}</th><th class="num">Peer median</th>
    ${peerTks.map(t => `<th class="num">${esc(t)}</th>`).join("")}<th>vs peers</th></tr>
    ${pc.rows.map(row => {
      const f = v => row.format === "pct" ? fmtPct(v) : (v == null ? "n/a" : v.toFixed(1) + (row.format === "x" ? "x" : ""));
      return `<tr><td>${esc(row.label)}</td>
        <td class="num"><strong>${f(row.company)}</strong></td>
        <td class="num">${f(row.peer_median)}</td>
        ${peerTks.map(t => `<td class="num muted">${f(row.peer_values[t])}</td>`).join("")}
        <td>${row.better == null ? "" : row.better
          ? '<span class="better">better</span>' : '<span class="worse">worse</span>'}</td></tr>`;
    }).join("")}</table></div>`;
}

/* ---------- charts ---------- */
const CHART_DEFAULTS = {
  color: PAL.tick,
  scales: {
    x: { ticks: { color: PAL.tick, maxTicksLimit: 8 }, grid: { color: PAL.grid } },
    y: { ticks: { color: PAL.tick }, grid: { color: PAL.grid } },
  },
  plugins: { legend: { labels: { color: PAL.legend, boxWidth: 12 } } },
  maintainAspectRatio: false,
  responsive: true,
  animation: false,
};
if (typeof Chart !== "undefined") {
  Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
  Chart.defaults.datasets.bar.borderRadius = 3;   // rounded data-ends
  Chart.defaults.datasets.bar.maxBarThickness = 36;
}

function annualSeries(r, key) {
  const s = r.series[key];
  if (!s || !s.length) return null;
  return { labels: s.map(d => d.date.slice(0, 4)), values: s.map(d => d.value) };
}

function addBarChart(grid, title, datasets, labels, unit = "usd") {
  if (!datasets.length || !labels) return;
  const box = document.createElement("div");
  box.className = "chart-box";
  box.innerHTML = `<h3>${esc(title)}</h3><div class="chart-wrap"><canvas></canvas></div>`;
  grid.appendChild(box);
  const tickFmt = { pct: v => (v * 100).toFixed(0) + "%", x: v => v + "x", usd: fmtUSD };
  charts.push(new Chart($("canvas", box), {
    type: "bar",
    data: { labels, datasets },
    options: {
      ...CHART_DEFAULTS,
      scales: {
        ...CHART_DEFAULTS.scales,
        y: {
          ...CHART_DEFAULTS.scales.y,
          ticks: {
            color: PAL.tick,
            callback: tickFmt[unit] || tickFmt.usd,
          },
        },
      },
    },
  }));
}

function renderCharts(r) {
  if (typeof Chart === "undefined") {
    // Chart.js CDN unreachable (offline) — degrade gracefully, never crash the report
    const msg = `<p class="muted" style="padding:20px">Charts unavailable — the Chart.js
      library could not be loaded (offline?). All data is still shown in the tables above.</p>`;
    $("#price-chart-box .chart-wrap").innerHTML = msg;
    $("#chart-grid").innerHTML = msg;
    return;
  }
  // price chart
  const ps = r.momentum.price_series || [];
  if (ps.length) {
    const byDate = {};
    (r.momentum.ma50_series || []).forEach(d => { (byDate[d.date] ||= {}).ma50 = d.value; });
    (r.momentum.ma200_series || []).forEach(d => { (byDate[d.date] ||= {}).ma200 = d.value; });
    charts.push(new Chart($("#ch-price"), {
      type: "line",
      data: {
        labels: ps.map(d => d.date),
        datasets: [
          { label: "Close", data: ps.map(d => d.close), borderColor: PAL.accent, borderWidth: 2, pointRadius: 0 },
          { label: "50-day MA", data: ps.map(d => byDate[d.date]?.ma50 ?? null), borderColor: PAL.s3, borderWidth: 1.2, pointRadius: 0 },
          { label: "200-day MA", data: ps.map(d => byDate[d.date]?.ma200 ?? null), borderColor: PAL.s4, borderWidth: 1.2, pointRadius: 0 },
        ],
      },
      options: { ...CHART_DEFAULTS, interaction: { intersect: false, mode: "index" } },
    }));
  }

  const grid = $("#chart-grid");
  grid.innerHTML = "";
  const rev = annualSeries(r, "revenue"), ni = annualSeries(r, "net_income");
  const gp = annualSeries(r, "gross_profit"), oi = annualSeries(r, "operating_income");
  const ebitda = annualSeries(r, "ebitda"), eps = annualSeries(r, "diluted_eps") || annualSeries(r, "eps");
  const ocf = annualSeries(r, "ocf"), fcf = annualSeries(r, "fcf");
  const cash = annualSeries(r, "cash"), debt = annualSeries(r, "total_debt");
  const shares = annualSeries(r, "shares"), sbc = annualSeries(r, "sbc");

  if (rev) addBarChart(grid, "Revenue / Gross profit / Operating income", [
    { label: "Revenue", data: rev.values, backgroundColor: PAL.s1 },
    gp ? { label: "Gross profit", data: gp.values, backgroundColor: PAL.s2 } : null,
    oi ? { label: "Operating income", data: oi.values, backgroundColor: PAL.s3 } : null,
  ].filter(Boolean), rev.labels);

  if (ni) addBarChart(grid, "Net income / EBITDA", [
    { label: "Net income", data: ni.values, backgroundColor: ni.values.map(v => v >= 0 ? PAL.good : PAL.bad) },
    ebitda ? { label: "EBITDA", data: ebitda.values, backgroundColor: PAL.s1 } : null,
  ].filter(Boolean), ni.labels);

  if (ocf || fcf) addBarChart(grid, "Operating cash flow / Free cash flow", [
    ocf ? { label: "Operating CF", data: ocf.values, backgroundColor: PAL.s1 } : null,
    fcf ? { label: "Free cash flow", data: fcf.values, backgroundColor: fcf.values.map(v => v >= 0 ? PAL.good : PAL.bad) } : null,
  ].filter(Boolean), (ocf || fcf).labels);

  if (rev && gp) {
    const margins = [];
    if (gp) margins.push({ label: "Gross margin", data: gp.values.map((v, i) => v / rev.values[i]), backgroundColor: PAL.s2 });
    if (oi) margins.push({ label: "Operating margin", data: oi.values.map((v, i) => v / rev.values[i]), backgroundColor: PAL.s1 });
    if (ni && ni.labels.length === rev.labels.length)
      margins.push({ label: "Net margin", data: ni.values.map((v, i) => v / rev.values[i]), backgroundColor: PAL.s3 });
    addBarChart(grid, "Margins over time", margins, rev.labels, "pct");
  }

  if (cash || debt) addBarChart(grid, "Cash vs total debt", [
    cash ? { label: "Cash", data: cash.values, backgroundColor: PAL.good } : null,
    debt ? { label: "Total debt", data: debt.values, backgroundColor: PAL.bad } : null,
  ].filter(Boolean), (cash || debt).labels);

  if (shares || sbc) addBarChart(grid, "Shares outstanding / SBC", [
    shares ? { label: "Shares outstanding", data: shares.values, backgroundColor: PAL.s3 } : null,
    sbc ? { label: "Stock-based comp", data: sbc.values, backgroundColor: PAL.s2 } : null,
  ].filter(Boolean), (shares || sbc).labels);

  const qrev = r.qseries.q_revenue;
  if (qrev && qrev.length) addBarChart(grid, "Quarterly revenue", [
    { label: "Revenue (Q)", data: qrev.map(d => d.value), backgroundColor: PAL.s1 },
  ], qrev.map(d => d.date.slice(0, 7)));

  if (eps) addBarChart(grid, "Diluted EPS", [
    { label: "EPS", data: eps.values, backgroundColor: eps.values.map(v => v >= 0 ? PAL.good : PAL.bad) },
  ], eps.labels);

  // valuation multiples at each fiscal-year end (from valuation_history)
  const vh = r.quant_checks?.valuation_history;
  if (vh?.points?.length >= 2) {
    const labels = vh.points.map(p => p.date.slice(0, 4));
    const sets = [];
    if (vh.points.some(p => p.pe != null))
      sets.push({ label: "P/E (FY-end)", data: vh.points.map(p => p.pe ?? null), backgroundColor: PAL.s1 });
    if (vh.points.some(p => p.ps != null))
      sets.push({ label: "P/S (FY-end)", data: vh.points.map(p => p.ps ?? null), backgroundColor: PAL.s2 });
    if (sets.length) {
      addBarChart(grid, "Valuation multiples over time", sets, labels, "x");
    }
  }

  if (!grid.children.length) {
    grid.innerHTML = `<p class="muted" style="padding:16px">No historical statement series
      available to chart for this ticker — see the Raw Data section for what was returned.</p>`;
  }
}

/* ---------- backtest ---------- */
async function runBacktest(tk) {
  const card = $("#backtest-card");
  card.classList.remove("hidden");
  $("#backtest-body").innerHTML = `<p class="muted">Running point-in-time simulation…</p>`;
  card.scrollIntoView({ behavior: "smooth" });
  try {
    const b = await api(`/api/backtest/${tk}`);
    if (b.error) { $("#backtest-body").innerHTML = `<p class="muted">${esc(b.error)}</p>`; return; }
    const stat = (label, s) => s ? `<div class="mini-score">
      <div class="v" style="color:${s.avg >= 0 ? PAL.goodText : PAL.badText}">${fmtPct(s.avg, true)}</div>
      <div class="k">${esc(label)} avg vs S&amp;P (n=${s.n}, win ${fmtPct(s.win_rate)}, median ${fmtPct(s.median, true)})</div></div>` : "";
    $("#backtest-body").innerHTML = `
      <div class="mini-scores">
        ${stat("Buy-rated signals", b.buy_stats_vs_spy)}
        ${stat("Sell-rated signals", b.sell_stats_vs_spy)}
        ${stat("All signals", b.all_stats_vs_spy)}
        <div class="mini-score"><div class="v">${b.false_buy_signals} / ${b.false_sell_signals}</div>
          <div class="k">False buys / false sells (±5% vs S&amp;P, 1y)</div></div>
        ${b.avg_buy_drawdown_1y != null ? `<div class="mini-score">
          <div class="v" style="color:${PAL.badText}">${fmtPct(b.avg_buy_drawdown_1y)}</div>
          <div class="k">Avg max drawdown in year after Buy signals</div></div>` : ""}
        ${b.worst_drawdown_1y != null ? `<div class="mini-score">
          <div class="v" style="color:${PAL.badText}">${fmtPct(b.worst_drawdown_1y)}</div>
          <div class="k">Worst 1-yr drawdown after any signal</div></div>` : ""}
      </div>
      <h3 class="sub" style="margin-top:14px">Historical signals</h3>
      <div style="overflow-x:auto"><table>
        <tr><th>Signal date</th><th>Statement</th><th class="num">Score</th><th>Rating</th>
        <th class="num">Price</th><th class="num">+1m</th><th class="num">+3m</th>
        <th class="num">+6m</th><th class="num">+1y</th><th class="num">+1y vs SPY</th></tr>
        ${b.signals.map(s => {
          const fr = s.forward_returns;
          const cell = k => fr[k] == null ? "<td class='num muted'>—</td>"
            : `<td class="num ${fr[k] >= 0 ? "pos" : "neg"}">${fmtPct(fr[k], true)}</td>`;
          return `<tr><td>${esc(s.as_of)}</td><td class="muted">${esc(s.statement_date)}</td>
            <td class="num">${s.score}</td><td>${esc(s.rating)}</td>
            <td class="num">$${s.price}</td>${cell("1m")}${cell("3m")}${cell("6m")}${cell("1y")}${cell("1y_vs_spy")}</tr>`;
        }).join("")}</table></div>
      <h3 class="sub" style="margin-top:12px">Methodology &amp; limitations</h3>
      <ul class="plain">${b.methodology.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>`;
  } catch (err) {
    $("#backtest-body").innerHTML = `<p class="muted">Backtest failed: ${esc(err.message)}</p>`;
  }
}

async function loadHistory(tk) {
  const card = $("#history-card");
  card.classList.remove("hidden");
  const h = await api(`/api/history/${tk}`);
  $("#history-body").innerHTML = h.history.length ? `<table>
    <tr><th>Date</th><th>Model</th><th>Rating</th><th class="num">Score</th><th>Confidence</th><th class="num">Price</th></tr>
    ${h.history.map(x => `<tr><td>${esc(x.generated_at.slice(0, 16).replace("T", " "))}</td>
      <td class="muted">${esc(x.model_version)}</td><td>${esc(x.rating)}</td>
      <td class="num">${x.score}</td><td>${esc(x.confidence)}</td>
      <td class="num">${x.price ? "$" + x.price.toFixed(2) : "n/a"}</td></tr>`).join("")}</table>`
    : `<p class="muted">No prior ratings recorded for ${esc(tk)}.</p>`;
  card.scrollIntoView({ behavior: "smooth" });
}

/* ---------- compare ---------- */
$("#compare-form").addEventListener("submit", async e => {
  e.preventDefault();
  const raw = $("#compare-input").value.trim();
  if (!raw) return;
  setStatus("Comparing — analyzing each ticker (this can take ~30s)…");
  try {
    const data = await api(`/api/compare?tickers=${encodeURIComponent(raw)}`);
    compareData = data.results;
    $("#compare-sort-row").classList.remove("hidden");
    renderCompare();
    const errs = Object.entries(data.errors || {});
    setStatus(errs.length ? `Some tickers failed: ${errs.map(([t, m]) => `${t} (${m})`).join("; ")}` : "", "error");
    if (!errs.length) setStatus("");
  } catch (err) {
    setStatus(`Compare failed: ${err.message}`, "error");
  }
});
$("#compare-sort").addEventListener("change", renderCompare);

function renderCompare() {
  const key = $("#compare-sort").value;
  const val = r => ({
    total_score: r.total_score,
    expected_upside: r.expected_upside ?? -99,
    risk: -(r.metrics.net_debt_to_ebitda ?? 99),
    valuation: -(r.metrics.forward_pe ?? r.metrics.pe ?? 9999),
    growth: r.metrics.rev_growth_1y ?? -99,
    fcf: r.metrics.fcf_yield ?? -99,
    momentum: r.momentum_12m ?? -99,
    confidence: { High: 3, Medium: 2, Low: 1 }[r.confidence] || 0,
  }[key]);
  const rows = [...compareData].sort((a, b) => val(b) - val(a));
  const metric = (label, fn) => `<tr><td>${label}</td>${rows.map(r =>
    `<td class="num">${fn(r)}</td>`).join("")}</tr>`;
  $("#compare-results").innerHTML = rows.length ? `<div style="overflow-x:auto"><table>
    <tr><th>Metric</th>${rows.map(r => `<th class="num">
      <button class="link-btn" onclick="analyzeTicker('${esc(r.ticker)}')">${esc(r.ticker)}</button></th>`).join("")}</tr>
    ${metric("Rating", r => `<span class="pill ${cls(r.final_rating)}" style="color:#fff;border:none">${esc(r.final_rating)}</span>`)}
    ${metric("Total score", r => `<strong style="color:${scoreColor(r.total_score)}">${r.total_score}</strong>`)}
    ${metric("Confidence", r => esc(r.confidence))}
    ${metric("Fundamental", r => esc(r.fundamental_rating))}
    ${metric("Timing", r => esc(r.timing_rating))}
    ${metric("Risk/Reward", r => esc(r.risk_reward_grade))}
    ${metric("Company type", r => esc(r.company_type))}
    ${metric("Suitability", r => esc(r.position_suitability))}
    ${metric("Price", r => r.price ? "$" + r.price.toFixed(2) : "n/a")}
    ${metric("Base-case upside", r => fmtPct(r.expected_upside, true))}
    ${metric("Revenue growth", r => fmtPct(r.metrics.rev_growth_1y))}
    ${metric("Gross margin", r => fmtPct(r.metrics.gross_margin))}
    ${metric("Operating margin", r => fmtPct(r.metrics.operating_margin))}
    ${metric("ROE", r => fmtPct(r.metrics.roe))}
    ${metric("P/E (fwd)", r => fmtX(r.metrics.forward_pe))}
    ${metric("P/S", r => fmtX(r.metrics.ps))}
    ${metric("EV/EBITDA", r => fmtX(r.metrics.ev_ebitda))}
    ${metric("FCF yield", r => fmtPct(r.metrics.fcf_yield))}
    ${metric("Net debt/EBITDA", r => fmtX(r.metrics.net_debt_to_ebitda))}
    ${metric("Dividend yield", r => fmtPct(r.metrics.dividend_yield))}
    ${metric("12-mo momentum", r => fmtPct(r.momentum_12m, true))}
  </table></div>` : "<p class='muted'>No results.</p>";
}

/* ---------- watchlist ---------- */
let wlData = [];

async function loadWatchlist() {
  const body = $("#watchlist-body");
  body.innerHTML = `<p class="muted">Loading…</p>`;
  const data = await api("/api/watchlist");
  wlData = data.watchlist;
  renderWatchlist();
}

function wlSortValue(w, key) {
  const l = w.last || {}, s = (l.summary || {}), sc = s.screener || {};
  return {
    score: l.score ?? -1,
    upside: s.expected_upside ?? -99,
    growth: sc.rev_growth ?? -99,
    fcf: sc.fcf_yield ?? -99,
    valuation: -(sc.forward_pe ?? sc.pe ?? 9999),
    risk: -(sc.net_debt_to_ebitda ?? 99),
    momentum: sc.momentum_12m ?? -99,
    confidence: { High: 3, Medium: 2, Low: 1 }[l.confidence] || 0,
    added: w.added_at || "",
  }[key];
}

function renderWatchlist() {
  const body = $("#watchlist-body");
  if (!wlData.length) {
    body.innerHTML = `<p class="muted">Watchlist is empty. Analyze a stock and click "Add to watchlist".</p>`;
    return;
  }
  const key = $("#wl-sort").value;
  const list = [...wlData].sort((a, b) => {
    const va = wlSortValue(a, key), vb = wlSortValue(b, key);
    return typeof va === "string" ? String(vb).localeCompare(String(va)) : vb - va;
  });
  body.innerHTML = `<div style="overflow-x:auto"><table>
    <tr><th>Ticker</th><th>Last rating</th><th class="num">Score</th><th class="num">Δ vs prior</th><th>Confidence</th>
    <th class="num">Upside</th><th class="num">Growth</th><th class="num">FCF yld</th><th class="num">Fwd P/E</th>
    <th class="num">12-mo</th><th class="num">Price</th><th>Rated</th><th style="min-width:180px">Notes</th><th></th></tr>
    ${list.map(w => {
      const l = w.last || {}, s = l.summary || {}, p = w.prev, sc = (l.summary || {}).screener || {};
      let delta = "<span class='muted'>—</span>";
      if (p && l.score != null && p.score != null) {
        const d = l.score - p.score;
        const chg = p.rating !== l.rating ? ` ${esc(p.rating)}→${esc(l.rating)}` : "";
        delta = Math.abs(d) < 0.05 ? `<span class="muted">0${chg}</span>`
          : `<span class="${d > 0 ? "delta-up" : "delta-down"}">${d > 0 ? "▲" : "▼"}${Math.abs(d).toFixed(1)}${chg}</span>`;
      }
      return `<tr>
        <td><button class="link-btn" onclick="analyzeTicker('${esc(w.ticker)}')">${esc(w.ticker)}</button></td>
        <td>${l.rating ? `<span class="pill ${cls(l.rating)}" style="color:#fff;border:none">${esc(l.rating)}</span>` : "<span class='muted'>not rated yet</span>"}</td>
        <td class="num">${l.score ?? ""}</td><td class="num">${delta}</td><td>${esc(l.confidence || "")}</td>
        <td class="num">${s.expected_upside != null ? fmtPct(s.expected_upside, true) : ""}</td>
        <td class="num">${sc.rev_growth != null ? fmtPct(sc.rev_growth) : ""}</td>
        <td class="num">${sc.fcf_yield != null ? fmtPct(sc.fcf_yield) : ""}</td>
        <td class="num">${sc.forward_pe != null ? sc.forward_pe.toFixed(1) + "x" : ""}</td>
        <td class="num">${sc.momentum_12m != null ? fmtPct(sc.momentum_12m, true) : ""}</td>
        <td class="num">${l.price ? "$" + l.price.toFixed(2) : ""}</td>
        <td class="muted">${l.generated_at ? esc(l.generated_at.slice(0, 10)) : ""}</td>
        <td><input class="wl-note-input" data-tk="${esc(w.ticker)}" value="${esc(w.notes || "")}"
          placeholder="Add a note…"></td>
        <td><button class="link-btn" data-remove="${esc(w.ticker)}">remove</button></td></tr>`;
    }).join("")}</table></div>
    <p class="muted" style="margin-top:8px">Notes save on Enter or when the field loses focus.</p>`;
  $$(".wl-note-input", body).forEach(inp => {
    const save = () => api(`/api/watchlist/${inp.dataset.tk}/note`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: inp.value }),
    });
    inp.addEventListener("change", save);
    inp.addEventListener("keydown", e => { if (e.key === "Enter") { save(); inp.blur(); } });
  });
  $$("[data-remove]", body).forEach(btn => btn.addEventListener("click", async () => {
    await api(`/api/watchlist/${btn.dataset.remove}`, { method: "DELETE" });
    loadWatchlist();
  }));
}

$("#wl-sort").addEventListener("change", renderWatchlist);

$("#wl-refresh").addEventListener("click", async () => {
  const data = await api("/api/watchlist");
  const tks = data.watchlist.map(w => w.ticker);
  if (!tks.length) return;
  const btn = $("#wl-refresh");
  btn.disabled = true;
  for (let i = 0; i < tks.length; i++) {
    btn.textContent = `⟳ Refreshing ${tks[i]} (${i + 1}/${tks.length})…`;
    try { await api(`/api/analyze/${tks[i]}`); } catch { /* keep going */ }
  }
  btn.disabled = false;
  btn.textContent = "⟳ Refresh all ratings";
  loadWatchlist();
});

// Charts created while the tab is backgrounded can measure a 0-width container;
// re-measure whenever the tab becomes visible or the window resizes.
const resizeCharts = () => charts.forEach(c => { try { c.resize(); } catch { /* destroyed */ } });
document.addEventListener("visibilitychange", () => { if (!document.hidden) resizeCharts(); });
window.addEventListener("focus", resizeCharts);

window.analyzeTicker = analyzeTicker;
