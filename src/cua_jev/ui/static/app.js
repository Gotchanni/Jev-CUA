const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
const formatMs = (value) => value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
const formatPct = (value) => value == null ? "—" : `${(value * 100).toFixed(0)}%`;
const agentLabel = { jev: "Jev", rule: "Rule baseline", codex_computer_use: "Codex Computer Use", jev_with_fallback: "Jev + fallback" };

let tasks = {};
let selectedTask = "edge";

const caseMeta = {
  edge: { index: "01", kicker: "GUI + DOM", stages: ["登录", "排序", "双商品购物车", "填写结算", "验证回执"] },
  excel: { index: "02", kicker: "GUI + COM + API", stages: ["总额", "均值", "最大值", "计数", "双图表", "独立验证"] },
  vscode: { index: "03", kicker: "GUI + CLI + MCP + API", stages: ["初始诊断", "四次修复", "逐次回归", "全量测试", "源码验证"] },
  explorer: { index: "04", kicker: "GUI + CLI + MCP + API", stages: ["筛选五份报告", "逐份归档", "排除敏感项", "生成清单", "发布说明"] }
};

async function getJSON(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function renderCases() {
  $("#case-grid").innerHTML = Object.entries(tasks).map(([id, task]) => {
    const meta = caseMeta[id];
    const routes = task.hybrid_routes || [];
    return `<article class="case-card">
      <div class="case-visual">
        <span class="case-number">${meta.index}</span><span class="video-state">DEMO VIDEO · RECORDING SLOT</span>
        <div class="play-mark" aria-hidden="true"><i></i></div>
        <div class="case-route-line">${routes.map((route) => `<span>${escapeHTML(route)}</span>`).join("")}</div>
      </div>
      <div class="case-body"><div class="case-kicker">${meta.kicker} · ${task.steps} DECISIONS</div><h3>${escapeHTML(task.title)}</h3><p>${escapeHTML(task.description)}</p><ol>${meta.stages.map((stage) => `<li>${escapeHTML(stage)}</li>`).join("")}</ol></div>
    </article>`;
  }).join("");
}

function renderTabs() {
  $("#task-tabs").innerHTML = Object.entries(tasks).map(([id, task]) => `<button role="tab" aria-selected="${id === selectedTask}" data-task="${id}">${escapeHTML(task.title)}<small>${task.steps} steps</small></button>`).join("");
  document.querySelectorAll("[data-task]").forEach((button) => {
    button.addEventListener("click", async () => {
      selectedTask = button.dataset.task;
      renderTabs();
      await renderBenchmark();
    });
  });
}

function benchmarkRow(row, maxDuration) {
  const duration = row.median_wall_time_ms;
  const width = duration && maxDuration ? Math.max(5, duration / maxDuration * 100) : 0;
  const kind = row.action_space === "hybrid" ? "hybrid" : "gui";
  return `<div class="result-row">
    <div><b>${escapeHTML(agentLabel[row.agent] || row.agent)}</b><span>${kind === "hybrid" ? "Hybrid Action Space" : "GUI Only"}</span></div>
    <div class="result-track"><i class="${kind}" style="--width:${width}%"></i><strong>${formatMs(duration)}</strong></div>
    <div class="result-meta"><span>${row.successful_samples}/${row.samples} success</span><span>${row.mean_actions == null ? "—" : row.mean_actions.toFixed(1)} actions</span><span>${formatMs(row.median_decision_time_ms)} decision</span></div>
  </div>`;
}

function pairedRows(rows) {
  const byAgent = new Map();
  rows.forEach((row) => {
    if (!byAgent.has(row.agent)) byAgent.set(row.agent, {});
    byAgent.get(row.agent)[row.action_space] = row;
  });
  return [...byAgent.entries()].find(([, pair]) => pair.hybrid?.median_wall_time_ms && pair.gui_only?.median_wall_time_ms);
}

async function renderBenchmark() {
  const task = tasks[selectedTask];
  $("#benchmark-name").textContent = task.title;
  $("#benchmark-description").textContent = task.description;
  try {
    const benchmark = await getJSON(`/api/benchmarks?task=${encodeURIComponent(selectedTask)}`);
    const rows = benchmark.rows || [];
    const maxDuration = Math.max(0, ...rows.map((row) => row.median_wall_time_ms || 0));
    $("#benchmark-rows").innerHTML = rows.length
      ? rows.map((row) => benchmarkRow(row, maxDuration)).join("")
      : `<div class="empty-results"><b>还没有可发布的配对样本</b><span>运行 Hybrid 与 GUI Only 的重复成功实验后，真实中位数会自动出现在这里。</span></div>`;
    const pair = pairedRows(rows);
    const callout = $("#speedup-callout");
    if (pair) {
      const [agent, values] = pair;
      const speedup = values.gui_only.median_wall_time_ms / values.hybrid.median_wall_time_ms;
      callout.innerHTML = `<strong>${speedup.toFixed(1)}×</strong><span>${escapeHTML(agentLabel[agent] || agent)} paired speedup</span>`;
      $("#benchmark-foot").textContent = `${values.hybrid.samples + values.gui_only.samples} 个真实样本 · 相同终态验证器 · 仅统计成功运行的耗时中位数`;
    } else {
      callout.innerHTML = `<strong>—</strong><span>paired speedup</span>`;
      $("#benchmark-foot").textContent = rows.length ? "已有单侧样本；需要同一决策器的 Hybrid 与 GUI Only 成功运行才能计算加速比。" : "不会用估算值或动画时长替代真实实验数据。";
    }
  } catch (error) {
    $("#benchmark-rows").innerHTML = `<div class="empty-results"><b>实验数据暂时不可读取</b><span>${escapeHTML(error.message)}</span></div>`;
    $("#benchmark-foot").textContent = "请确认本地展示服务仍在运行。";
  }
}

async function boot() {
  try {
    const bootstrap = await getJSON("/api/bootstrap");
    tasks = bootstrap.tasks || {};
    renderTabs();
    renderCases();
    await renderBenchmark();
  } catch (error) {
    $("#case-grid").innerHTML = `<div class="empty-results"><b>项目数据读取失败</b><span>${escapeHTML(error.message)}</span></div>`;
  }
}

boot();
