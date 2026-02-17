// ── State ──
let currentView = "overview"; // "overview" or filename
let currentTab = "uebersicht";
let overviewData = null;
let currentClient = null;
let txFilter = "ALL";
let txPage = 0;
const TX_PER_PAGE = 30;
let charts = {};

// Finance state
let financeData = null;
let financeTransactions = [];
let finFilter = { search: "", kategorie: "", art: "", konto: "", startDatum: "", endDatum: "" };
let finSort = { field: "datum", dir: "desc" };
let finPage = 0;
const FIN_PER_PAGE = 30;

// ── API ──
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ── Sidebar Toggle ──
function toggleSidebar() {
  const sidebar = document.getElementById("sidebar");
  sidebar.classList.toggle("collapsed");
  document.body.classList.toggle("sidebar-collapsed");
  localStorage.setItem("sidebarCollapsed", sidebar.classList.contains("collapsed"));
}

function restoreSidebar() {
  if (localStorage.getItem("sidebarCollapsed") === "true") {
    document.getElementById("sidebar").classList.add("collapsed");
    document.body.classList.add("sidebar-collapsed");
  }
}

// ── Init ──
(async function init() {
  restoreSidebar();
  await loadOverview();
  updateSyncStatus();
  setInterval(updateSyncStatus, 60000);
})();

// ── Navigation ──
async function loadOverview() {
  overviewData = await fetchJSON("/api/overview");
  buildSidebar();
  if (currentView === "overview") renderOverview();
}

function showOverview() {
  currentView = "overview";
  currentTab = "uebersicht";
  setActiveNav("navOverview");
  renderOverview();
}

async function showClient(filename) {
  currentView = filename;
  currentTab = "uebersicht";
  txFilter = "ALL";
  txPage = 0;
  setActiveNav("nav-" + filename);
  document.getElementById("app").innerHTML = '<div class="loading"><div class="spinner"></div> Laden...</div>';
  currentClient = await fetchJSON(`/api/clients/${encodeURIComponent(filename)}`);
  renderClientView();
}

async function switchTab(tab) {
  currentTab = tab;
  if (tab === "ausgaben" && !financeData) {
    document.getElementById("tabContent") && (document.getElementById("tabContent").innerHTML = '<div class="loading"><div class="spinner"></div> Laden...</div>');
    try {
      financeData = await fetchJSON("/api/finance/overview");
      financeTransactions = await fetchJSON("/api/finance/transactions");
    } catch (e) {
      document.getElementById("tabContent") && (document.getElementById("tabContent").innerHTML = `<div class="alert alert-error">Fehler: ${esc(e.message)}</div>`);
      return;
    }
  }
  renderClientView();
}

function setActiveNav(id) {
  document.querySelectorAll(".nav-item, .nav-client").forEach(el => el.classList.remove("active"));
  const el = document.getElementById(id);
  if (el) el.classList.add("active");
}

function buildSidebar() {
  if (!overviewData) return;
  const nav = document.getElementById("clientNav");
  nav.innerHTML = overviewData.clients.map(c => `
    <div class="nav-client ${currentView === c.filename ? 'active' : ''}"
         id="nav-${esc(c.filename)}"
         onclick="showClient('${esc(c.filename)}')">
      <span class="client-name">${esc(c.client_name)}</span>
      <span class="client-meta">
        <span>${fmt(c.total_value)} ${esc(c.base_currency)}</span>
        <span class="${changeClass(c.gain_loss_pct)}">${fmtPct(c.gain_loss_pct)}</span>
      </span>
    </div>
  `).join("");
}

async function triggerSync() {
  document.getElementById("syncStatus").textContent = "Syncing...";
  try {
    await fetch("/api/sync/trigger", { method: "POST" });
    await loadOverview();
  } catch (e) {
    document.getElementById("syncStatus").textContent = "Fehler";
  }
}

async function updateSyncStatus() {
  try {
    const s = await fetchJSON("/api/sync/status");
    const el = document.getElementById("syncStatus");
    el.textContent = s.last_sync
      ? `Sync: ${new Date(s.last_sync).toLocaleTimeString("de-CH")}`
      : "Lokal";
  } catch {}
}

// ── Formatting ──
function fmt(n, d = 2) {
  return new Intl.NumberFormat("de-CH", { minimumFractionDigits: d, maximumFractionDigits: d }).format(n);
}
function fmtPct(n) { return `${n >= 0 ? "+" : ""}${fmt(n, 1)}%`; }
function changeClass(n) { return n >= 0 ? "positive" : "negative"; }
function fmtDate(d) { return new Date(d).toLocaleDateString("de-CH"); }
function esc(s) { if (!s) return ""; const e = document.createElement("span"); e.textContent = s; return e.innerHTML; }
function truncate(s, n) { return s.length > n ? s.substring(0, n) + "..." : s; }
function txBadge(type) {
  const cls = type.includes("PURCHASE") || type.includes("INBOUND") ? "badge-purchase"
    : type.includes("SALE") || type.includes("OUTBOUND") ? "badge-sale"
    : type.includes("DIVIDEND") ? "badge-dividend"
    : type.includes("DEPOSIT") ? "badge-deposit"
    : type.includes("FEE") || type.includes("TAX") ? "badge-fee" : "badge-other";
  return `<span class="badge ${cls}">${txLabel(type)}</span>`;
}
function txLabel(t) {
  return ({PURCHASE:"Kauf",SALE:"Verkauf",INBOUND_DELIVERY:"Einlieferung",OUTBOUND_DELIVERY:"Auslieferung",
    SECURITY_TRANSFER:"Transfer",CASH_TRANSFER:"Umbuchung",DEPOSIT:"Einzahlung",REMOVAL:"Auszahlung",
    DIVIDEND:"Dividende",INTEREST:"Zinsen",INTEREST_CHARGE:"Zinsbelastung",TAX:"Steuer",
    TAX_REFUND:"Steuererstattung",FEE:"Gebühr",FEE_REFUND:"Gebührenerstattung"})[t] || t;
}

const COLORS = ["#4f8cff","#22c55e","#ef4444","#eab308","#a855f7","#06b6d4","#f97316","#ec4899","#14b8a6","#8b5cf6","#f59e0b","#3b82f6","#10b981","#f43f5e","#6366f1"];

function destroyCharts() { Object.values(charts).forEach(c => c.destroy()); charts = {}; }

function heatmapColor(v) {
  if (v > 5) return "rgba(34,197,94,0.7)";
  if (v > 2) return "rgba(34,197,94,0.4)";
  if (v > 0) return "rgba(34,197,94,0.2)";
  if (v > -2) return "rgba(239,68,68,0.2)";
  if (v > -5) return "rgba(239,68,68,0.4)";
  return "rgba(239,68,68,0.7)";
}

// ════════════════════════════════════════
// OVERVIEW
// ════════════════════════════════════════
function renderOverview() {
  destroyCharts();
  const d = overviewData;
  document.getElementById("app").innerHTML = `
    <div class="page-header"><h2>Gesamtübersicht</h2></div>
    <div class="stats-row">
      <div class="stat-card">
        <div class="label">Gesamtvermögen</div>
        <div class="value">${fmt(d.total_value)}</div>
        <div class="sub ${changeClass(d.total_gain_loss)}">${fmtPct(d.total_gain_loss_pct)} (${fmt(d.total_gain_loss)})</div>
      </div>
      <div class="stat-card"><div class="label">Investiert</div><div class="value">${fmt(d.total_invested)}</div></div>
      <div class="stat-card"><div class="label">Dividenden</div><div class="value">${fmt(d.total_dividends)}</div></div>
      <div class="stat-card"><div class="label">Kunden</div><div class="value">${d.client_count}</div></div>
    </div>
    <div class="charts-row">
      <div class="chart-card"><h3>Top Holdings</h3><canvas id="chHoldings"></canvas></div>
      <div class="chart-card"><h3>Währungsverteilung</h3><canvas id="chCurrency"></canvas></div>
    </div>
    <div class="client-grid">
      ${d.clients.map(c => `
        <div class="client-card" onclick="showClient('${esc(c.filename)}')">
          <div class="name">${esc(c.client_name)}</div>
          <div class="metrics">
            <div><div class="metric-label">Wert</div><div class="metric-value">${fmt(c.total_value)} ${esc(c.base_currency)}</div></div>
            <div><div class="metric-label">Performance</div><div class="metric-value ${changeClass(c.gain_loss_pct)}">${fmtPct(c.gain_loss_pct)}</div></div>
            <div><div class="metric-label">Investiert</div><div class="metric-value">${fmt(c.total_invested)}</div></div>
            <div><div class="metric-label">Dividenden</div><div class="metric-value">${fmt(c.dividends_total)}</div></div>
          </div>
        </div>`).join("")}
    </div>
    <div class="table-card"><h3>Letzte Transaktionen</h3>
      <table><thead><tr><th>Datum</th><th>Typ</th><th>Wertpapier</th><th class="text-right">Betrag</th><th class="text-right">Anteile</th></tr></thead>
      <tbody>${d.recent_transactions.slice(0,15).map(t => `<tr><td>${fmtDate(t.date)}</td><td>${txBadge(t.type)}</td><td>${esc(t.security_name||t.account||"-")}</td><td class="text-right text-mono">${fmt(t.amount)} ${esc(t.currency)}</td><td class="text-right text-mono">${t.shares?fmt(t.shares,4):"-"}</td></tr>`).join("")}</tbody></table>
    </div>`;
  // Charts
  if (d.top_holdings.length) {
    charts.h = new Chart(document.getElementById("chHoldings"), {type:"doughnut",data:{labels:d.top_holdings.slice(0,10).map(h=>truncate(h.security.name,22)),datasets:[{data:d.top_holdings.slice(0,10).map(h=>h.current_value),backgroundColor:COLORS,borderWidth:0}]},options:{responsive:true,plugins:{legend:{position:"right",labels:{color:"#8b8fa3",font:{size:10}}}}}});
  }
  const cur = Object.entries(d.currency_breakdown);
  if (cur.length) {
    charts.c = new Chart(document.getElementById("chCurrency"), {type:"doughnut",data:{labels:cur.map(([k])=>k),datasets:[{data:cur.map(([,v])=>v),backgroundColor:COLORS,borderWidth:0}]},options:{responsive:true,plugins:{legend:{position:"right",labels:{color:"#8b8fa3",font:{size:10}}}}}});
  }
}

// ════════════════════════════════════════
// CLIENT VIEW
// ════════════════════════════════════════
async function renderClientView() {
  destroyCharts();
  const c = currentClient;
  const tabs = [
    ["uebersicht","Übersicht"],["vermoegen","Vermögen"],["performance","Performance"],
    ["risiko","Risiko"],["positionen","Positionen"],["transaktionen","Transaktionen"],["dividenden","Dividenden"],["ausgaben","Ausgaben"]
  ];
  document.getElementById("app").innerHTML = `
    <div class="page-header">
      <h2>${esc(c.client_name)}</h2>
      <div class="subtitle">${esc(c.filename)} &middot; ${esc(c.base_currency)}</div>
    </div>
    <div class="tabs">${tabs.map(([id,lbl])=>`<div class="tab ${currentTab===id?'active':''}" onclick="switchTab('${id}')">${lbl}</div>`).join("")}</div>
    <div id="tabContent"></div>`;
  const renderers = {uebersicht:tabOverview,vermoegen:tabVermoegen,performance:tabPerformance,risiko:tabRisiko,positionen:tabPositionen,transaktionen:tabTransaktionen,dividenden:tabDividenden,ausgaben:tabAusgaben};
  await (renderers[currentTab]||tabOverview)(c);
}

// ── Tab: Übersicht ──
function tabOverview(c) {
  document.getElementById("tabContent").innerHTML = `
    <div class="stats-row">
      <div class="stat-card"><div class="label">Gesamtwert</div><div class="value">${fmt(c.total_value)}</div><div class="sub ${changeClass(c.gain_loss)}">${fmtPct(c.gain_loss_pct)} (${fmt(c.gain_loss)})</div></div>
      <div class="stat-card"><div class="label">Investiert</div><div class="value">${fmt(c.total_invested)}</div></div>
      <div class="stat-card"><div class="label">Dividenden</div><div class="value">${fmt(c.dividends_total)}</div></div>
      <div class="stat-card"><div class="label">Gebühren</div><div class="value">${fmt(c.fees_total)}</div></div>
      <div class="stat-card"><div class="label">Rendite p.a.</div><div class="value ${changeClass(c.performance.annual_return)}">${fmtPct(c.performance.annual_return)}</div></div>
      <div class="stat-card"><div class="label">Volatilität</div><div class="value">${fmt(c.performance.volatility,1)}%</div></div>
    </div>
    <div class="charts-row">
      <div class="chart-card"><h3>Holdings</h3><canvas id="chOvHoldings"></canvas></div>
      <div class="chart-card"><h3>Asset Allocation</h3><canvas id="chOvAlloc"></canvas></div>
    </div>
    <div class="table-card"><h3>Letzte Transaktionen</h3>
      <table><thead><tr><th>Datum</th><th>Typ</th><th>Wertpapier</th><th class="text-right">Betrag</th></tr></thead>
      <tbody>${c.recent_transactions.slice(0,10).map(t=>`<tr><td>${fmtDate(t.date)}</td><td>${txBadge(t.type)}</td><td>${esc(t.security_name||"-")}</td><td class="text-right text-mono">${fmt(t.amount)} ${esc(t.currency)}</td></tr>`).join("")}</tbody></table>
    </div>`;
  if (c.holdings.length) {
    charts.oh = new Chart(document.getElementById("chOvHoldings"),{type:"doughnut",data:{labels:c.holdings.slice(0,10).map(h=>truncate(h.security.name,20)),datasets:[{data:c.holdings.slice(0,10).map(h=>h.current_value),backgroundColor:COLORS,borderWidth:0}]},options:{responsive:true,plugins:{legend:{position:"right",labels:{color:"#8b8fa3",font:{size:10}}}}}});
  }
  if (c.asset_allocation.length) {
    charts.oa = new Chart(document.getElementById("chOvAlloc"),{type:"doughnut",data:{labels:c.asset_allocation.map(a=>a.name),datasets:[{data:c.asset_allocation.map(a=>a.value),backgroundColor:c.asset_allocation.map(a=>a.color||COLORS[0]),borderWidth:0}]},options:{responsive:true,plugins:{legend:{position:"right",labels:{color:"#8b8fa3",font:{size:10}}}}}});
  }
}

// ── Tab: Vermögen ──
function tabVermoegen(c) {
  const cashAccounts = c.accounts.filter(a => a.balance > 0);
  document.getElementById("tabContent").innerHTML = `
    <div class="charts-row">
      <div class="chart-card"><h3>Asset Allocation</h3><canvas id="chAlloc"></canvas></div>
      <div class="chart-card"><h3>Währungsverteilung</h3><canvas id="chCurr"></canvas></div>
    </div>
    <div class="table-card"><h3>Vermögensaufstellung</h3>
      <table><thead><tr><th>Kategorie</th><th class="text-right">Wert</th><th class="text-right">Anteil</th><th>Positionen</th></tr></thead>
      <tbody>${c.asset_allocation.map(a=>`
        <tr style="font-weight:600">
          <td><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${a.color};margin-right:6px"></span>${esc(a.name)}</td>
          <td class="text-right text-mono">${fmt(a.value)}</td>
          <td class="text-right text-mono">${fmt(a.percentage,1)}%</td>
          <td>${a.holdings.length} Positionen</td>
        </tr>
        ${a.holdings.map(h=>`<tr><td style="padding-left:2rem;color:var(--text-muted)">${esc(h.security.name)}</td><td class="text-right text-mono">${fmt(h.current_value)} ${esc(h.currency)}</td><td class="text-right text-mono ${changeClass(h.gain_loss_pct)}">${fmtPct(h.gain_loss_pct)}</td><td class="text-mono">${fmt(h.shares,4)} Stk.</td></tr>`).join("")}
      `).join("")}</tbody></table>
    </div>
    ${cashAccounts.length ? `<div class="table-card"><h3>Cash-Bestände</h3>
      <table><thead><tr><th>Konto</th><th>Währung</th><th class="text-right">Saldo</th></tr></thead>
      <tbody>${cashAccounts.map(a=>`<tr><td>${esc(a.name)}</td><td>${esc(a.currency)}</td><td class="text-right text-mono">${fmt(a.balance)}</td></tr>`).join("")}</tbody></table>
    </div>` : ""}`;
  if (c.asset_allocation.length) {
    charts.al = new Chart(document.getElementById("chAlloc"),{type:"doughnut",data:{labels:c.asset_allocation.map(a=>a.name),datasets:[{data:c.asset_allocation.map(a=>a.value),backgroundColor:c.asset_allocation.map(a=>a.color),borderWidth:0}]},options:{responsive:true,plugins:{legend:{position:"right",labels:{color:"#8b8fa3",font:{size:11}}}}}});
  }
  const cur = Object.entries(c.currency_breakdown);
  if (cur.length) {
    charts.cu = new Chart(document.getElementById("chCurr"),{type:"doughnut",data:{labels:cur.map(([k])=>k),datasets:[{data:cur.map(([,v])=>v),backgroundColor:COLORS,borderWidth:0}]},options:{responsive:true,plugins:{legend:{position:"right",labels:{color:"#8b8fa3",font:{size:11}}}}}});
  }
}

// ── Tab: Performance ──
function tabPerformance(c) {
  const p = c.performance;
  document.getElementById("tabContent").innerHTML = `
    <div class="stats-row">
      <div class="stat-card"><div class="label">Gesamtrendite</div><div class="value ${changeClass(p.ttwror)}">${fmtPct(p.ttwror)}</div></div>
      <div class="stat-card"><div class="label">Rendite p.a.</div><div class="value ${changeClass(p.annual_return)}">${fmtPct(p.annual_return)}</div></div>
      <div class="stat-card"><div class="label">YTD</div><div class="value ${changeClass(p.ytd_return)}">${fmtPct(p.ytd_return)}</div></div>
      <div class="stat-card"><div class="label">1 Jahr</div><div class="value ${changeClass(p.return_1y)}">${fmtPct(p.return_1y)}</div></div>
      <div class="stat-card"><div class="label">3 Jahre</div><div class="value ${changeClass(p.return_3y)}">${fmtPct(p.return_3y)}</div></div>
      <div class="stat-card"><div class="label">5 Jahre</div><div class="value ${changeClass(p.return_5y)}">${fmtPct(p.return_5y)}</div></div>
    </div>
    <div class="chart-card chart-full" style="margin-bottom:1rem"><h3>Portfoliowert über Zeit</h3><canvas id="chPerf"></canvas></div>
    ${c.monthly_returns.length ? `<div class="chart-card chart-full" style="margin-bottom:1rem"><h3>Monatliche Renditen (Heatmap)</h3><div id="heatmap"></div></div>` : ""}`;
  // Performance chart
  if (c.value_history.length) {
    charts.pf = new Chart(document.getElementById("chPerf"),{type:"line",data:{labels:c.value_history.map(v=>v.date),datasets:[{label:"Portfoliowert",data:c.value_history.map(v=>v.value),borderColor:"#4f8cff",backgroundColor:"rgba(79,140,255,0.08)",fill:true,borderWidth:1.5,pointRadius:0,tension:0.3}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{ticks:{color:"#8b8fa3",maxTicksLimit:12,font:{size:10}},grid:{display:false}},y:{ticks:{color:"#8b8fa3",callback:v=>fmt(v,0)},grid:{color:"#2a2e3a"}}}}});
  }
  // Heatmap
  if (c.monthly_returns.length) renderHeatmap(c.monthly_returns);
}

function renderHeatmap(data) {
  const years = [...new Set(data.map(d => d.year))].sort();
  const months = ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
  const lookup = {};
  data.forEach(d => { lookup[`${d.year}-${d.month}`] = d.return_pct; });

  let html = `<div class="heatmap" style="grid-template-columns: 60px repeat(12, 1fr)">`;
  // Header
  html += `<div class="heatmap-header"></div>`;
  months.forEach(m => { html += `<div class="heatmap-header">${m}</div>`; });
  // Rows
  years.forEach(y => {
    html += `<div class="heatmap-header" style="text-align:right;padding-right:8px">${y}</div>`;
    for (let m = 1; m <= 12; m++) {
      const v = lookup[`${y}-${m}`];
      if (v !== undefined) {
        html += `<div class="heatmap-cell" style="background:${heatmapColor(v)}" title="${months[m-1]} ${y}: ${fmtPct(v)}">${v > 0 ? "+" : ""}${fmt(v,1)}</div>`;
      } else {
        html += `<div class="heatmap-cell" style="background:var(--card)"></div>`;
      }
    }
  });
  html += `</div>`;
  document.getElementById("heatmap").innerHTML = html;
}

// ── Tab: Risiko ──
function tabRisiko(c) {
  const p = c.performance;
  const holdingsWithRisk = c.holdings.filter(h => h.volatility > 0);
  document.getElementById("tabContent").innerHTML = `
    <div class="stats-row">
      <div class="stat-card"><div class="label">Volatilität (Portfolio)</div><div class="value">${fmt(p.volatility,1)}%</div></div>
      <div class="stat-card"><div class="label">Sharpe Ratio</div><div class="value">${fmt(p.sharpe_ratio,2)}</div></div>
      <div class="stat-card"><div class="label">Max Drawdown</div><div class="value negative">-${fmt(p.max_drawdown,1)}%</div><div class="sub" style="color:var(--text-muted);font-size:0.7rem">${p.max_drawdown_start} → ${p.max_drawdown_end}</div></div>
      <div class="stat-card"><div class="label">Rendite p.a.</div><div class="value ${changeClass(p.annual_return)}">${fmtPct(p.annual_return)}</div></div>
    </div>
    <div class="chart-card chart-full" style="margin-bottom:1rem"><h3>Rendite vs. Volatilität (pro Position)</h3><canvas id="chRisk"></canvas></div>
    <div class="table-card"><h3>Risikokennzahlen pro Position</h3>
      <table><thead><tr><th>Position</th><th>Kategorie</th><th class="text-right">Wert</th><th class="text-right">Volatilität</th><th class="text-right">Rendite p.a.</th><th class="text-right">G/V %</th></tr></thead>
      <tbody>${holdingsWithRisk.map(h=>`<tr><td>${esc(h.security.name)}</td><td style="color:var(--text-muted)">${esc(h.category)}</td><td class="text-right text-mono">${fmt(h.current_value)}</td><td class="text-right text-mono">${fmt(h.volatility,1)}%</td><td class="text-right text-mono ${changeClass(h.annual_return)}">${fmtPct(h.annual_return)}</td><td class="text-right text-mono ${changeClass(h.gain_loss_pct)}">${fmtPct(h.gain_loss_pct)}</td></tr>`).join("")}</tbody></table>
    </div>`;
  if (holdingsWithRisk.length) {
    charts.rk = new Chart(document.getElementById("chRisk"),{type:"scatter",data:{datasets:[{label:"Positionen",data:holdingsWithRisk.map(h=>({x:h.volatility,y:h.annual_return,r:Math.max(4,Math.min(20,h.current_value/c.total_value*80)),label:h.security.name})),backgroundColor:"rgba(79,140,255,0.5)",borderColor:"#4f8cff",pointRadius:holdingsWithRisk.map(h=>Math.max(4,Math.min(16,h.current_value/c.total_value*60)))}]},options:{responsive:true,plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>{const h=holdingsWithRisk[ctx.dataIndex];return `${h.security.name}: Vol ${fmt(h.volatility,1)}%, Rendite ${fmtPct(h.annual_return)}`;}}}},scales:{x:{title:{display:true,text:"Volatilität (%)",color:"#8b8fa3"},ticks:{color:"#8b8fa3"},grid:{color:"#2a2e3a"}},y:{title:{display:true,text:"Rendite p.a. (%)",color:"#8b8fa3"},ticks:{color:"#8b8fa3"},grid:{color:"#2a2e3a"}}}}});
  }
}

// ── Tab: Positionen ──
function tabPositionen(c) {
  document.getElementById("tabContent").innerHTML = `
    <div class="chart-card chart-full" style="margin-bottom:1rem"><h3>Wert vs. Investiert</h3><canvas id="chPos"></canvas></div>
    <div class="table-card"><h3>Alle Positionen (${c.holdings.length})</h3>
      <table><thead><tr><th>Wertpapier</th><th>ISIN</th><th>Kategorie</th><th class="text-right">Anteile</th><th class="text-right">Kurs</th><th class="text-right">Wert</th><th class="text-right">Investiert</th><th class="text-right">G/V</th><th class="text-right">G/V %</th></tr></thead>
      <tbody>${c.holdings.map(h=>`<tr><td>${esc(h.security.name)}</td><td style="color:var(--text-muted);font-size:0.75rem">${esc(h.security.isin)}</td><td style="color:var(--text-muted)">${esc(h.category)}</td><td class="text-right text-mono">${fmt(h.shares,4)}</td><td class="text-right text-mono">${fmt(h.security.latest_price)}</td><td class="text-right text-mono">${fmt(h.current_value)} ${esc(h.currency)}</td><td class="text-right text-mono">${fmt(h.invested)}</td><td class="text-right text-mono ${changeClass(h.gain_loss)}">${fmt(h.gain_loss)}</td><td class="text-right text-mono ${changeClass(h.gain_loss_pct)}">${fmtPct(h.gain_loss_pct)}</td></tr>`).join("")}
      <tr style="font-weight:700;border-top:2px solid var(--border)"><td colspan="5">Total</td><td class="text-right text-mono">${fmt(c.total_value)}</td><td class="text-right text-mono">${fmt(c.total_invested)}</td><td class="text-right text-mono ${changeClass(c.gain_loss)}">${fmt(c.gain_loss)}</td><td class="text-right text-mono ${changeClass(c.gain_loss_pct)}">${fmtPct(c.gain_loss_pct)}</td></tr>
      </tbody></table>
    </div>`;
  if (c.holdings.length) {
    charts.ps = new Chart(document.getElementById("chPos"),{type:"bar",data:{labels:c.holdings.map(h=>truncate(h.security.name,18)),datasets:[{label:"Wert",data:c.holdings.map(h=>h.current_value),backgroundColor:"#4f8cff"},{label:"Investiert",data:c.holdings.map(h=>h.invested),backgroundColor:"#2a2e3a"}]},options:{responsive:true,indexAxis:"y",plugins:{legend:{labels:{color:"#8b8fa3"}}},scales:{x:{ticks:{color:"#8b8fa3"},grid:{color:"#2a2e3a"}},y:{ticks:{color:"#8b8fa3",font:{size:10}},grid:{display:false}}}}});
  }
}

// ── Tab: Transaktionen ──
function tabTransaktionen(c) {
  const types = ["ALL","PURCHASE","SALE","DIVIDEND","DEPOSIT","REMOVAL","FEE","INTEREST"];
  const filtered = txFilter === "ALL" ? c.all_transactions : c.all_transactions.filter(t => t.type === txFilter);
  const paged = filtered.slice(txPage * TX_PER_PAGE, (txPage + 1) * TX_PER_PAGE);
  const totalPages = Math.ceil(filtered.length / TX_PER_PAGE);

  document.getElementById("tabContent").innerHTML = `
    <div class="filter-bar">
      ${types.map(t=>`<button class="filter-btn ${txFilter===t?'active':''}" onclick="setTxFilter('${t}')">${t==="ALL"?"Alle":txLabel(t)}</button>`).join("")}
    </div>
    <div class="table-card"><h3>${filtered.length} Transaktionen</h3>
      <table><thead><tr><th>Datum</th><th>Typ</th><th>Wertpapier</th><th>Konto / Depot</th><th class="text-right">Betrag</th><th class="text-right">Anteile</th><th>Notiz</th></tr></thead>
      <tbody>${paged.map(t=>`<tr><td>${fmtDate(t.date)}</td><td>${txBadge(t.type)}</td><td>${esc(t.security_name||"-")}</td><td style="color:var(--text-muted)">${esc(t.account||t.portfolio||"-")}</td><td class="text-right text-mono">${fmt(t.amount)} ${esc(t.currency)}</td><td class="text-right text-mono">${t.shares?fmt(t.shares,4):"-"}</td><td style="color:var(--text-muted);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.note||"")}</td></tr>`).join("")}</tbody></table>
      ${totalPages > 1 ? `<div class="pagination">
        ${txPage > 0 ? `<button class="btn btn-sm" onclick="setTxPage(${txPage-1})">&#8592;</button>` : ""}
        <span style="color:var(--text-muted);font-size:0.8rem;padding:0.3rem">Seite ${txPage+1} / ${totalPages}</span>
        ${txPage < totalPages-1 ? `<button class="btn btn-sm" onclick="setTxPage(${txPage+1})">&#8594;</button>` : ""}
      </div>` : ""}
    </div>`;
}

function setTxFilter(f) { txFilter = f; txPage = 0; tabTransaktionen(currentClient); }
function setTxPage(p) { txPage = p; tabTransaktionen(currentClient); }

// ════════════════════════════════════════
// AUSGABEN (Haushaltsfinanzen) – als Tab im Kundenbereich
// ════════════════════════════════════════
async function tabAusgaben(c) {
  if (!financeData) {
    document.getElementById("tabContent").innerHTML = '<div class="loading"><div class="spinner"></div> Laden...</div>';
    try {
      financeData = await fetchJSON("/api/finance/overview");
      financeTransactions = await fetchJSON("/api/finance/transactions");
    } catch (e) {
      document.getElementById("tabContent").innerHTML = `<div class="alert alert-error">Fehler: ${esc(e.message)}</div>`;
      return;
    }
  }
  finFilter = { search: "", kategorie: "", art: "", konto: "", startDatum: "", endDatum: "" };
  finSort = { field: "datum", dir: "desc" };
  finPage = 0;
  renderAusgabenTab();
}

function renderAusgabenTab() {
  const s = financeData.summary;
  document.getElementById("tabContent").innerHTML = `
    <div class="stats-row">
      <div class="stat-card"><div class="label">Einnahmen</div><div class="value betrag-pos">${fmtCHF(s.total_einnahmen)}</div></div>
      <div class="stat-card"><div class="label">Ausgaben</div><div class="value betrag-neg">${fmtCHF(s.total_ausgaben)}</div></div>
      <div class="stat-card"><div class="label">Saldo</div><div class="value ${s.saldo >= 0 ? 'positive' : 'negative'}">${fmtCHF(s.saldo)}</div></div>
      <div class="stat-card"><div class="label">Transaktionen</div><div class="value">${s.anzahl_transaktionen}</div></div>
    </div>
    <div class="charts-row">
      <div class="chart-card"><h3>Monatliche Übersicht</h3><canvas id="chFinMonthly"></canvas></div>
      <div class="chart-card"><h3>Ausgaben nach Kategorie</h3><canvas id="chFinCat"></canvas></div>
    </div>
    <div class="chart-card chart-full" style="margin-bottom:1.5rem"><h3>Saldo-Verlauf</h3><canvas id="chFinSaldo"></canvas></div>
    <div class="table-card">
      <h3>Transaktionen</h3>
      <div class="fin-filter-bar">
        <input type="text" placeholder="Suche..." id="finSearch" oninput="updateFinFilter()">
        <select id="finKategorie" onchange="updateFinFilter()">
          <option value="">Alle Kategorien</option>
          ${financeData.kategorien.map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join("")}
        </select>
        <select id="finArt" onchange="updateFinFilter()">
          <option value="">Alle Typen</option>
          <option value="Belastung">Belastung</option>
          <option value="Gutschrift">Gutschrift</option>
        </select>
        <select id="finKonto" onchange="updateFinFilter()">
          <option value="">Alle Konten</option>
          ${financeData.konten.map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join("")}
        </select>
        <input type="date" id="finStartDatum" onchange="updateFinFilter()">
        <input type="date" id="finEndDatum" onchange="updateFinFilter()">
      </div>
      <div id="finTableContent"></div>
    </div>`;
  renderFinCharts();
  renderFinTable();
}

function renderFinCharts() {
  const m = financeData.monthly;
  const monthNames = ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"];
  function monthLabel(s) {
    const [y, mo] = s.split("-");
    return `${monthNames[parseInt(mo)-1]} ${y}`;
  }
  // Monthly bar chart
  if (m.length) {
    charts.fm = new Chart(document.getElementById("chFinMonthly"), {
      type: "bar",
      data: {
        labels: m.map(d => monthLabel(d.monat)),
        datasets: [
          { label: "Einnahmen", data: m.map(d => d.einnahmen), backgroundColor: "rgba(34,197,94,0.7)" },
          { label: "Ausgaben", data: m.map(d => d.ausgaben), backgroundColor: "rgba(239,68,68,0.7)" },
        ],
      },
      options: { responsive: true, plugins: { legend: { labels: { color: "#8b8fa3" } } }, scales: { x: { ticks: { color: "#8b8fa3" }, grid: { display: false } }, y: { ticks: { color: "#8b8fa3", callback: v => fmtCHF(v) }, grid: { color: "#2a2e3a" } } } },
    });
  }
  // Category doughnut
  const c = financeData.categories;
  if (c.length) {
    charts.fc = new Chart(document.getElementById("chFinCat"), {
      type: "doughnut",
      data: {
        labels: c.map(d => d.kategorie),
        datasets: [{ data: c.map(d => d.betrag), backgroundColor: COLORS, borderWidth: 0 }],
      },
      options: { responsive: true, plugins: { legend: { position: "right", labels: { color: "#8b8fa3", font: { size: 10 } } } } },
    });
  }
  // Saldo trend line
  if (m.length) {
    let cumulative = [];
    m.reduce((acc, d) => { acc += d.saldo; cumulative.push(acc); return acc; }, 0);
    charts.fs = new Chart(document.getElementById("chFinSaldo"), {
      type: "line",
      data: {
        labels: m.map(d => monthLabel(d.monat)),
        datasets: [{
          label: "Kumulierter Saldo",
          data: cumulative,
          borderColor: "#4f8cff",
          backgroundColor: "rgba(79,140,255,0.08)",
          fill: true,
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
        }],
      },
      options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: "#8b8fa3", maxTicksLimit: 12 }, grid: { display: false } }, y: { ticks: { color: "#8b8fa3", callback: v => fmtCHF(v) }, grid: { color: "#2a2e3a" } } } },
    });
  }
}

function updateFinFilter() {
  finFilter.search = (document.getElementById("finSearch")?.value || "").trim();
  finFilter.kategorie = document.getElementById("finKategorie")?.value || "";
  finFilter.art = document.getElementById("finArt")?.value || "";
  finFilter.konto = document.getElementById("finKonto")?.value || "";
  finFilter.startDatum = document.getElementById("finStartDatum")?.value || "";
  finFilter.endDatum = document.getElementById("finEndDatum")?.value || "";
  finPage = 0;
  renderFinTable();
}

function getFilteredFinTx() {
  let txs = financeTransactions;
  if (finFilter.search) {
    const s = finFilter.search.toLowerCase();
    txs = txs.filter(t => (t.titel||"").toLowerCase().includes(s) || (t.empfaenger||"").toLowerCase().includes(s) || (t.detail_beschrieb||"").toLowerCase().includes(s) || (t.kategorie||"").toLowerCase().includes(s));
  }
  if (finFilter.kategorie) txs = txs.filter(t => t.kategorie === finFilter.kategorie);
  if (finFilter.art) txs = txs.filter(t => t.art === finFilter.art);
  if (finFilter.konto) txs = txs.filter(t => t.konto === finFilter.konto);
  if (finFilter.startDatum) txs = txs.filter(t => t.datum >= finFilter.startDatum);
  if (finFilter.endDatum) txs = txs.filter(t => t.datum <= finFilter.endDatum);
  // Sort
  const field = finSort.field;
  const dir = finSort.dir === "desc" ? -1 : 1;
  txs = [...txs].sort((a, b) => {
    const va = a[field], vb = b[field];
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
    return String(va || "").localeCompare(String(vb || "")) * dir;
  });
  return txs;
}

function renderFinTable() {
  const filtered = getFilteredFinTx();
  const totalPages = Math.max(1, Math.ceil(filtered.length / FIN_PER_PAGE));
  const paged = filtered.slice(finPage * FIN_PER_PAGE, (finPage + 1) * FIN_PER_PAGE);
  const sortIcon = (f) => finSort.field === f ? (finSort.dir === "desc" ? " \u25BC" : " \u25B2") : "";

  document.getElementById("finTableContent").innerHTML = `
    <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.5rem">${filtered.length} Transaktion${filtered.length !== 1 ? "en" : ""}</div>
    <table>
      <thead><tr>
        <th class="sortable" onclick="setFinSort('datum')">Datum${sortIcon('datum')}</th>
        <th class="sortable" onclick="setFinSort('empfaenger')">Empfänger${sortIcon('empfaenger')}</th>
        <th class="sortable" onclick="setFinSort('kategorie')">Kategorie${sortIcon('kategorie')}</th>
        <th class="sortable" onclick="setFinSort('art')">Art${sortIcon('art')}</th>
        <th class="sortable text-right" onclick="setFinSort('betrag')">Betrag${sortIcon('betrag')}</th>
        <th class="sortable" onclick="setFinSort('konto')">Konto${sortIcon('konto')}</th>
      </tr></thead>
      <tbody>${paged.length === 0
        ? '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:2rem">Keine Transaktionen gefunden</td></tr>'
        : paged.map(t => `<tr>
            <td>${fmtDate(t.datum)}</td>
            <td title="${esc(t.detail_beschrieb)}">${esc(t.empfaenger || t.titel || "-")}</td>
            <td><span class="badge badge-other">${esc(t.kategorie)}</span></td>
            <td>${t.art === "Gutschrift" ? '<span class="badge badge-deposit">Gutschrift</span>' : '<span class="badge badge-sale">Belastung</span>'}</td>
            <td class="text-right text-mono ${t.art === 'Gutschrift' ? 'betrag-pos' : 'betrag-neg'}">${t.art === 'Belastung' ? '-' : '+'}${fmtCHF(t.betrag)}</td>
            <td style="color:var(--text-muted)">${esc(t.konto)}</td>
          </tr>`).join("")}</tbody>
    </table>
    ${totalPages > 1 ? `<div class="pagination">
      ${finPage > 0 ? `<button class="btn btn-sm" onclick="setFinPage(${finPage-1})">\u2190</button>` : ""}
      <span style="color:var(--text-muted);font-size:0.8rem;padding:0.3rem">Seite ${finPage+1} / ${totalPages}</span>
      ${finPage < totalPages-1 ? `<button class="btn btn-sm" onclick="setFinPage(${finPage+1})">\u2192</button>` : ""}
    </div>` : ""}`;
}

function setFinSort(field) {
  if (finSort.field === field) {
    finSort.dir = finSort.dir === "desc" ? "asc" : "desc";
  } else {
    finSort.field = field;
    finSort.dir = field === "datum" ? "desc" : "asc";
  }
  renderFinTable();
}

function setFinPage(p) { finPage = p; renderFinTable(); }

function fmtCHF(n) {
  return new Intl.NumberFormat("de-CH", { style: "currency", currency: "CHF" }).format(n);
}

// ════════════════════════════════════════
// SETTINGS
// ════════════════════════════════════════
async function showSettings() {
  currentView = "settings";
  destroyCharts();
  setActiveNav(null);
  document.getElementById("app").innerHTML = '<div class="loading"><div class="spinner"></div> Laden...</div>';
  try {
    const s = await fetchJSON("/api/settings");
    renderSettings(s);
  } catch (e) {
    document.getElementById("app").innerHTML = `<div class="alert alert-error">Fehler beim Laden der Einstellungen: ${esc(e.message)}</div>`;
  }
}

function renderSettings(s) {
  document.getElementById("app").innerHTML = `
    <div class="page-header">
      <h2>Einstellungen</h2>
      <div class="subtitle">SharePoint-Verbindung konfigurieren</div>
    </div>
    <div id="settingsAlert"></div>
    <div class="stat-card" style="margin-bottom:1.5rem;display:flex;align-items:center;justify-content:space-between">
      <div>
        <div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:0.2rem">Verbindungsstatus</div>
        <span class="connection-badge ${s.connected ? 'connected' : 'disconnected'}">
          &#${s.connected ? '9679' : '9675'};
          ${s.connected ? 'Verbunden' : 'Nicht verbunden'}
        </span>
      </div>
      <button class="btn btn-sm" onclick="testConnection()">Verbindung testen</button>
    </div>
    <div class="settings-form">
      <div class="stat-card" style="margin-bottom:1rem">
        <h3 style="font-size:0.8rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:1rem">Azure AD / Entra ID</h3>
        <div class="form-group">
          <label>Tenant ID</label>
          <input type="text" id="settTenant" value="${esc(s.azure_tenant_id)}" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
          <div class="hint">Azure AD Verzeichnis-ID (Directory ID)</div>
        </div>
        <div class="form-group">
          <label>Client ID (Application ID)</label>
          <input type="text" id="settClient" value="${esc(s.azure_client_id)}" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
          <div class="hint">ID der registrierten App in Azure AD</div>
        </div>
        <div class="form-group">
          <label>Client Secret</label>
          <input type="password" id="settSecret" value="" placeholder="${s.azure_client_secret_set ? '(gespeichert - leer lassen um beizubehalten)' : 'Geheimen Schlüssel eingeben'}">
          <div class="hint">${s.azure_client_secret_set ? 'Secret ist gespeichert. Leer lassen um es beizubehalten.' : 'Client Secret der Azure App-Registrierung'}</div>
        </div>
      </div>
      <div class="stat-card" style="margin-bottom:1rem">
        <h3 style="font-size:0.8rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:1rem">SharePoint</h3>
        <div class="form-group">
          <label>Site ID</label>
          <input type="text" id="settSite" value="${esc(s.sharepoint_site_id)}" placeholder="site-id oder hostname,site-path">
          <div class="hint">SharePoint Site ID (z.B. golders123.sharepoint.com,xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx,xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)</div>
        </div>
        <div class="form-group">
          <label>Ordnerpfad</label>
          <input type="text" id="settFolder" value="${esc(s.sharepoint_folder_path)}" placeholder="/Freigegebene Dokumente/Portfolios">
          <div class="hint">Pfad zum Ordner mit den .portfolio Dateien</div>
        </div>
      </div>
      <div class="stat-card" style="margin-bottom:1rem">
        <h3 style="font-size:0.8rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:1rem">Haushaltsfinanzen</h3>
        <div class="form-group">
          <label>Finance Site ID</label>
          <input type="text" id="settFinanceSite" value="${esc(s.finance_site_id)}" placeholder="SharePoint Site ID für Finanzen-Site">
          <div class="hint">Site ID der SharePoint-Site mit der Kontobewegungen-Liste</div>
        </div>
        <div class="form-group">
          <label>Listenname</label>
          <input type="text" id="settFinanceList" value="${esc(s.finance_list_name || 'Kontobewegungen')}" placeholder="Kontobewegungen">
          <div class="hint">Name der SharePoint-Liste mit den Transaktionen</div>
        </div>
      </div>
      <div class="stat-card" style="margin-bottom:1rem">
        <h3 style="font-size:0.8rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:1rem">Synchronisierung</h3>
        <div class="form-group">
          <label>Sync-Intervall (Sekunden)</label>
          <input type="number" id="settInterval" value="${s.sync_interval}" min="60" max="86400">
          <div class="hint">Wie oft soll nach neuen Dateien gesucht werden (min. 60s)</div>
        </div>
      </div>
      <div class="form-actions">
        <button class="btn btn-primary" onclick="saveSettings()">Speichern</button>
        <button class="btn" onclick="showOverview()">Abbrechen</button>
      </div>
    </div>`;
}

async function saveSettings() {
  const alertEl = document.getElementById("settingsAlert");
  alertEl.innerHTML = "";
  const data = {
    azure_tenant_id: document.getElementById("settTenant").value.trim(),
    azure_client_id: document.getElementById("settClient").value.trim(),
    azure_client_secret: document.getElementById("settSecret").value,
    sharepoint_site_id: document.getElementById("settSite").value.trim(),
    sharepoint_folder_path: document.getElementById("settFolder").value.trim(),
    sync_interval: Math.max(60, parseInt(document.getElementById("settInterval").value) || 300),
    finance_site_id: document.getElementById("settFinanceSite").value.trim(),
    finance_list_name: document.getElementById("settFinanceList").value.trim() || "Kontobewegungen",
  };
  try {
    const resp = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "Speichern fehlgeschlagen");
    }
    alertEl.innerHTML = '<div class="alert alert-success">Einstellungen gespeichert und Sync-Service neu konfiguriert.</div>';
    // Reload settings to reflect new state
    const s = await fetchJSON("/api/settings");
    renderSettings(s);
    updateSyncStatus();
  } catch (e) {
    alertEl.innerHTML = `<div class="alert alert-error">Fehler: ${esc(e.message)}</div>`;
  }
}

async function testConnection() {
  const alertEl = document.getElementById("settingsAlert");
  alertEl.innerHTML = '<div class="alert alert-info">Verbindung wird getestet...</div>';
  try {
    const resp = await fetch("/api/settings/test", { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Test fehlgeschlagen");
    let filesHtml = data.files && data.files.length
      ? `<br>Dateien: ${data.files.map(f => esc(f)).join(", ")}`
      : "";
    alertEl.innerHTML = `<div class="alert alert-success">${esc(data.message)}${filesHtml}</div>`;
  } catch (e) {
    alertEl.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
  }
}

// ── Tab: Dividenden ──
function tabDividenden(c) {
  const d = c.dividends;
  const years = Object.entries(d.by_year).sort((a,b) => b[0]-a[0]);
  const securities = Object.entries(d.by_security).sort((a,b) => b[1]-a[1]);
  document.getElementById("tabContent").innerHTML = `
    <div class="stats-row">
      <div class="stat-card"><div class="label">Dividenden Total</div><div class="value">${fmt(d.total)}</div></div>
      <div class="stat-card"><div class="label">Dividenden-Rendite</div><div class="value">${c.total_invested>0?fmt(d.total/c.total_invested*100,2):0}%</div></div>
      <div class="stat-card"><div class="label">Quellen</div><div class="value">${securities.length}</div></div>
    </div>
    <div class="charts-row">
      <div class="chart-card"><h3>Dividenden pro Jahr</h3><canvas id="chDivYear"></canvas></div>
      <div class="chart-card"><h3>Dividenden pro Wertpapier</h3><canvas id="chDivSec"></canvas></div>
    </div>
    <div class="charts-row">
      <div class="table-card"><h3>Nach Jahr</h3>
        <table><thead><tr><th>Jahr</th><th class="text-right">Betrag</th></tr></thead>
        <tbody>${years.map(([y,a])=>`<tr><td>${y}</td><td class="text-right text-mono">${fmt(a)}</td></tr>`).join("")}</tbody></table>
      </div>
      <div class="table-card"><h3>Nach Wertpapier</h3>
        <table><thead><tr><th>Wertpapier</th><th class="text-right">Total</th></tr></thead>
        <tbody>${securities.map(([n,a])=>`<tr><td>${esc(n)}</td><td class="text-right text-mono">${fmt(a)}</td></tr>`).join("")}</tbody></table>
      </div>
    </div>`;
  if (years.length) {
    const yrs = years.reverse();
    charts.dy = new Chart(document.getElementById("chDivYear"),{type:"bar",data:{labels:yrs.map(([y])=>y),datasets:[{label:"Dividenden",data:yrs.map(([,a])=>a),backgroundColor:"#22c55e"}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{ticks:{color:"#8b8fa3"},grid:{display:false}},y:{ticks:{color:"#8b8fa3",callback:v=>fmt(v,0)},grid:{color:"#2a2e3a"}}}}});
  }
  if (securities.length) {
    charts.ds = new Chart(document.getElementById("chDivSec"),{type:"bar",data:{labels:securities.slice(0,10).map(([n])=>truncate(n,18)),datasets:[{label:"Dividenden",data:securities.slice(0,10).map(([,a])=>a),backgroundColor:"#22c55e"}]},options:{responsive:true,indexAxis:"y",plugins:{legend:{display:false}},scales:{x:{ticks:{color:"#8b8fa3"},grid:{color:"#2a2e3a"}},y:{ticks:{color:"#8b8fa3",font:{size:10}},grid:{display:false}}}}});
  }
}
