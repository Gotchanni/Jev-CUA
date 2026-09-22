const $ = (selector) => document.querySelector(selector);
let csrf = "";
let tasks = {};
let selectedTask = "edge";
let currentRun = null;
let runs = [];
let pollCount = 0;

const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);

async function api(url, body, method) {
  const options = { method: method || (body === undefined ? "GET" : "POST"), headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.headers["X-CUA-JEV-CSRF"] = csrf;
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function taskCard(id, task) {
  return `<button class="task-card" role="radio" aria-checked="${id === selectedTask}" data-task="${id}">
    <span class="task-card-head"><b>${escapeHTML(task.title)}</b><span>${task.steps} STEPS</span></span>
    <p>${escapeHTML(task.description)}</p>
    <span class="route-chips">${task.routes.map((route) => `<span>${escapeHTML(route)}</span>`).join("")}</span>
  </button>`;
}

function renderTasks() {
  $("#task-grid").innerHTML = Object.entries(tasks).map(([id, task]) => taskCard(id, task)).join("");
  document.querySelectorAll("[data-task]").forEach((button) => {
    button.onclick = () => { selectedTask = button.dataset.task; renderTasks(); updateConfig(); };
  });
  updateConfig();
}

function updateConfig() {
  const task = tasks[selectedTask];
  $("#selected-routes").innerHTML = task ? task.routes.map((route) => `<span>${escapeHTML(route)}</span>`).join("") : "";
  $("#headed-edge").closest("label").hidden = !["edge", "all"].includes(selectedTask);
  $("#open-vscode").closest("label").hidden = !["vscode", "all"].includes(selectedTask);
}

function eventLabel(event) {
  const payload = event.payload || {};
  if (event.kind === "observation") return ["Observation", payload.subgoal || payload.task || "状态已读取"];
  if (event.kind === "candidates") return ["Candidates", `${(payload.items || []).length} 条合法路线`];
  if (event.kind === "decision") return ["Jev Decision", payload.candidate_id || "动作已选择"];
  if (event.kind === "receipt") return ["Executor", `${payload.channel || "channel"} · ${payload.success ? "执行成功" : "执行失败"}`];
  if (event.kind === "verification") return ["Verifier", payload.passed ? "验证通过" : "验证失败"];
  if (event.kind === "evaluation") return ["Evaluation", payload.reason || "状态已评估"];
  if (event.kind === "episode") return ["Episode", payload.status || "结束"];
  return [event.kind, "事件已记录"];
}

function renderTimeline(events) {
  const visible = events.filter((event) => !["candidates"].includes(event.kind)).slice(-12);
  $("#live-empty").hidden = visible.length > 0;
  $("#event-count").textContent = `${events.length} events`;
  $("#timeline").innerHTML = visible.map((event, index) => {
    const [title, detail] = eventLabel(event);
    return `<li class="${index === visible.length - 1 ? "current" : ""}"><span class="timeline-top"><span>${escapeHTML(event.suite || "run")}</span><span>${String(index + 1).padStart(2,"0")}</span></span><strong>${escapeHTML(title)}</strong><p>${escapeHTML(detail)}</p></li>`;
  }).join("");
}

function latestPair(events) {
  let pending = null;
  let latest = { candidates: null, decision: null };
  let latestCompetitive = null;
  for (const event of events) {
    if (event.kind === "candidates") pending = event.payload.items || [];
    if (event.kind === "decision" && pending) {
      latest = { candidates: pending, decision: event.payload };
      if (pending.length > 1) latestCompetitive = latest;
      pending = null;
    }
  }
  return latestCompetitive || latest;
}

function renderEvidence(run) {
  const events = run?.events || [];
  const { candidates, decision } = latestPair(events);
  if (candidates?.length) {
    $("#candidate-board").innerHTML = candidates.map((candidate) => {
      const probability = Number(decision?.probabilities?.[candidate.id] ?? 0);
      const selected = decision?.candidate_id === candidate.id;
      return `<div class="candidate ${selected ? "selected" : ""}"><span class="candidate-channel">${escapeHTML(candidate.channel)}</span><span class="candidate-copy"><b>${escapeHTML(candidate.id)}</b><small>${escapeHTML(candidate.description)}</small></span><span class="probability">${(probability * 100).toFixed(1)}%<i style="--p:${probability * 100}%"></i></span></div>`;
    }).join("");
  } else {
    $("#candidate-board").innerHTML = '<p class="muted">运行后显示候选动作与概率。</p>';
  }
  const verification = events.filter((event) => event.kind === "verification" || event.kind === "episode").slice(-5);
  $("#verification-board").innerHTML = verification.length ? verification.map((event) => {
    const passed = event.kind === "episode" ? event.payload.status === "success" : event.payload.passed;
    const title = event.kind === "episode" ? `Episode · ${event.payload.status}` : event.payload.verifier;
    const detail = event.kind === "episode" ? event.payload.reason : JSON.stringify(event.payload.details || {});
    return `<div class="verification-item ${passed ? "" : "failed"}"><b>${escapeHTML(title)}</b><span>${escapeHTML(detail)}</span></div>`;
  }).join("") : '<p class="muted">独立验证结果会出现在这里。</p>';
  const summary = run?.summary;
  const suites = summary?.suites || [];
  const successes = suites.reduce((sum, item) => sum + item.successes, 0);
  const duration = suites.reduce((sum, item) => sum + item.mean_duration_ms, 0);
  const steps = events.filter((event) => event.kind === "receipt").length;
  $("#run-metrics").innerHTML = run ? `<span><b>${successes}/${suites.length || "—"}</b><small>SUITES</small></span><span><b>${steps}</b><small>ACTIONS</small></span><span><b>${duration ? (duration / 1000).toFixed(1) + "s" : "—"}</b><small>WALL TIME</small></span>` : "";
}

function channelSummary(run) {
  const channels = {};
  for (const suite of run.summary?.suites || []) for (const [name, count] of Object.entries(suite.channels || {})) channels[name] = (channels[name] || 0) + count;
  return Object.entries(channels).filter(([name]) => name !== "control").map(([name, count]) => `${name}×${count}`).join(" · ") || "—";
}

function renderHistory() {
  $("#history-body").innerHTML = runs.length ? runs.slice(0, 12).map((run) => {
    const success = run.summary?.all_passed;
    return `<tr><td>${escapeHTML(run.id.slice(0, 15))}</td><td>${escapeHTML(tasks[run.task]?.title || run.task)}</td><td>${escapeHTML(run.policy)}</td><td><span class="status ${escapeHTML(run.status)}">${escapeHTML(run.status)}</span></td><td>${escapeHTML(channelSummary(run))}</td><td>${run.status === "completed" ? (success ? "通过" : "未通过") : "—"}</td></tr>`;
  }).join("") : '<tr><td colspan="6" class="muted">还没有本机实验记录。</td></tr>';
}

function renderRun(run) {
  currentRun = run;
  const running = run?.status === "running";
  $("#runtime-state").textContent = running ? "运行中" : "空闲";
  $("#header-status").textContent = run ? run.status : "Ready";
  $("#run-button").disabled = running;
  $("#stop-button").hidden = !running;
  renderTimeline(run?.events || []);
  renderEvidence(run);
}

async function startRun() {
  $("#action-error").textContent = "";
  const policy = document.querySelector('input[name="policy"]:checked').value;
  try {
    const run = await api("/api/runs", { task: selectedTask, policy, headed_edge: $("#headed-edge").checked, open_vscode: $("#open-vscode").checked });
    renderRun(run);
    await refreshRuns();
  } catch (error) { $("#action-error").textContent = error.message; }
}

async function stopRun() {
  if (!currentRun) return;
  try { renderRun(await api(`/api/runs/${currentRun.id}/stop`, {})); await refreshRuns(); }
  catch (error) { $("#action-error").textContent = error.message; }
}

async function refreshRuns() {
  const shallow = await api("/api/runs");
  runs = await Promise.all(shallow.slice(0, 12).map((run) => api(`/api/runs/${run.id}`)));
  renderHistory();
}

async function poll() {
  try {
    const wasRunning = currentRun?.status === "running";
    if (wasRunning) renderRun(await api(`/api/runs/${currentRun.id}`));
    pollCount += 1;
    if (pollCount % 5 === 0 || (wasRunning && currentRun?.status !== "running")) await refreshRuns();
  } catch (error) { $("#action-error").textContent = error.message; }
}

async function init() {
  try {
    const bootstrap = await api("/api/bootstrap");
    csrf = bootstrap.csrf;
    tasks = bootstrap.tasks;
    $("#key-state").textContent = bootstrap.jev_configured ? "已配置" : "未配置";
    $("#runtime-dot").style.background = bootstrap.jev_configured ? "var(--green)" : "var(--amber)";
    renderTasks();
    await refreshRuns();
    if (bootstrap.active_id) renderRun(await api(`/api/runs/${bootstrap.active_id}`));
    else if (runs.length) renderRun(runs[0]);
    $("#run-button").onclick = startRun;
    $("#stop-button").onclick = stopRun;
    setInterval(poll, 900);
  } catch (error) { $("#action-error").textContent = error.message; }
}

document.addEventListener("DOMContentLoaded", init);
