const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
const formatMs = (value) => value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
const agentLabel = { jev: "Jev", rule: "Rule baseline", codex_computer_use: "Codex agent", jev_with_fallback: "Jev + fallback" };
let tasks = {};
let demos = {};
let selectedTask = "edge";
let benchmarkRequest = 0;

const caseMeta = {
  edge: { app: "EDGE", className: "edge", summary: "Public store checkout", stages: "Sign in · sort · cart · checkout · receipt" },
  excel: { app: "EXCEL", className: "excel", summary: "Analysis report delivery", stages: "7 metrics · 2 charts · COM verification" },
  vscode: { app: "VS CODE", className: "vscode", summary: "Multi-defect repair", stages: "8 defects · 9 test runs · source verification" },
  explorer: { app: "EXPLORER", className: "explorer", summary: "Quarterly release pipeline", stages: "10 reports · 5 artifacts · byte verification" }
};

const loopDetails = {
  observe: {
    kicker: "01 · OBSERVE",
    title: "Frame a typed decision",
    summary: "A task-specific adapter turns structured app state into the next set of legal choices for Jev.",
    jev: "Receives the current subgoal, structured state, and only the legal actions available now.",
    runtime: "Reads DOM, UI Automation, COM, terminal, or filesystem state through the task adapter."
  },
  select: {
    kicker: "02 · SELECT",
    title: "Choose intent and action space",
    summary: "Jev compares typed candidates across GUI and structured channels, then commits to one executable action.",
    jev: "Selects the next intent × channel pair from the constrained candidate set; it can reselect after new evidence.",
    runtime: "The task adapter offers typed candidates; the runtime validates Jev’s response."
  },
  execute: {
    kicker: "03 · EXECUTE",
    title: "Guard and execute the choice",
    summary: "The runtime checks scope and arguments before dispatching the selected action to the real Windows tool.",
    jev: "Selects an offered action with prebuilt arguments; it does not directly control the operating system.",
    runtime: "Applies safety guards, invokes PyAutoGUI, DOM, COM, CLI, MCP, script, or API, and records the receipt."
  },
  verify: {
    kicker: "04 · VERIFY",
    title: "Return independent evidence",
    summary: "A verifier checks the resulting application state, not merely whether the executor reported success.",
    jev: "Consumes the verified result on the next turn and continues, retries, or changes action space.",
    runtime: "Runs task assertions, records wall time and action mix, and terminates only when the task contract is satisfied."
  }
};

async function getJSON(url, retries = 0) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      return data;
    } catch (error) {
      lastError = error;
      if (attempt < retries) await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw lastError;
}

function appIcon(id) {
  return `<img src="/static/icons/${escapeHTML(id)}.svg" width="28" height="28" alt="">`;
}

function renderLoopStep(id) {
  const detail = loopDetails[id];
  if (!detail) return;
  $("#loop-kicker").textContent = detail.kicker;
  $("#loop-title").textContent = detail.title;
  $("#loop-summary").textContent = detail.summary;
  $("#loop-jev").textContent = detail.jev;
  $("#loop-runtime").textContent = detail.runtime;
  document.querySelectorAll("[data-loop-step]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.loopStep === id)));
}

function appPreview(meta, routes) {
  return `<div class="case-window ${meta.className}"><div class="window-bar"><span></span><span></span><span></span><b>${meta.app}</b></div><div class="window-content"><div class="window-sidebar"></div><div class="window-canvas"><i></i><i></i><i></i><i></i></div></div><div class="route-overlay">${routes.slice(0, 4).map((route) => `<span>${escapeHTML(route.split(" · ")[0])}</span>`).join("")}<b>Jev selects ↗</b></div></div>`;
}

function casePreview(id, meta, routes) {
  const sources = demos[id] || {};
  const initial = sources.hybrid || sources.gui_only;
  if (!initial) return appPreview(meta, routes);
  return `<div class="case-video"><video controls muted playsinline preload="metadata" src="${escapeHTML(initial)}" aria-label="${escapeHTML(meta.summary)} demonstration"></video><div class="video-switch" aria-label="Select demonstration mode">${sources.hybrid ? `<button data-video="${escapeHTML(sources.hybrid)}" aria-pressed="${initial === sources.hybrid}">Hybrid</button>` : ""}${sources.gui_only ? `<button data-video="${escapeHTML(sources.gui_only)}" aria-pressed="${initial === sources.gui_only}">GUI Only</button>` : ""}</div></div>`;
}

function renderCases() {
  $("#case-grid").innerHTML = Object.entries(tasks).map(([id, task]) => {
    const meta = caseMeta[id];
    return `<article class="case-card"><div class="case-preview">${casePreview(id, meta, task.hybrid_routes || [])}<span class="case-app-badge">${appIcon(id)}<b>${meta.app}</b></span></div><div class="case-copy"><div class="case-meta"><span>VERIFIED WORKFLOW</span><b>${task.steps} STEPS</b></div><h3>${meta.summary}</h3><p>${escapeHTML(task.description)}</p><small>${meta.stages}</small></div></article>`;
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
  $("#task-tabs").innerHTML = Object.keys(tasks).map((id) => `<button role="tab" aria-selected="${id === selectedTask}" data-task="${id}">${appIcon(id)}<span>${escapeHTML(caseMeta[id].app)}</span></button>`).join("");
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
  const sampleLabel = row.agent === "codex_computer_use" && row.samples === 1 ? "1 pilot run" : `${row.successful_samples}/${row.samples} runs`;
  const usd = row.agent === "codex_computer_use" ? row.median_reference_cost_usd : row.median_model_cost_usd;
  const cost = usd == null ? "—" : `$${usd < 0.01 ? usd.toFixed(4) : usd.toFixed(3)}`;
  return `<div class="result-row"><div class="result-name"><b>${escapeHTML(label)}</b></div><div class="result-track"><i class="${kind}" style="--width:${width}%"></i><strong>${formatMs(duration)}</strong></div><div class="result-cost" aria-label="Estimated model cost"><strong>${cost}</strong></div><div class="result-meta">${sampleLabel} · ${actions} actions</div></div>`;
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
  const request = ++benchmarkRequest;
  const task = tasks[selectedTask];
  $("#benchmark-name").textContent = task.title;
  $("#benchmark-description").textContent = task.description;
  $("#benchmark-rows").setAttribute("aria-busy", "true");
  $("#benchmark-rows").innerHTML = `<div class="empty-results"><b>Loading measured runs</b><span>Reading the local benchmark store…</span></div>`;
  $("#speedup-callout").innerHTML = `<strong>—</strong><span>paired wall-time ratio</span>`;
  $("#benchmark-foot").textContent = "";
  try {
    const { rows = [] } = await getJSON(`/api/benchmarks?task=${encodeURIComponent(selectedTask)}`, 1);
    if (request !== benchmarkRequest) return;
    const maxDuration = Math.max(0, ...rows.map((row) => row.median_wall_time_ms || 0));
    $("#benchmark-rows").innerHTML = rows.length
      ? rows.map((row) => benchmarkRow(row, maxDuration)).join("")
      : `<div class="empty-results"><b>No paired runs yet</b><span>Measured Hybrid and GUI Only results will appear here.</span></div>`;
    const pair = pairedRows(rows);
    if (pair) {
      const [, values] = pair;
      const speedup = values.gui_only.median_wall_time_ms / values.hybrid.median_wall_time_ms;
      const wording = speedup >= 1.02 ? "Hybrid speedup" : "GUI Only ÷ Hybrid";
      $("#speedup-callout").innerHTML = `<strong>${speedup.toFixed(1)}×</strong><span>${wording}</span>`;
      const codexSamples = rows.filter((row) => row.agent === "codex_computer_use").reduce((sum, row) => sum + row.samples, 0);
      const codexNote = codexSamples ? ` · ${codexSamples} Codex pilot ${codexSamples === 1 ? "run" : "runs"}` : "";
      $("#benchmark-foot").textContent = `${values.hybrid.samples + values.gui_only.samples} Jev runs${codexNote} · same terminal verifier`;
    } else {
      $("#speedup-callout").innerHTML = `<strong>—</strong><span>paired speedup</span>`;
      $("#benchmark-foot").textContent = "Only measured runs are shown—no estimated values.";
    }
  } catch (error) {
    if (request !== benchmarkRequest) return;
    $("#speedup-callout").innerHTML = `<strong>—</strong><span>paired wall-time ratio</span>`;
    $("#benchmark-foot").textContent = "The data request failed; no previous task metrics are being shown.";
    $("#benchmark-rows").innerHTML = `<div class="empty-results"><b>Results unavailable</b><span>${escapeHTML(error.message)}</span><button class="retry-button" type="button">Retry</button></div>`;
    $(".retry-button").addEventListener("click", renderBenchmark, { once: true });
  } finally {
    if (request === benchmarkRequest) $("#benchmark-rows").setAttribute("aria-busy", "false");
  }
}

async function boot() {
  try {
    const bootstrap = await getJSON("/api/bootstrap");
    tasks = bootstrap.tasks || {};
    demos = bootstrap.demos || {};
    renderCases();
    renderTabs();
    document.querySelectorAll("[data-loop-step]").forEach((button) => button.addEventListener("click", () => renderLoopStep(button.dataset.loopStep)));
    await Promise.all([renderBenchmark(), renderHeadlineMetrics()]);
  } catch (error) {
    $("#case-grid").innerHTML = `<div class="empty-results"><b>Project data unavailable</b><span>${escapeHTML(error.message)}</span></div>`;
  }
}

boot();
