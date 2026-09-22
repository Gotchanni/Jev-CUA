const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
const formatMs = (value) => value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
const agentLabel = { jev: "Jev", rule: "Rule baseline", codex_computer_use: "Codex Computer Use", jev_with_fallback: "Jev + fallback" };
let tasks = {};
let selectedTask = "edge";

const caseMeta = {
  edge: { index: "01", app: "EDGE", className: "edge", summary: "真实电商结算", stages: "登录 · 排序 · 购物车 · 结算 · 回执" },
  excel: { index: "02", app: "EXCEL", className: "excel", summary: "分析报告交付", stages: "7 KPI · 2 charts · COM verify" },
  vscode: { index: "03", app: "VS CODE", className: "vscode", summary: "缺陷诊断修复", stages: "8 defects · 9 test runs · source verify" },
  explorer: { index: "04", app: "EXPLORER", className: "explorer", summary: "季度发布流水线", stages: "10 reports · 5 artifacts · byte verify" }
};

async function getJSON(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function appPreview(meta, routes) {
  return `<div class="case-window ${meta.className}"><div class="window-bar"><span></span><span></span><span></span><b>${meta.app}</b></div><div class="window-content"><div class="window-sidebar"></div><div class="window-canvas"><i></i><i></i><i></i><i></i></div></div><div class="route-overlay">${routes.slice(0, 4).map((route) => `<span>${escapeHTML(route.split(" · ")[0])}</span>`).join("")}<b>JEV ↗</b></div></div>`;
}

function renderCases() {
  const entries = Object.entries(tasks);
  $("#avg-steps").textContent = entries.length ? (entries.reduce((sum, [, task]) => sum + task.steps, 0) / entries.length).toFixed(0) : "—";
  $("#case-grid").innerHTML = entries.map(([id, task]) => {
    const meta = caseMeta[id];
    return `<article class="case-card"><div class="case-preview">${appPreview(meta, task.hybrid_routes || [])}<span class="case-index">${meta.index}</span></div><div class="case-copy"><div class="case-meta"><span>${meta.app}</span><b>${task.steps} STEPS</b></div><h3>${meta.summary}</h3><p>${escapeHTML(task.description)}</p><small>${meta.stages}</small></div></article>`;
  }).join("");
}

function renderTabs() {
  $("#task-tabs").innerHTML = Object.entries(tasks).map(([id, task]) => `<button role="tab" aria-selected="${id === selectedTask}" data-task="${id}"><span>${escapeHTML(caseMeta[id].app)}</span><small>${task.steps} steps</small></button>`).join("");
  document.querySelectorAll("[data-task]").forEach((button) => button.addEventListener("click", async () => { selectedTask = button.dataset.task; renderTabs(); await renderBenchmark(); }));
}

function benchmarkRow(row, maxDuration) {
  const duration = row.median_wall_time_ms;
  const width = duration && maxDuration ? Math.max(6, duration / maxDuration * 100) : 0;
  const kind = row.action_space === "hybrid" ? "hybrid" : "gui";
  return `<div class="result-row"><div class="result-name"><b>${escapeHTML(agentLabel[row.agent] || row.agent)}</b><span>${kind === "hybrid" ? "Hybrid Action Space" : "GUI Only"}</span></div><div class="result-track"><i class="${kind}" style="--width:${width}%"></i><strong>${formatMs(duration)}</strong></div><div class="result-meta">${row.successful_samples}/${row.samples} success · ${row.mean_actions == null ? "—" : row.mean_actions.toFixed(1)} actions</div></div>`;
}

function pairedRows(rows) {
  const byAgent = new Map();
  rows.forEach((row) => { if (!byAgent.has(row.agent)) byAgent.set(row.agent, {}); byAgent.get(row.agent)[row.action_space] = row; });
  return [...byAgent.entries()].find(([, pair]) => pair.hybrid?.median_wall_time_ms && pair.gui_only?.median_wall_time_ms);
}

async function renderBenchmark() {
  const task = tasks[selectedTask];
  $("#benchmark-name").textContent = task.title;
  $("#benchmark-description").textContent = task.description;
  try {
    const { rows = [] } = await getJSON(`/api/benchmarks?task=${encodeURIComponent(selectedTask)}`);
    const maxDuration = Math.max(0, ...rows.map((row) => row.median_wall_time_ms || 0));
    $("#benchmark-rows").innerHTML = rows.length ? rows.map((row) => benchmarkRow(row, maxDuration)).join("") : `<div class="empty-results"><b>等待首组配对实验</b><span>真实 Hybrid / GUI Only 结果会自动显示在这里。</span></div>`;
    const pair = pairedRows(rows);
    if (pair) {
      const [, values] = pair;
      const speedup = values.gui_only.median_wall_time_ms / values.hybrid.median_wall_time_ms;
      $("#speedup-callout").innerHTML = `<strong>${speedup.toFixed(1)}×</strong><span>paired speedup</span>`;
      $("#benchmark-foot").textContent = `${values.hybrid.samples + values.gui_only.samples} 个真实样本 · 相同终态验证器 · 成功运行中位数`;
    } else {
      $("#speedup-callout").innerHTML = `<strong>—</strong><span>paired speedup</span>`;
      $("#benchmark-foot").textContent = "只发布真实运行数据，不用估算值填充。";
    }
  } catch (error) {
    $("#benchmark-rows").innerHTML = `<div class="empty-results"><b>暂时无法读取实验数据</b><span>${escapeHTML(error.message)}</span></div>`;
  }
}

async function boot() {
  try {
    const bootstrap = await getJSON("/api/bootstrap");
    tasks = bootstrap.tasks || {};
    renderCases(); renderTabs(); await renderBenchmark();
  } catch (error) {
    $("#case-grid").innerHTML = `<div class="empty-results"><b>项目数据读取失败</b><span>${escapeHTML(error.message)}</span></div>`;
  }
}
boot();
