const $ = (selector) => document.querySelector(selector);
let csrf = "";
let tasks = {};
let selectedTask = "edge";
let currentRun = null;
let runs = [];
let pollCount = 0;
let viewKind = "waiting";

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
  const routes = taskRoutes(task);
  return `<button class="task-card" role="radio" aria-checked="${id === selectedTask}" data-task="${id}">
    <span class="task-card-head"><b>${escapeHTML(task.title)}</b><span>${task.steps} STEPS</span></span>
    <p>${escapeHTML(task.description)}</p>
    <span class="route-chips">${routes.map((route) => `<span>${escapeHTML(route)}</span>`).join("")}</span>
  </button>`;
}

function currentMode() { return document.querySelector('input[name="mode"]:checked')?.value || "adaptive"; }
function taskRoutes(task) {
  const mode = currentMode();
  if (mode === "adaptive") return task.adaptive_routes;
  return mode === "physical" ? task.demo_routes : task.evaluation_routes;
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
  const mode = currentMode();
  const demo = mode !== "evaluation";
  $("#selected-routes").innerHTML = task ? taskRoutes(task).map((route) => `<span>${escapeHTML(route)}</span>`).join("") : "";
  $("#route-title").textContent = demo ? "本任务执行链" : "候选执行路线";
  $("#profile-note").innerHTML = mode === "adaptive"
    ? "<b>ADAPTIVE ROUTING</b><span>真实应用保持可见；Jev 同时选择下一子目标和 PyAutoGUI、DOM、COM、CLI、MCP 或 API 路线。</span>"
    : mode === "physical"
      ? "<b>PHYSICAL GUI</b><span>录屏优先：Jev 决定下一步，所有执行都由 PyAutoGUI 在真实应用中清晰呈现。</span>"
      : "<b>ROUTE EVALUATION</b><span>确定性任务开放多种动作空间，并支持 Jev 与 Rule baseline 的可复现对照。</span>";
  $("#visible-desktop").disabled = demo;
  if (demo) $("#visible-desktop").checked = true;
  $("#visible-hint").textContent = demo ? `${mode === "adaptive" ? "Adaptive" : "Physical"} Demo 必须可见运行` : "可选：让支持的桌面通道保持可见";
}

function eventLabel(event, run) {
  const payload = event.payload || {};
  if (event.kind === "observation") return ["Observation", payload.subgoal || payload.task || "状态已读取"];
  if (event.kind === "candidates") return ["Candidates", `${(payload.items || []).length} 条合法路线`];
  if (event.kind === "decision") return [payload.model?.includes("rule-fallback") ? "Fallback Decision" : run?.policy === "rule" ? "Rule Decision" : "Jev Decision", payload.candidate_id || "动作已选择"];
  if (event.kind === "policy_exchange" && payload.fallback) return ["Policy Fallback", `Jev 暂时不可达 · ${payload.fallback.candidate_id}`];
  if (event.kind === "commitment") return ["Commitment", `${payload.intent || "act"} · ${payload.channel || "channel"}`];
  if (event.kind === "guard") return ["Guard", payload.approved ? "安全检查通过" : `拒绝：${payload.reason || "unknown"}`];
  if (event.kind === "receipt") return ["Executor", `${payload.channel || "channel"} · ${payload.success ? "执行成功" : "执行失败"}`];
  if (event.kind === "verification") return ["Verifier", payload.passed ? "验证通过" : "验证失败"];
  if (event.kind === "evaluation") return ["Evaluation", payload.reason || "状态已评估"];
  if (event.kind === "episode") return ["Episode", payload.status || "结束"];
  return [event.kind, "事件已记录"];
}

function friendlyReason(reason) {
  const value = String(reason || "");
  if (value.includes("temporarily unreachable") || value.includes("ConnectError")) {
    return "Jev 服务暂时不可达；没有执行桌面动作。请直接重新运行。";
  }
  if (value.includes("timed out")) return "Jev 请求超时；没有执行桌面动作。请直接重新运行。";
  if (value.includes("authentication failed")) return "Jev API 鉴权失败，请检查服务进程中的 API Key。";
  return value;
}

function renderTimeline(events, run) {
  const visible = events.filter((event) => event.kind !== "candidates" && (event.kind !== "policy_exchange" || event.payload?.fallback)).slice(-18);
  $("#live-empty").hidden = visible.length > 0;
  $("#event-count").textContent = `${events.length} events`;
  $("#timeline").innerHTML = visible.map((event, index) => {
    const [title, detail] = eventLabel(event, run);
    return `<li class="${index === visible.length - 1 ? "current" : ""}"><span class="timeline-top"><span>${escapeHTML(event.suite || "run")}</span><span>${String(index + 1).padStart(2,"0")}</span></span><strong>${escapeHTML(title)}</strong><p>${escapeHTML(detail)}</p></li>`;
  }).join("");
  const completed = new Set();
  for (const event of events) {
    if (event.kind === "observation") completed.add("Observe");
    if (event.kind === "decision") completed.add("Decide");
    if (event.kind === "receipt") completed.add("Act");
    if (event.kind === "verification") completed.add("Verify");
  }
  $("#loop-progress").innerHTML = ["Observe", "Decide", "Act", "Verify"].map((stage, index) =>
    `<span class="${completed.has(stage) ? "complete" : ""}"><i>${index + 1}</i>${stage}</span>`
  ).join("");
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
      return `<div class="candidate ${selected ? "selected" : ""}"><span class="candidate-channel">${escapeHTML(candidate.channel)}<em>${escapeHTML(candidate.intent || "act")}</em></span><span class="candidate-copy"><b>${escapeHTML(candidate.id)}</b><small>${escapeHTML(candidate.description)}</small></span><span class="probability">${(probability * 100).toFixed(1)}%<i style="--p:${probability * 100}%"></i></span></div>`;
    }).join("");
  } else {
    $("#candidate-board").innerHTML = '<p class="muted">运行后显示候选动作与概率。</p>';
  }
  const verification = events.filter((event) => ["guard", "verification", "episode"].includes(event.kind)).slice(-7);
  $("#verification-board").innerHTML = verification.length ? verification.map((event) => {
    const passed = event.kind === "episode" ? event.payload.status === "success" : event.kind === "guard" ? event.payload.approved : event.payload.passed;
    const title = event.kind === "episode" ? `Episode · ${event.payload.status}` : event.kind === "guard" ? `Guard · ${event.payload.approved ? "approved" : "rejected"}` : event.payload.verifier;
    const detail = event.kind === "episode" ? friendlyReason(event.payload.reason) : event.kind === "guard" ? JSON.stringify(event.payload.checks || event.payload.reason || {}) : JSON.stringify(event.payload.details || {});
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
    const profile = run.execution_profile === "adaptive" ? "Adaptive" : run.execution_profile === "visible" ? "Physical" : "Evaluation";
    return `<tr data-run-id="${escapeHTML(run.id)}"><td><button class="history-link" data-open-run="${escapeHTML(run.id)}">${escapeHTML(run.id.slice(0, 15))}</button></td><td>${escapeHTML(tasks[run.task]?.title || run.task)}</td><td>${profile}</td><td>${escapeHTML(run.policy)}</td><td><span class="status ${escapeHTML(run.status)}">${escapeHTML(run.status)}</span></td><td>${escapeHTML(channelSummary(run))}</td><td>${run.status === "completed" ? (success ? "通过" : "未通过") : "—"}</td></tr>`;
  }).join("") : '<tr><td colspan="7" class="muted">还没有本机实验记录。</td></tr>';
  document.querySelectorAll("[data-open-run]").forEach((button) => {
    button.onclick = async () => { viewKind = "replay"; renderRun(await api(`/api/runs/${button.dataset.openRun}`)); location.hash = "evidence"; };
  });
}

function renderRun(run) {
  currentRun = run;
  const running = run?.status === "running";
  $("#runtime-state").textContent = running ? "运行中" : "空闲";
  $("#header-status").textContent = run ? `${viewKind === "replay" ? "REPLAY" : "LIVE"} · ${run.policy.toUpperCase()} · ${run.status}` : "Ready";
  $("#trace-kind").textContent = run ? `03 / ${viewKind === "replay" ? "HISTORY REPLAY" : "LIVE EXECUTION"}` : "03 / WAITING";
  $("#run-button").disabled = running;
  const failedEpisode = run?.events?.findLast?.((event) => event.kind === "episode")?.payload?.status;
  $("#run-button span").textContent = failedEpisode === "policy_error" ? "重新运行" : "启动实验";
  $("#stop-button").hidden = !running;
  renderTimeline(run?.events || [], run);
  renderEvidence(run);
}

async function startRun() {
  $("#action-error").textContent = "";
  const mode = currentMode();
  const policy = mode !== "evaluation" ? "jev" : document.querySelector('input[name="policy"]:checked').value;
  try {
    viewKind = "live";
    renderRun(null);
    const run = await api("/api/runs", {
      task: selectedTask,
      policy,
      visible_desktop: $("#visible-desktop").checked,
      execution_profile: mode === "adaptive" ? "adaptive" : mode === "physical" ? "visible" : "hybrid"
    });
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
    renderRun(null);
    await refreshRuns();
    if (bootstrap.active_id) { viewKind = "live"; renderRun(await api(`/api/runs/${bootstrap.active_id}`)); }
    $("#run-button").onclick = startRun;
    $("#stop-button").onclick = stopRun;
    document.querySelectorAll('input[name="mode"]').forEach((input) => {
      input.onchange = () => {
        $("#evaluation-policy").hidden = input.value !== "evaluation" || !input.checked;
        renderTasks();
      };
    });
    setInterval(poll, 900);
  } catch (error) { $("#action-error").textContent = error.message; }
}

document.addEventListener("DOMContentLoaded", init);
