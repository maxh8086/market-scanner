/**
 * Market Scanner UI - Vanilla JS SPA
 * Hash-based routing with data fetching from REST API
 */

const fmt = n => n.toLocaleString("en-IN");
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// Router
const ROUTES = {
  "": "home",
  "/": "home",
  "/run": "run",
  "/results": "results",
  "/stock": "stock",
  "/stocks": "stocks",
  "/cost": "cost",
  "/report": "report",
  "/config": "config",
};

let currentRoute = "home";
let currentData = {};

async function router(hash = location.hash) {
  const path = hash.replace(/^#/, "");
  const [route, ...args] = path.split("/").filter(Boolean);
  const routeKey = "/" + route;
  const viewName = ROUTES[routeKey] || ROUTES[""];

  currentRoute = viewName;

  // Update nav
  $$("#nav a").forEach(a => a.removeAttribute("aria-current"));
  const navLink = $(`#nav a[data-nav="${viewName}"]`);
  if (navLink) navLink.setAttribute("aria-current", "page");

  // Update breadcrumb
  updateBreadcrumb(viewName, args);

  // Load view
  renderView(viewName, args);
}

function updateBreadcrumb(view, args) {
  const crumbs = $(".crumbs");
  const trail = $("#trail");

  if (view === "home") {
    crumbs.style.display = "none";
    trail.innerHTML = "<b>Home</b>";
    document.title = "Market Scanner";
  } else {
    crumbs.style.display = "";
    let html = `<a href="#/">Home</a>`;

    if (view === "run" && args[0]) html += `<span>/</span><b>Run ${args[0]}</b>`;
    else if (view === "run") html += `<span>/</span><b>Latest run</b>`;
    else if (view === "results" && args[0]) html += `<span>/</span><a href="#/run/${args[0]}">Run</a><span>/</span><b>Results</b>`;
    else if (view === "stock" && args[0]) html += `<span>/</span><b>${args[0]}</b>`;
    else if (view === "stocks") html += `<span>/</span><a href="#/stocks">Stocks</a>`;
    else if (view === "cost") html += `<span>/</span><b>Cost center</b>`;
    else if (view === "report") html += `<span>/</span><b>Report dashboard</b>`;
    else if (view === "config") html += `<span>/</span><b>Master configuration</b>`;

    trail.innerHTML = html;
    document.title = `${view.charAt(0).toUpperCase() + view.slice(1)} | Market Scanner`;
  }
}

async function renderView(view, args) {
  const app = $("#app");

  try {
    let html = "<div class='loading' style='padding:40px;text-align:center'>Loading...</div>";

    switch (view) {
      case "home":
        html = await renderHome();
        break;
      case "run":
        html = await renderRun(args[0]);
        break;
      case "results":
        html = await renderResults(args[0]);
        break;
      case "stock":
        html = await renderStock(args[0]);
        break;
      case "stocks":
        html = await renderStocks();
        break;
      case "cost":
        html = await renderCost();
        break;
      case "report":
        html = await renderReport();
        break;
      case "config":
        html = await renderConfig();
        break;
      default:
        html = "<div class='empty'>View not found</div>";
    }

    app.innerHTML = html;
    window.scrollTo(0, 0);
    document.getElementById("nav").classList.remove("open");
    document.getElementById("menu").setAttribute("aria-expanded", "false");
  } catch (err) {
    app.innerHTML = `<div class='empty'>Error: ${err.message}</div>`;
  }
}

// View renderers
async function renderHome() {
  const res = await fetch("/api/runs");
  const data = await res.json();
  const runs = data.runs || [];
  const latest = runs[0];

  if (!latest) {
    return `
      <div class="head">
        <div>
          <div class="eyebrow">Latest run</div>
          <h1>No runs yet</h1>
          <p class="sub">Waiting for the first scan to complete.</p>
        </div>
      </div>
    `;
  }

  updateStamp(latest.run_date);

  const runsHtml = runs.slice(0, 6).map(r => `
    <tr class="link" tabindex="0" onclick="location.hash='#/run/${r.run_date}'">
      <td><b>${r.run_date}</b></td>
      <td class="r num hide-sm">${r.scanned || 0}</td>
      <td class="r num">${r.in_range || 0}</td>
      <td class="r num hide-sm">${r.at_ath || 0}</td>
      <td><span class="pill ${r.status === 'complete' ? 'ok' : r.status === 'running' ? 'pending' : 'pending'}"><span class="dot"></span>${r.status}</span></td>
    </tr>
  `).join("");

  return `
    <div class="head">
      <div>
        <div class="eyebrow">Latest run</div>
        <h1>${latest.run_date}: ${latest.in_range || 0} stocks within range</h1>
        <p class="sub">${latest.scanned || 0} stocks scanned. Pick any run below to open its dashboard.</p>
      </div>
      <a class="btn primary" href="#/run/${latest.run_date}">Open run dashboard <svg><use href="#i-arrow"/></svg></a>
    </div>

    <div class="grid">
      <div class="stack">
        <div class="strip" aria-label="Latest run summary">
          <div><div class="k">At ATH</div><div class="v">${latest.at_ath || 0}</div></div>
          <div><div class="k">In range</div><div class="v">${latest.in_range || 0}</div></div>
          <div><div class="k">Run status</div><div class="v">${latest.status}</div></div>
        </div>

        <div class="sect">
          <header><h2>Runs</h2><span class="hint">Click to open</span></header>
          <div class="tbl-wrap">
            <table>
              <thead><tr>
                <th>Run date</th><th class="r hide-sm">Scanned</th><th class="r">In range</th><th class="r hide-sm">At ATH</th><th>Status</th>
              </tr></thead>
              <tbody>${runsHtml || '<tr><td colspan="5"><div class="empty">No runs yet</div></td></tr>'}</tbody>
            </table>
          </div>
        </div>
      </div>

      <aside class="stack">
        <div class="panel">
          <div class="eyebrow">Cost center</div>
          <h2 style="margin-top:6px;font-size:18px">Measured metrics</h2>
          <p class="note" style="margin:8px 0 14px">See the Cost center page for detailed token and energy metrics from your runs.</p>
          <a class="btn" href="#/cost">Open cost center <svg><use href="#i-arrow"/></svg></a>
        </div>

        <div class="panel">
          <div class="eyebrow">Report dashboard</div>
          <h2 style="margin-top:6px;font-size:18px">Trends</h2>
          <p class="note" style="margin:8px 0 14px">View how stocks and metrics have changed across recent runs.</p>
          <a class="btn" href="#/report">Open dashboard <svg><use href="#i-arrow"/></svg></a>
        </div>
      </aside>
    </div>
  `;
}

async function renderRun(runId) {
  if (!runId) {
    const res = await fetch("/api/runs?limit=1");
    const data = await res.json();
    if (data.runs && data.runs.length) runId = data.runs[0].run_id;
  }

  if (!runId) return `<div class="empty">No run specified</div>`;

  const res = await fetch(`/api/runs/${runId}`);
  const data = await res.json();
  const run = data.run;
  const stats = data.stats;

  if (!run) return `<div class="empty">Run not found</div>`;

  updateStamp(run.run_date);

  return `
    <div class="head">
      <div>
        <div class="eyebrow">Run dashboard</div>
        <h1>Run of ${run.run_date}</h1>
        <p class="sub">Started ${new Date(run.started_at).toLocaleString()}</p>
      </div>
      <a class="btn primary" href="#/results/${run.run_date}">All results <svg><use href="#i-arrow"/></svg></a>
    </div>

    <div class="strip" style="margin-bottom:32px">
      <div><div class="k">Scanned</div><div class="v">${run.scanned || 0}</div></div>
      <div><div class="k">In range</div><div class="v">${run.in_range || 0}</div></div>
      <div><div class="k">At ATH</div><div class="v">${run.at_ath || 0}</div></div>
      <div><div class="k">Status</div><div class="v">${run.status}</div></div>
    </div>

    <div class="grid">
      <div class="stack">
        <div class="sect">
          <header><h2>Counts by stance</h2></header>
          <div style="display:grid;gap:12px;margin-top:12px">
            <div class="hbar"><span>Constructive</span><span class="t"><i style="width:${stats.constructive ? stats.constructive / Math.max(stats.constructive, stats.mixed, stats.cautious) * 100 : 0}%"></i></span><span class="num r">${stats.constructive || 0}</span></div>
            <div class="hbar"><span>Mixed</span><span class="t"><i style="width:${stats.mixed ? stats.mixed / Math.max(stats.constructive, stats.mixed, stats.cautious) * 100 : 0}%"></i></span><span class="num r">${stats.mixed || 0}</span></div>
            <div class="hbar"><span>Cautious</span><span class="t"><i style="width:${stats.cautious ? stats.cautious / Math.max(stats.constructive, stats.mixed, stats.cautious) * 100 : 0}%"></i></span><span class="num r">${stats.cautious || 0}</span></div>
          </div>
        </div>
      </div>

      <aside class="stack">
        <div class="panel">
          <h2>Cost of this run</h2>
          <div class="rows" style="margin-top:8px">
            <div><span class="l">Run date</span><span class="num">${run.run_date}</span></div>
            <div><span class="l">Status</span><span class="num">${run.status}</span></div>
          </div>
          <a class="btn" style="margin-top:14px" href="#/cost">View cost details <svg><use href="#i-arrow"/></svg></a>
        </div>
      </aside>
    </div>
  `;
}

async function renderResults(runId) {
  if (!runId) {
    const res = await fetch("/api/runs?limit=1");
    const data = await res.json();
    if (data.runs && data.runs.length) runId = data.runs[0].run_date;
  }

  if (!runId) return `<div class="empty">No run specified</div>`;

  const res = await fetch(`/api/runs/${runId}/results?limit=20`);
  const data = await res.json();
  const results = data.results || [];
  const total = data.total || 0;

  const rows = results.map(r => `
    <tr class="link" tabindex="0" onclick="location.hash='#/stock/${r.symbol}'">
      <td><div class="sym">${r.symbol}</div><div class="nm">${r.company || ""}</div></td>
      <td class="hide-sm">${r.industry || ""}</td>
      <td class="r num">${fmt(r.ltp)}</td>
      <td class="r num">${r.distance_pct ? r.distance_pct.toFixed(1) + "%" : "—"}</td>
      <td class="r num hide-sm">${r.ath_date || "—"}</td>
      <td><span class="pill ${r.stance}">${r.stance ? r.stance.charAt(0).toUpperCase() + r.stance.slice(1) : "—"}</span></td>
    </tr>
  `).join("");

  return `
    <div class="head">
      <div>
        <div class="eyebrow">Run of ${runId}</div>
        <h1>All results</h1>
        <p class="sub">Showing ${results.length} of ${total} stocks in range.</p>
      </div>
    </div>

    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th>Stock</th><th class="hide-sm">Industry</th><th class="r">Price</th><th class="r">Below ATH</th><th class="r hide-sm">ATH date</th><th>Stance</th>
        </tr></thead>
        <tbody>${rows || '<tr><td colspan="6"><div class="empty">No results</div></td></tr>'}</tbody>
      </table>
    </div>
  `;
}

async function renderStocks() {
  const res = await fetch("/api/stocks");
  const data = await res.json();

  if (data.error) return `<div class="empty">${data.error}</div>`;

  const rows = (data.rows || []).map(r => `
    <tr class="link" tabindex="0" onclick="location.hash='#/stock/${r.symbol ?? ""}'">
      <td><div class="sym">${r.symbol ?? ""}</div></td>
      <td>${r.bucket ?? ""}</td>
      <td class="r num">${r.stance_score ?? ""}</td>
      <td class="r num hide-sm">${r.run_date ?? ""}</td>
    </tr>
  `).join("");

  return `
    <div class="head">
      <div>
        <div class="eyebrow">Latest snapshot</div>
        <h1>Stocks</h1>
        <p class="sub">${data.total ?? 0} stocks in the latest run.</p>
      </div>
    </div>

    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th>Symbol</th><th>Bucket</th><th class="r">Stance score</th><th class="r hide-sm">Run date</th>
        </tr></thead>
        <tbody>${rows || '<tr><td colspan="4"><div class="empty">No stocks</div></td></tr>'}</tbody>
      </table>
    </div>
  `;
}

async function renderStock(symbol) {
  if (!symbol) return `<div class="empty">No symbol specified</div>`;

  const res = await fetch(`/api/stocks/${symbol}`);
  const data = await res.json();

  if (data.error) return `<div class="empty">${data.error}</div>`;

  const snapshot = data.snapshot;
  const timeline = data.timeline || [];

  if (!snapshot) return `<div class="empty">Stock not found</div>`;

  const timelineHtml = timeline.slice(0, 5).map(t => `
    <li><div class="when"><b>${t.run_date}</b><span class="pill ${t.stance}">${t.stance || "—"}</span><span class="num">${t.ltp} · ${t.distance_pct ? t.distance_pct.toFixed(1) + "%" : "—"} below ATH</span></div></li>
  `).join("");

  return `
    <div class="head">
      <div>
        <div class="eyebrow">${snapshot.industry || "—"}</div>
        <h1>${snapshot.company || symbol}</h1>
        <p class="sub"><span class="mono">${symbol}</span> on NSE.</p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <span class="pill measured">${snapshot.bucket || "—"}</span>
        <span class="pill ${snapshot.stance || 'mixed'}">${snapshot.stance ? snapshot.stance.charAt(0).toUpperCase() + snapshot.stance.slice(1) : "—"}</span>
      </div>
    </div>

    <div class="strip" style="margin-bottom:32px">
      <div><div class="k">Price</div><div class="v">${fmt(snapshot.ltp)}</div><div class="d">as of ${snapshot.run_date}</div></div>
      <div><div class="k">Below ATH</div><div class="v">${snapshot.distance_pct ? snapshot.distance_pct.toFixed(1) + "%" : "—"}</div><div class="d mono">ATH ${fmt(snapshot.ath_high)} on ${snapshot.ath_date}</div></div>
      <div><div class="k">1Y return</div><div class="v ${snapshot.one_year_return_pct >= 0 ? 'up' : 'down'}">${snapshot.one_year_return_pct ? (snapshot.one_year_return_pct >= 0 ? "+" : "") + snapshot.one_year_return_pct.toFixed(1) + "%" : "—"}</div></div>
    </div>

    <div class="grid">
      <div class="stack">
        <div class="sect">
          <header><h2>Analysis timeline</h2><span class="hint">recent runs</span></header>
          <ol class="tl" style="margin-top:12px">${timelineHtml || '<li><div class="empty">No timeline data</div></li>'}</ol>
        </div>
      </div>

      <aside class="stack">
        <div class="panel">
          <div class="eyebrow">Metrics</div>
          <div class="kv" style="margin-top:8px">
            <span>Latest price</span><span>${fmt(snapshot.ltp)}</span>
            <span>Stance</span><span>${snapshot.stance || "—"}</span>
            <span>Bucket</span><span>${snapshot.bucket || "—"}</span>
            <span>EMA</span><span>TBD</span>
            <span>Relative strength</span><span>TBD</span>
          </div>
        </div>
      </aside>
    </div>
  `;
}

async function renderCost() {
  const res = await fetch("/api/cost");
  const data = await res.json();

  if (data.error) return `<div class="empty">${data.error}</div>`;

  const metrics = data.metrics;
  const comparison = data.runs_comparison || [];

  if (!metrics) return `<div class="empty">No metrics available</div>`;

  updateStamp(metrics.run_date);

  const compRows = comparison.slice(0, 10).map(r => `
    <tr>
      <td class="num">${r.run_date}</td>
      <td class="r num">${r.llm_calls}</td>
      <td class="r num">${r.total_input_tokens ? fmt(Math.round(r.total_input_tokens / 1000)) + "K" : "—"}</td>
      <td class="r num">${r.total_output_tokens ? fmt(Math.round(r.total_output_tokens / 1000)) + "K" : "—"}</td>
      <td class="r num">${r.total_seconds ? r.total_seconds.toFixed(0) + "s" : "—"}</td>
      <td class="r num">${r.gpu_energy_wh ? r.gpu_energy_wh.toFixed(1) + " Wh" : "—"}</td>
    </tr>
  `).join("");

  return `
    <div class="head">
      <div>
        <div class="eyebrow">Cost center</div>
        <h1>Measured metrics from runs</h1>
        <p class="sub">All figures below are measured from real pipeline executions. Multiply tokens or energy by your own rates.</p>
      </div>
    </div>

    <div class="strip" style="margin-bottom:32px">
      <div><div class="k">LLM calls</div><div class="v">${metrics.llm_calls}</div><div class="d">ok ${metrics.ok_calls || 0} failed ${metrics.failed_calls || 0}</div></div>
      <div><div class="k">Input tokens</div><div class="v">${fmt(metrics.total_input_tokens || 0)}</div></div>
      <div><div class="k">Output tokens</div><div class="v">${fmt(metrics.total_output_tokens || 0)}</div></div>
      <div><div class="k">GPU energy</div><div class="v">${metrics.gpu_energy_wh ? metrics.gpu_energy_wh.toFixed(1) + " Wh" : "—"}</div><div class="d">at ${metrics.gpu_watts_avg || "—"} W avg</div></div>
    </div>

    <div class="grid">
      <div class="stack">
        <div class="sect">
          <header><h2>Run comparison</h2><span class="hint">recent runs, key metrics</span></header>
          <div class="tbl-wrap"><table>
            <thead><tr><th>Run date</th><th class="r">LLM calls</th><th class="r">Input tokens</th><th class="r">Output tokens</th><th class="r">Seconds</th><th class="r">GPU Wh</th></tr></thead>
            <tbody>${compRows || '<tr><td colspan="6"><div class="empty">No data</div></td></tr>'}</tbody>
          </table></div>
        </div>
      </div>

      <aside class="stack">
        <div class="panel">
          <h2>About these metrics</h2>
          <p class="note">Input and output tokens are from actual model calls. GPU energy is: average watts × busy seconds ÷ 3,600. Missing values show as a dash or "—".</p>
          <p class="note" style="margin-top:8px">Multiply tokens by your API rate, or energy by your electricity cost, to find your own cost.</p>
        </div>
      </aside>
    </div>
  `;
}

async function renderReport() {
  const res = await fetch("/api/report");
  const data = await res.json();

  if (data.error) return `<div class="empty">${data.error}</div>`;

  const runs = data.runs || [];
  const industries = data.industries || [];
  const newlyAth = data.newly_ath || [];

  if (runs.length) updateStamp(runs[0].run_date);

  const indRows = industries.slice(0, 6).map(i => `
    <div class="hbar"><span>${i.industry || "—"}</span><span class="t"><i style="width:${i.count ? i.count / Math.max(...industries.map(x => x.count || 0)) * 100 : 0}%"></i></span><span class="num r">${i.count || 0}</span></div>
  `).join("");

  const newAthRows = newlyAth.slice(0, 10).map(a => `
    <div><a class="mono" href="#/stock/${a.symbol}">${a.symbol}</a><span class="num l">${a.run_date}</span></div>
  `).join("");

  return `
    <div class="head">
      <div>
        <div class="eyebrow">Report dashboard</div>
        <h1>How the market is trending</h1>
        <p class="sub">Analysis across recent runs.</p>
      </div>
    </div>

    <div class="grid wide-right">
      <div class="stack">
        <div class="sect">
          <header><h2>Industries represented</h2><span class="hint">latest run</span></header>
          <div style="margin-top:12px">${indRows || '<div class="empty">No data</div>'}</div>
        </div>
      </div>

      <aside class="stack">
        <div class="sect">
          <header><h2>Newly at ATH</h2></header>
          <div class="rows" style="margin-top:12px">${newAthRows || '<div class="empty">No data</div>'}</div>
        </div>
      </aside>
    </div>
  `;
}

async function renderConfig() {
  const res = await fetch("/api/config");
  const data = await res.json();

  if (data.error) return `<div class="empty">${data.error}</div>`;

  const sources = data.sources || [];
  const coverage = data.coverage;

  const sourceHtml = sources.map(s => `
    <div class="sect" id="cfg-${s.source}">
      <header><h2>${s.source}</h2></header>
      <div style="display:grid;gap:16px;margin-top:12px">
        <div style="display:flex;gap:32px;align-items:flex-start">
          <div>
            <label style="display:block;margin-bottom:8px">Mode</label>
            <div class="seg" role="group">
              <button data-mode="scheduled" aria-pressed="${s.mode === 'scheduled' ? 'true' : 'false'}" onclick="setMode('${s.source}', 'scheduled')">Scheduled</button>
              <button data-mode="manual" aria-pressed="${s.mode === 'manual' ? 'true' : 'false'}" onclick="setMode('${s.source}', 'manual')">Manual</button>
            </div>
          </div>
          <div style="flex:1">
            <label for="cron-${s.source}">Cron (Asia/Kolkata)</label>
            <input id="cron-${s.source}" class="mono" value="${s.cron}" placeholder="minute hour day month dow">
          </div>
          <div style="color:var(--muted);padding-top:26px">${s.cron_human}</div>
        </div>
        <div style="border-top:1px solid var(--line);padding-top:12px">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px;margin-bottom:12px">
            <div><span style="color:var(--faint);font-size:12px">Last run</span><div class="num" style="margin-top:4px">${s.last_runs && s.last_runs[0] ? new Date(s.last_runs[0].started_at).toLocaleString() : "—"}</div></div>
            <div><span style="color:var(--faint);font-size:12px">Status</span><div class="num" style="margin-top:4px"><span class="pill ${s.last_runs && s.last_runs[0] && s.last_runs[0].status === 'ok' ? 'ok' : 'pending'}"><span class="dot"></span>${s.last_runs && s.last_runs[0] ? s.last_runs[0].status : "—"}</span></div></div>
            <div><span style="color:var(--faint);font-size:12px">Rows fetched</span><div class="num" style="margin-top:4px">${s.last_runs && s.last_runs[0] ? s.last_runs[0].rows_fetched : "—"}</div></div>
            <div><span style="color:var(--faint);font-size:12px">Rows new</span><div class="num" style="margin-top:4px">${s.last_runs && s.last_runs[0] ? s.last_runs[0].rows_new : "—"}</div></div>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn primary" onclick="runNow('${s.source}')">Run now</button>
            <button class="btn" onclick="saveConfig('${s.source}')">Save</button>
            ${s.last_runs && s.last_runs.length > 1 ? `<details style="flex:1"><summary style="cursor:pointer;color:var(--accent);font-weight:500">Last ${Math.min(s.last_runs.length, 5)} runs</summary><div class="tbl-wrap" style="margin-top:8px"><table style="font-size:13px"><thead><tr><th>Started</th><th>Status</th><th class="r">Fetched</th><th class="r">New</th></tr></thead><tbody>${s.last_runs.slice(0, 5).map(r => `<tr><td>${new Date(r.started_at).toLocaleString()}</td><td><span class="pill ${r.status === 'ok' ? 'ok' : 'pending'}">${r.status}</span></td><td class="r">${r.rows_fetched}</td><td class="r">${r.rows_new}</td></tr>`).join('')}</tbody></table></div></details>` : ''}
          </div>
        </div>
      </div>
    </div>
  `).join("");

  return `
    <div class="head">
      <div>
        <div class="eyebrow">Data sources</div>
        <h1>Master configuration</h1>
        <p class="sub">Configure when each data source updates: on a schedule (cron) or manually.</p>
      </div>
    </div>

    <div class="stack">
      ${sourceHtml || '<div class="empty">No sources configured</div>'}

      <div class="sect" style="margin-top:32px">
        <header><h2>Announcements coverage</h2><span class="hint">per stock, 3 years or since listing date</span></header>
        <p class="note" style="margin-top:12px;margin-bottom:12px">The UI requires announcements from <b>max(listing date, today - 3 years)</b> to today.</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:12px">
          <div style="border-top:1px solid var(--line-strong);padding-top:14px">
            <div><span style="color:var(--faint);font-size:12px">Stocks OK</span><div class="num">${coverage && coverage.stocks_ok ? coverage.stocks_ok : "—"}</div></div>
          </div>
          <div style="border-top:1px solid var(--line-strong);padding-top:14px">
            <div><span style="color:var(--faint);font-size:12px">Stocks with gaps</span><div class="num">${coverage && coverage.stocks_with_gaps ? coverage.stocks_with_gaps : "—"}</div></div>
          </div>
        </div>
        <p class="note" style="margin-top:12px">Candles are end-of-day prices only.</p>
      </div>
    </div>
  `;
}

function updateStamp(runDate) {
  const stamp = document.getElementById("stamp");
  const now = new Date();
  stamp.textContent = `data as of ${runDate} ${now.toLocaleString()}`;
}

function setMode(source, mode) {
  const sect = document.getElementById(`cfg-${source}`);
  const buttons = sect.querySelectorAll('.seg button');
  buttons.forEach(b => {
    b.setAttribute('aria-pressed', b.dataset.mode === mode ? 'true' : 'false');
  });
}

function saveConfig(source) {
  const sect = document.getElementById(`cfg-${source}`);
  const cronInput = sect.querySelector('.mono');
  const modeButton = sect.querySelector('[aria-pressed="true"]');
  const mode = modeButton ? (modeButton.textContent.toLowerCase()) : 'scheduled';
  const cron = cronInput.value.trim();

  if (!cron) {
    alert("Cron expression is required");
    return;
  }

  fetch(`/api/config/${source}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, cron, params: {} })
  })
    .then(r => r.json())
    .then(d => {
      if (d.success) {
        alert(`Saved ${source}`);
        router(); // Refresh
      } else {
        alert("Error: " + (d.detail || "Unknown error"));
      }
    })
    .catch(e => alert("Error: " + e));
}

function runNow(source) {
  fetch(`/api/config/${source}/run`, { method: "POST" })
    .then(r => r.json())
    .then(d => alert("Run queued: " + d.source))
    .catch(e => alert("Error: " + e));
}

// Route on hash change and load
addEventListener("hashchange", () => router());
router();
