const $ = (selector) => document.querySelector(selector);
let csrf = "";
let tasks = {};
let selectedTask = "edge";
let currentRun = null;
let selectedRunId = null;
let runs = [];
let benchmark = { rows: [] };
let pollCount = 0;
let viewKind = "waiting";

const channelMeta = {
  gui: { label: "PyAutoGUI / GUI", color: "#315f9d" },
  script: { label: "DOM / COM Script", color: "#15a6a0" },
  api: { label: "API / Filesystem", color: "#ec8a3f" },
  mcp: { label: "MCP", color: "#8a63c7" },
  cli: { label: "CLI", color: "#d5536c" },
  control: { label: "Control", color: "#8794a3" }
};
const agentLabels = { jev: "Jev", rule: "Rule baseline", codex_computer_use: "Codex Computer Use", jev_with_fallback: "Jev + fallback" };
const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
const formatMs = (value) => value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`;
const formatPct = (value) => value == null ? "—" : `${(value * 100).toFixed(0)}%`;

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

function currentMode() { return document.querySelector('input[name="mode"]:checked')?.value || "hybrid"; }
function currentPolicy() { return document.querySelector('input[name="policy"]:checked')?.value || "jev"; }
function taskRoutes(task) { return currentMode() === "hybrid" ? (task.hybrid_routes || task.adaptive_routes) : (task.gui_routes || task.demo_routes); }

function taskCard(id, task) {
  return `<button class="task-card" role="radio" aria-checked="${id === selectedTask}" data-task="${id}"><span class="task-card-head"><b>${escapeHTML(task.title)}</b><span>${task.steps} STEPS</span></span><p>${escapeHTML(task.description)}</p><span class="route-chips">${taskRoutes(task).map((route) => `<span>${escapeHTML(route)}</span>`).join("")}</span></button>`;
}

function renderTasks() {
  $("#task-grid").innerHTML = Object.entries(tasks).map(([id, task]) => taskCard(id, task)).join("");
  document.querySelectorAll("[data-task]").forEach((button) => {
    button.onclick = async () => { selectedTask = button.dataset.task; renderTasks(); await refreshBenchmark(); };
  });
  updateConfig();
}

function updateConfig() {
  const task = tasks[selectedTask];
  const hybrid = currentMode() === "hybrid";
  $("#selected-routes").innerHTML = task ? taskRoutes(task).map((route) => `<span>${escapeHTML(route)}</span>`).join("") : "";
  $("#profile-note").innerHTML = hybrid
    ? "<b>HYBRID ACTION SPACE</b><span>Jev 在 PyAutoGUI、DOM、COM、CLI、MCP 与 API 候选中选择下一条真实可执行路线。</span>"
    : "<b>GUI ONLY</b><span>所有状态改变均通过可见的 PyAutoGUI 完成，作为动作空间消融与录屏对照。</span>";
}

function friendlyReason(reason) {
  const value = String(reason || "");
  if (value.includes("temporarily unreachable") || value.includes("ConnectError")) return "Jev 服务暂时不可达；没有执行桌面动作，可以直接重新运行。";
  if (value.includes("timed out")) return "Jev 请求超时；没有执行桌面动作，可以直接重新运行。";
  if (value.includes("authentication failed")) return "Jev API 鉴权失败，请检查服务进程中的 API Key。";
  return value;
}

function phaseState(events) {
  const completed = new Set();
  for (const event of events) {
    if (event.kind === "observation") completed.add("Observe");
    if (event.kind === "decision") completed.add("Route");
    if (event.kind === "guard") completed.add("Guard");
    if (event.kind === "receipt") completed.add("Execute");
    if (event.kind === "verification") completed.add("Verify");
  }
  const stages = [["Observe", "读取状态"], ["Route", "Jev 选路"], ["Guard", "安全检查"], ["Execute", "真实执行"], ["Verify", "独立验证"]];
  $("#loop-progress").innerHTML = stages.map(([key, label], index) => `<span class="${completed.has(key) ? "complete" : ""}"><i>${index + 1}</i><b>${label}</b></span>`).join("");
}

function groupSteps(events) {
  const steps = [];
  let step = null;
  for (const event of events) {
    if (event.kind === "observation") {
      step = { index: steps.length + 1, observation: event, candidates: null, decision: null, exchange: null, guard: null, receipt: null, verification: null, evaluation: null };
      steps.push(step);
    } else if (step && event.kind === "candidates") step.candidates = event;
    else if (step && event.kind === "decision") step.decision = event;
    else if (step && event.kind === "policy_exchange") step.exchange = event;
    else if (step && event.kind === "guard") step.guard = event;
    else if (step && event.kind === "receipt") step.receipt = event;
    else if (step && event.kind === "verification") step.verification = event;
    else if (step && event.kind === "evaluation") step.evaluation = event;
  }
  return steps;
}

function renderLive(events) {
  $("#event-count").textContent = `${events.length} events`;
  phaseState(events);
  const step = groupSteps(events).at(-1) || null;
  $("#live-empty").hidden = Boolean(step);
  $("#current-action").hidden = !step;
  if (!step) return;
  const decision = step.decision?.payload || {};
  const receipt = step.receipt?.payload || {};
  const verification = step.verification?.payload || {};
  const meta = channelMeta[receipt.channel] || channelMeta.control;
  $("#current-action").innerHTML = `<div class="current-action-top"><span style="--channel:${meta.color}">${escapeHTML(meta.label)}</span><small>STEP ${String(step.index).padStart(2, "0")}</small></div><h3>${escapeHTML(decision.candidate_id || step.observation?.payload?.subgoal || "准备动作")}</h3><p>${escapeHTML(step.observation?.payload?.subgoal || "")}</p><div class="current-action-state"><span>${receipt.success === undefined ? "等待执行" : receipt.success ? "Executor 已完成" : "Executor 失败"}</span><span>${verification.passed === undefined ? "等待验证" : verification.passed ? "Verifier 通过" : "Verifier 未通过"}</span></div>`;
}

function renderCandidateRows(step) {
  const items = step.candidates?.payload?.items || [];
  const decision = step.decision?.payload || {};
  if (!items.length) return '<p class="muted">没有候选路线记录。</p>';
  return `<div class="candidate-list">${items.map((item) => {
    const probability = Number(decision.probabilities?.[item.id] ?? 0);
    const selected = decision.candidate_id === item.id;
    const meta = channelMeta[item.channel] || channelMeta.control;
    return `<div class="candidate-row ${selected ? "selected" : ""}"><i style="--channel:${meta.color}"></i><div><b>${escapeHTML(item.id)}</b><span>${escapeHTML(item.description)}</span></div><em>${escapeHTML(meta.label)}</em><strong>${(probability * 100).toFixed(1)}%</strong></div>`;
  }).join("")}</div>`;
}

function renderStep(step) {
  const observation = step.observation?.payload || {};
  const decision = step.decision?.payload || {};
  const receipt = step.receipt?.payload || {};
  const verification = step.verification?.payload || {};
  const guard = step.guard?.payload || {};
  const meta = channelMeta[receipt.channel] || channelMeta.control;
  const finished = verification.passed === true;
  return `<details class="trace-step"><summary><span class="step-index">${String(step.index).padStart(2, "0")}</span><span class="step-channel" style="--channel:${meta.color}">${escapeHTML(meta.label)}</span><span class="step-copy"><b>${escapeHTML(decision.candidate_id || observation.subgoal || "未决策")}</b><small>${escapeHTML(observation.subgoal || "")}</small></span><span class="step-duration">${formatMs(receipt.duration_ms)}</span><span class="step-result ${finished ? "passed" : ""}">${finished ? "VERIFIED" : receipt.success ? "EXECUTED" : "PENDING"}</span></summary><div class="step-detail"><section><small>OBSERVATION</small><h4>${escapeHTML(observation.subgoal || "状态读取")}</h4><p>source: ${escapeHTML(observation.source || "—")} · observation: ${escapeHTML(String(observation.observation_id || "").slice(0, 10))}</p></section><section><small>CANDIDATE ROUTES + JEV PROBABILITY</small>${renderCandidateRows(step)}</section><div class="evidence-cells"><div><small>GUARD</small><b>${guard.approved ? "Approved" : guard.reason ? "Rejected" : "—"}</b><span>${escapeHTML((guard.checks || []).join(" · ") || guard.reason || "等待检查")}</span></div><div><small>EXECUTOR</small><b>${receipt.success ? "Success" : receipt.error ? "Failed" : "—"}</b><span>${escapeHTML(receipt.capability || "等待执行")} · ${formatMs(receipt.duration_ms)}</span></div><div><small>VERIFIER</small><b>${verification.passed ? "Passed" : verification.verifier ? "Failed" : "—"}</b><span>${escapeHTML(verification.verifier || "等待验证")}</span></div></div></div></details>`;
}

function actionSpaceLabel(run) {
  const space = run.metrics?.action_space;
  if (space === "hybrid") return "Hybrid Action Space";
  if (space === "gui_only") return "GUI Only";
  if (space === "legacy_evaluation") return "Legacy Evaluation";
  return run.execution_profile === "adaptive" ? "Hybrid Action Space" : run.execution_profile === "visible" ? "GUI Only" : "External";
}

function agentLabel(run) {
  if (run.agent) return agentLabels[run.agent] || run.agent;
  return run.metrics?.fallback_count ? "Jev + fallback" : (agentLabels[run.policy] || run.policy);
}

function renderDonut(channels) {
  const entries = Object.entries(channels || {}).filter(([name, count]) => name !== "control" && count > 0);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (!total) {
    $("#action-space-chart").innerHTML = '<div class="donut-empty">NO<br>ROUTES</div>';
    $("#channel-legend").innerHTML = '<span class="muted">没有可视化的动作记录。</span>';
    return;
  }
  let offset = 0;
  const circles = entries.map(([name, count], index) => {
    const value = count / total * 100;
    const color = (channelMeta[name] || channelMeta.control).color;
    const circle = `<circle class="donut-segment" cx="60" cy="60" r="46" pathLength="100" style="--segment:${color};--delay:${index * 70}ms" stroke-dasharray="${value} ${100 - value}" stroke-dashoffset="${-offset}"></circle>`;
    offset += value;
    return circle;
  }).join("");
  $("#action-space-chart").innerHTML = `<svg viewBox="0 0 120 120" aria-hidden="true"><circle class="donut-track" cx="60" cy="60" r="46"></circle>${circles}</svg><div class="donut-center"><b>${entries.length}</b><span>ROUTES</span></div>`;
  $("#channel-legend").innerHTML = entries.map(([name, count]) => { const meta = channelMeta[name] || channelMeta.control; return `<span><i style="--channel:${meta.color}"></i><b>${escapeHTML(meta.label)}</b><em>${count}</em></span>`; }).join("");
}

function renderRunMetrics(run) {
  const metrics = run.metrics || {};
  $("#run-metrics").innerHTML = `<span><b>${formatMs(metrics.wall_time_ms)}</b><small>END-TO-END</small></span><span><b>${formatMs(metrics.decision_time_ms)}</b><small>DECISION</small></span><span><b>${formatMs(metrics.execution_time_ms)}</b><small>EXECUTION</small></span><span><b>${metrics.actions ?? "—"}</b><small>ACTIONS</small></span><span><b>${formatPct(metrics.gui_ratio)}</b><small>GUI SHARE</small></span>`;
}

function renderTrace(run) {
  if (!run) return;
  selectedRunId = run.id;
  $("#trace-placeholder").hidden = true;
  $("#trace-content").hidden = false;
  $("#trace-run-id").textContent = run.id;
  $("#trace-run-title").textContent = tasks[run.task]?.title || run.task;
  $("#trace-run-meta").textContent = `${actionSpaceLabel(run)} · ${agentLabel(run)} · ${new Date(run.created_at * 1000).toLocaleString()}`;
  $("#trace-status").className = `status ${run.status}`;
  $("#trace-status").textContent = run.status;
  renderRunMetrics(run);
  renderDonut(run.metrics?.channels || {});
  const steps = groupSteps(run.events || []);
  const episode = (run.events || []).findLast?.((event) => event.kind === "episode")?.payload;
  $("#route-insight").textContent = episode ? `${steps.length} 次决策 · ${episode.status === "success" ? "终态验证通过" : friendlyReason(episode.reason)}` : run.agent ? "外部 baseline 只保存统一指标和终态证据。" : "运行仍在进行。";
  $("#trace-steps").innerHTML = steps.length ? steps.map(renderStep).join("") : `<div class="trace-empty">${run.agent ? "外部 baseline 没有 CUA-JEV 内部事件；请查看上方统一指标。" : "尚未产生动作步骤。"}</div>`;
  renderRunList();
}

function renderRunList() {
  $("#run-count").textContent = runs.length;
  $("#run-list").innerHTML = runs.length ? runs.map((run) => `<button class="run-item ${run.id === selectedRunId ? "active" : ""}" data-open-run="${escapeHTML(run.id)}"><span><b>${escapeHTML(tasks[run.task]?.title || run.task)}</b><small>${escapeHTML(actionSpaceLabel(run))} · ${escapeHTML(agentLabel(run))}</small></span><em class="status ${escapeHTML(run.status)}">${escapeHTML(run.status)}</em><time>${new Date(run.created_at * 1000).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})}</time></button>`).join("") : '<p class="muted rail-empty">还没有本机实验记录。</p>';
  document.querySelectorAll("[data-open-run]").forEach((button) => { button.onclick = () => { viewKind = "replay"; renderTrace(runs.find((run) => run.id === button.dataset.openRun)); }; });
}

function benchmarkRow(row, maxWall) {
  const width = maxWall && row.median_wall_time_ms ? Math.max(4, row.median_wall_time_ms / maxWall * 100) : 0;
  return `<div class="benchmark-row"><div><b>${escapeHTML(agentLabels[row.agent] || row.agent)}</b><span>${row.action_space === "hybrid" ? "Hybrid Action Space" : "GUI Only"} · success ${row.successful_samples}/${row.samples}</span></div><div class="benchmark-bar"><i style="--bar:${width}%"></i><strong>${formatMs(row.median_wall_time_ms)}</strong></div><span>${formatPct(row.success_rate)} success</span></div>`;
}

function renderBenchmark() {
  const rows = benchmark.rows || [];
  const taskTitle = tasks[selectedTask]?.title || selectedTask;
  $("#benchmark-title").textContent = `${taskTitle} · 端到端耗时中位数`;
  $("#benchmark-sample-count").textContent = `${rows.reduce((sum, row) => sum + row.samples, 0)} samples`;
  const maxWall = Math.max(0, ...rows.map((row) => row.median_wall_time_ms || 0));
  $("#benchmark-chart").innerHTML = rows.length ? rows.map((row) => benchmarkRow(row, maxWall)).join("") : '<div class="benchmark-empty">当前任务还没有可比较的成功运行。先分别运行 Hybrid Action Space 和 GUI Only。</div>';
  const jevHybrid = rows.find((row) => row.agent === "jev" && row.action_space === "hybrid");
  const jevGui = rows.find((row) => row.agent === "jev" && row.action_space === "gui_only");
  const codex = rows.find((row) => row.agent === "codex_computer_use");
  const insights = [];
  if (jevHybrid && jevGui) {
    if (jevHybrid.median_wall_time_ms && jevGui.median_wall_time_ms) {
      const hybridWins = jevHybrid.median_wall_time_ms <= jevGui.median_wall_time_ms;
      const slower = Math.max(jevHybrid.median_wall_time_ms, jevGui.median_wall_time_ms);
      const faster = Math.min(jevHybrid.median_wall_time_ms, jevGui.median_wall_time_ms);
      insights.push(`<span><small>JEV ACTION-SPACE ABLATION</small><b>${hybridWins ? "Hybrid" : "GUI Only"} 成功样本快 ${((slower - faster) / slower * 100).toFixed(0)}%</b></span>`);
    } else insights.push('<span><small>ACTION-SPACE ABLATION</small><b>两个动作空间都需至少一个成功样本</b></span>');
  } else insights.push('<span><small>ACTION-SPACE ABLATION</small><b>需补齐 Jev Hybrid / GUI 样本</b></span>');
  insights.push(codex ? `<span><small>NON-JEV BASELINE</small><b>Codex CU · ${formatMs(codex.median_wall_time_ms)}</b></span>` : '<span><small>NON-JEV BASELINE</small><b>Codex Computer Use 尚未采样</b></span>');
  $("#benchmark-insights").innerHTML = insights.join("");
  $("#benchmark-metrics").innerHTML = rows.length ? rows.map((row) => `<div><b>${escapeHTML(agentLabels[row.agent] || row.agent)} · ${row.action_space === "hybrid" ? "Hybrid" : "GUI"}</b><span><em>${formatMs(row.median_decision_time_ms)}</em> 决策</span><span><em>${formatMs(row.median_execution_time_ms)}</em> 执行</span><span><em>${row.mean_actions == null ? "—" : row.mean_actions.toFixed(1)}</em> 动作</span><span><em>${row.mean_route_diversity == null ? "—" : row.mean_route_diversity.toFixed(1)}</em> 通道</span><span><em>${formatPct(row.mean_gui_ratio)}</em> GUI</span></div>`).join("") : "";
}

function renderRun(run) {
  const running = run?.status === "running";
  $("#runtime-state").textContent = running ? "运行中" : "空闲";
  $("#header-status").textContent = run ? `${viewKind === "replay" ? "REPLAY" : "LIVE"} · ${agentLabel(run).toUpperCase()} · ${run.status}` : "Ready";
  $("#trace-kind").textContent = run ? `03 / ${viewKind === "replay" ? "HISTORY" : "LIVE EXECUTION"}` : "03 / WAITING";
  $("#run-button").disabled = running;
  const failedEpisode = run?.events?.findLast?.((event) => event.kind === "episode")?.payload?.status;
  $("#run-button span").textContent = failedEpisode === "policy_error" ? "重新运行" : "启动实验";
  $("#stop-button").hidden = !running;
  renderLive(run?.events || []);
  if (run) renderTrace(run);
}

async function startRun() {
  $("#action-error").textContent = "";
  try {
    viewKind = "live";
    const run = await api("/api/runs", { task: selectedTask, policy: currentPolicy(), visible_desktop: true, execution_profile: currentMode() === "hybrid" ? "adaptive" : "visible" });
    currentRun = run; selectedRunId = run.id; renderRun(run); await refreshRuns();
  } catch (error) { $("#action-error").textContent = error.message; }
}

async function stopRun() {
  if (!currentRun) return;
  try { currentRun = await api(`/api/runs/${currentRun.id}/stop`, {}); renderRun(currentRun); await refreshRuns(); }
  catch (error) { $("#action-error").textContent = error.message; }
}

async function refreshRuns() {
  const shallow = await api("/api/runs");
  runs = await Promise.all(shallow.slice(0, 30).map((run) => api(`/api/runs/${run.id}`)));
  renderRunList();
  if (selectedRunId && viewKind === "replay") {
    const selected = runs.find((run) => run.id === selectedRunId);
    if (selected) renderTrace(selected);
  }
}

async function refreshBenchmark() { benchmark = await api(`/api/benchmarks?task=${encodeURIComponent(selectedTask)}`); renderBenchmark(); }

async function poll() {
  try {
    const wasRunning = currentRun?.status === "running";
    if (wasRunning) { currentRun = await api(`/api/runs/${currentRun.id}`); renderRun(currentRun); }
    pollCount += 1;
    if (pollCount % 30 === 0 || (wasRunning && currentRun?.status !== "running")) await Promise.all([refreshRuns(), refreshBenchmark()]);
  } catch (error) { $("#action-error").textContent = error.message; }
}

async function init() {
  try {
    const bootstrap = await api("/api/bootstrap");
    csrf = bootstrap.csrf; tasks = bootstrap.tasks;
    $("#key-state").textContent = bootstrap.jev_configured ? "已配置" : "未配置";
    $("#runtime-dot").style.background = bootstrap.jev_configured ? "var(--green)" : "var(--amber)";
    renderTasks(); renderRun(null);
    await Promise.all([refreshRuns(), refreshBenchmark()]);
    if (bootstrap.active_id) { viewKind = "live"; currentRun = await api(`/api/runs/${bootstrap.active_id}`); selectedRunId = currentRun.id; renderRun(currentRun); }
    else if (runs.length) { viewKind = "replay"; renderTrace(runs[0]); }
    $("#run-button").onclick = startRun; $("#stop-button").onclick = stopRun;
    document.querySelectorAll('input[name="mode"]').forEach((input) => { input.onchange = async () => { renderTasks(); await refreshBenchmark(); }; });
    $("#baseline-info").onclick = () => $("#baseline-dialog").showModal();
    $("#close-baseline").onclick = () => $("#baseline-dialog").close();
    setInterval(poll, 900);
  } catch (error) { $("#action-error").textContent = error.message; }
}

init();
