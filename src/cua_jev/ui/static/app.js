const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
const formatMs = (value) => value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
const agentLabel = { jev: "Jev", rule: "Rule baseline", codex_computer_use: "Codex Computer Use", jev_with_fallback: "Jev + fallback" };
let tasks = {};
let demos = {};
let selectedTask = "edge";

const caseMeta = {
  edge: { index: "01", app: "EDGE", className: "edge", summary: "Public store checkout", stages: "Sign in · sort · cart · checkout · receipt" },
  excel: { index: "02", app: "EXCEL", className: "excel", summary: "Analysis report delivery", stages: "7 metrics · 2 charts · COM verification" },
  vscode: { index: "03", app: "VS CODE", className: "vscode", summary: "Multi-defect repair", stages: "8 defects · 9 test runs · source verification" },
  explorer: { index: "04", app: "EXPLORER", className: "explorer", summary: "Quarterly release pipeline", stages: "10 reports · 5 artifacts · byte verification" }
};

async function getJSON(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function appPreview(meta, routes) {
  return `<div class="case-window ${meta.className}"><div class="window-bar"><span></span><span></span><span></span><b>${meta.app}</b></div><div class="window-content"><div class="window-sidebar"></div><div class="window-canvas"><i></i><i></i><i></i><i></i></div></div><div class="route-overlay">${routes.slice(0, 4).map((route) => `<span>${escapeHTML(route.split(" · ")[0])}</span>`).join("")}<b>Jev selects ↗</b></div></div>`;
}

function casePreview(id, meta, routes) {
  const sources = demos[id] || {};
  const initial = sources.hybrid || sources.gui_only;
  if (!initial) return appPreview(meta, routes);
  return `<div class="case-video"><video controls muted playsinline preload="metadata" src="${escapeHTML(initial)}" aria-label="${escapeHTML(meta.summary)} demonstration"></video><div class="video-switch" aria-label="Select demonstration mode">${sources.hybrid ? `<button data-video="${escapeHTML(sources.hybrid)}" aria-pressed="${initial === sources.hybrid}">Jev · Hybrid</button>` : ""}${sources.gui_only ? `<button data-video="${escapeHTML(sources.gui_only)}" aria-pressed="${initial === sources.gui_only}">Jev · GUI Only</button>` : ""}</div></div>`;
}

function renderCases() {
  $("#case-grid").innerHTML = Object.entries(tasks).map(([id, task]) => {
    const meta = caseMeta[id];
    return `<article class="case-card"><div class="case-preview">${casePreview(id, meta, task.hybrid_routes || [])}<span class="case-index">${meta.index}</span></div><div class="case-copy"><div class="case-meta"><span>${meta.app}</span><b>${task.steps} STEPS</b></div><h3>${meta.summary}</h3><p>${escapeHTML(task.description)}</p><small>${meta.stages}</small></div></article>`;
  }).join("");
  document.querySelectorAll(".video-switch button").forEach((button) => button.addEventListener("click", () => {
    const wrapper = button.closest(".case-video");
    const video = wrapper.querySelector("video");
    video.pause();
    video.src = button.dataset.video;
    video.load();
    wrapper.querySelectorAll("button").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
  }));
}

function renderTabs() {
  $("#task-tabs").innerHTML = Object.entries(tasks).map(([id, task]) => `<button role="tab" aria-selected="${id === selectedTask}" data-task="${id}"><span>${escapeHTML(caseMeta[id].app)}</span><small>${task.steps} steps</small></button>`).join("");
  document.querySelectorAll("[data-task]").forEach((button) => button.addEventListener("click", async () => {
    selectedTask = button.dataset.task;
    renderTabs();
    await renderBenchmark();
  }));
}

function benchmarkRow(row, maxDuration) {
  const duration = row.median_wall_time_ms;
  const width = duration && maxDuration ? Math.max(6, duration / maxDuration * 100) : 0;
  const kind = row.action_space === "hybrid" ? "hybrid" : "gui";
  const mode = kind === "hybrid" ? "Hybrid" : "GUI Only";
  const label = `${agentLabel[row.agent] || row.agent} · ${mode}`;
  const actions = row.mean_actions == null ? "—" : row.mean_actions.toFixed(1);
  return `<div class="result-row"><div class="result-name"><b>${escapeHTML(label)}</b></div><div class="result-track"><i class="${kind}" style="--width:${width}%"></i><strong>${formatMs(duration)}</strong></div><div class="result-meta">${row.successful_samples}/${row.samples} runs · ${actions} actions</div></div>`;
}

function pairedRows(rows) {
  const byAgent = new Map();
  rows.forEach((row) => {
    if (!byAgent.has(row.agent)) byAgent.set(row.agent, {});
    byAgent.get(row.agent)[row.action_space] = row;
  });
  return [...byAgent.entries()].find(([agent, pair]) => agent.startsWith("jev") && pair.hybrid?.median_wall_time_ms && pair.gui_only?.median_wall_time_ms)
    || [...byAgent.entries()].find(([, pair]) => pair.hybrid?.median_wall_time_ms && pair.gui_only?.median_wall_time_ms);
}

async function renderHeadlineMetrics() {
  const results = await Promise.all(Object.keys(tasks).map(async (task) => {
    try {
      const { rows = [] } = await getJSON(`/api/benchmarks?task=${encodeURIComponent(task)}`);
      const pair = pairedRows(rows);
      if (!pair) return null;
      const [, values] = pair;
      return values.gui_only.median_wall_time_ms / values.hybrid.median_wall_time_ms;
    } catch (_) {
      return null;
    }
  }));
  const speedups = results.filter((value) => Number.isFinite(value));
  $("#best-speedup").textContent = speedups.length ? `${Math.max(...speedups).toFixed(1)}×` : "—";
}

async function renderBenchmark() {
  const task = tasks[selectedTask];
  $("#benchmark-name").textContent = task.title;
  $("#benchmark-description").textContent = task.description;
  try {
    const { rows = [] } = await getJSON(`/api/benchmarks?task=${encodeURIComponent(selectedTask)}`);
    const maxDuration = Math.max(0, ...rows.map((row) => row.median_wall_time_ms || 0));
    $("#benchmark-rows").innerHTML = rows.length
      ? rows.map((row) => benchmarkRow(row, maxDuration)).join("")
      : `<div class="empty-results"><b>No paired runs yet</b><span>Measured Jev · Hybrid and Jev · GUI Only results will appear here.</span></div>`;
    const pair = pairedRows(rows);
    if (pair) {
      const [, values] = pair;
      const speedup = values.gui_only.median_wall_time_ms / values.hybrid.median_wall_time_ms;
      const wording = speedup >= 1 ? "faster with Hybrid" : "GUI Only / Hybrid";
      $("#speedup-callout").innerHTML = `<strong>${speedup.toFixed(1)}×</strong><span>${wording}</span>`;
      $("#benchmark-foot").textContent = `${values.hybrid.samples + values.gui_only.samples} real runs · same terminal verifier · median successful wall time`;
    } else {
      $("#speedup-callout").innerHTML = `<strong>—</strong><span>paired speedup</span>`;
      $("#benchmark-foot").textContent = "Only measured runs are shown—no estimated values.";
    }
  } catch (error) {
    $("#benchmark-rows").innerHTML = `<div class="empty-results"><b>Results unavailable</b><span>${escapeHTML(error.message)}</span></div>`;
  }
}

async function boot() {
  try {
    const bootstrap = await getJSON("/api/bootstrap");
    tasks = bootstrap.tasks || {};
    demos = bootstrap.demos || {};
    renderCases();
    renderTabs();
    await Promise.all([renderBenchmark(), renderHeadlineMetrics()]);
  } catch (error) {
    $("#case-grid").innerHTML = `<div class="empty-results"><b>Project data unavailable</b><span>${escapeHTML(error.message)}</span></div>`;
  }
}

boot();
