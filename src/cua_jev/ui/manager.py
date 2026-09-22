from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from ..suites import SUITE_NAMES

BENCHMARK_VERSION = "long-horizon-v1"

TASK_CATALOG = {
    "edge": {
        "title": "Edge 长程采购",
        "description": "登录公开商店、排序、构建双商品购物车、填写结算信息并验证订单回执。",
        "gui_routes": ["PyAutoGUI · Edge", "DOM Observe", "DOM Verify"],
        "hybrid_routes": ["PyAutoGUI · Edge", "Playwright DOM", "DOM Verify"],
        "hybrid_channels": ["gui", "script"],
        "evaluation_routes": ["Visible Edge", "DOM Script", "Page API"],
        "steps": 15,
        "benchmark_version": BENCHMARK_VERSION,
    },
    "excel": {
        "title": "Excel 分析交付",
        "description": "计算四项指标、标记复核状态、创建两张图表，再由独立 COM 会话验证。",
        "gui_routes": ["PyAutoGUI · Excel", "COM Observe", "COM Verify"],
        "hybrid_routes": ["PyAutoGUI · Excel", "Live Excel COM", "COM Verify"],
        "hybrid_channels": ["gui", "script"],
        "evaluation_routes": ["Visible Excel", "Excel COM", "Workbook API"],
        "steps": 8,
        "benchmark_version": BENCHMARK_VERSION,
    },
    "vscode": {
        "title": "VS Code 测试修复",
        "description": "诊断四个独立缺陷，选择修复顺序和通道，并在每次修改后重跑回归测试。",
        "gui_routes": ["PyAutoGUI · VS Code", "Terminal", "Test Verify"],
        "hybrid_routes": ["PyAutoGUI", "MCP", "Filesystem API", "Allowlisted CLI"],
        "hybrid_channels": ["gui", "mcp", "api", "cli"],
        "evaluation_routes": ["Visible VS Code", "MCP", "Filesystem API", "Allowlisted CLI"],
        "steps": 10,
        "benchmark_version": BENCHMARK_VERSION,
    },
    "explorer": {
        "title": "Explorer 发布流水线",
        "description": "从混合收件箱筛选五份合格报告，排除敏感材料并生成发布清单与说明。",
        "gui_routes": ["PyAutoGUI · Explorer", "PyAutoGUI · Notepad", "File Verify"],
        "hybrid_routes": ["PyAutoGUI", "MCP", "Filesystem API", "Allowlisted CLI"],
        "hybrid_channels": ["gui", "mcp", "api", "cli"],
        "evaluation_routes": ["Visible Explorer", "MCP", "Filesystem API", "Allowlisted CLI"],
        "steps": 8,
        "benchmark_version": BENCHMARK_VERSION,
    },
}


class RunManager:
    """One-at-a-time local subprocess manager with JSON-backed run history."""

    def __init__(self, root: str | Path, data: str | Path | None = None) -> None:
        self.root = Path(root).resolve()
        self.data = Path(data or self.root / "runs" / "ui").resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._log_handle = None
        self._active_id: str | None = None

    @property
    def active_id(self) -> str | None:
        self._refresh_active()
        return self._active_id

    def create(self, spec: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._refresh_active()
            if self._active_id:
                raise ValueError("已有实验正在运行，请等待完成或先停止")
            task = str(spec.get("task", ""))
            policy = str(spec.get("policy", ""))
            if task not in (*SUITE_NAMES, "all") or policy not in {"rule", "jev"}:
                raise ValueError("无效的任务或策略")
            if policy == "jev" and not os.getenv("TYPESAFE_API_KEY"):
                raise ValueError("启动 Jev 实验前，请先在服务进程中设置 TYPESAFE_API_KEY")

            run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
            run_dir = self.data / run_id
            run_dir.mkdir(parents=True)
            workspace = run_dir / "workspace"
            summary = run_dir / "summary.json"
            trace = run_dir / "trace.jsonl"
            log = run_dir / "console.log"
            argv = [
                sys.executable,
                "-m",
                "cua_jev.cli",
                "suite",
                "--task",
                task,
                "--policy",
                policy,
                "--episodes",
                "1",
                "--workspace",
                str(workspace),
                "--output",
                str(summary),
                "--trace",
                str(trace),
            ]
            visible_desktop = bool(spec.get("visible_desktop"))
            execution_profile = str(spec.get("execution_profile", "hybrid"))
            if execution_profile not in {"hybrid", "visible", "adaptive"}:
                raise ValueError("无效的执行配置")
            argv.extend(("--profile", execution_profile))
            if policy == "jev" and execution_profile in {"visible", "adaptive"}:
                argv.append("--policy-fallback")
            if visible_desktop:
                argv.append("--headed-edge")
                argv.append("--open-vscode")
                argv.append("--visible-apps")
            record = {
                "id": run_id,
                "task": task,
                "benchmark_version": BENCHMARK_VERSION,
                "policy": policy,
                "visible_desktop": visible_desktop,
                "execution_profile": execution_profile,
                "status": "running",
                "created_at": time.time(),
                "updated_at": time.time(),
                "workspace": str(workspace),
                "summary_path": str(summary),
                "trace_base": str(trace),
                "log_path": str(log),
            }
            self._save(record)
            self._log_handle = log.open("w", encoding="utf-8")
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._process = subprocess.Popen(
                argv,
                cwd=self.root,
                env=os.environ.copy(),
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=creationflags,
            )
            self._active_id = run_id
            return self.detail(run_id)

    def stop(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_active()
            if run_id != self._active_id or self._process is None:
                raise ValueError("该实验当前没有运行中的进程")
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            record = self._load(run_id)
            record.update(status="stopped", updated_at=time.time(), returncode=self._process.returncode)
            self._save(record)
            self._finish_process()
            return self.detail(run_id)

    def list(self) -> list[dict[str, Any]]:
        self._refresh_active()
        records = [self._load(path.parent.name) for path in self.data.glob("*/run.json")]
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def detail(self, run_id: str) -> dict[str, Any]:
        self._refresh_active()
        record = self._load(run_id)
        summary_path = Path(record["summary_path"]) if record.get("summary_path") else None
        record["summary"] = (
            self._read_json(summary_path) if summary_path is not None and summary_path.is_file() else None
        )
        log_path = Path(record["log_path"]) if record.get("log_path") else None
        record["log"] = (
            log_path.read_text(encoding="utf-8", errors="replace")[-20_000:]
            if log_path is not None and log_path.is_file()
            else ""
        )
        record["events"] = self._events(record)
        record["metrics"] = self._metrics(record)
        return record

    def import_baseline(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Import a measured external-agent result without inventing unavailable timings."""
        task = str(spec.get("task", ""))
        agent = str(spec.get("agent", ""))
        action_space = str(spec.get("action_space", ""))
        if task not in SUITE_NAMES:
            raise ValueError("无效的 baseline 任务")
        if agent != "codex_computer_use":
            raise ValueError("目前只接受 codex_computer_use baseline")
        if action_space not in {"hybrid", "gui_only"}:
            raise ValueError("action_space 必须是 hybrid 或 gui_only")
        try:
            duration_ms = float(spec["duration_ms"])
            actions = int(spec["actions"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("baseline 需要有效的 duration_ms 和 actions") from exc
        if duration_ms <= 0 or actions < 0:
            raise ValueError("baseline 指标必须为非负值，duration_ms 必须大于零")
        success = spec.get("success")
        if not isinstance(success, bool):
            raise ValueError("baseline success 必须是布尔值")
        channels = spec.get("channels", {"gui": actions})
        if not isinstance(channels, dict) or any(
            not isinstance(key, str) or not isinstance(value, int) or value < 0
            for key, value in channels.items()
        ):
            raise ValueError("baseline channels 必须是非负整数映射")
        run_id = f"external-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        record = {
            "id": run_id,
            "task": task,
            "benchmark_version": TASK_CATALOG[task]["benchmark_version"],
            "policy": agent,
            "agent": agent,
            "execution_profile": "external",
            "action_space": action_space,
            "status": "completed",
            "created_at": float(spec.get("created_at", time.time())),
            "updated_at": time.time(),
            "external_metrics": {
                "success": success,
                "wall_time_ms": duration_ms,
                "actions": actions,
                "decision_time_ms": self._optional_nonnegative(spec.get("decision_time_ms")),
                "execution_time_ms": self._optional_nonnegative(spec.get("execution_time_ms")),
                "channels": channels,
                "verifier": str(spec.get("verifier", "shared_terminal_verifier")),
                "evidence": str(spec.get("evidence", "")),
            },
        }
        run_dir = self.data / run_id
        run_dir.mkdir(parents=True)
        self._save(record)
        return self.detail(run_id)

    def benchmarks(self, task: str | None = None) -> dict[str, Any]:
        if task is not None and task not in SUITE_NAMES:
            raise ValueError("无效的 benchmark 任务")
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for record in self.list():
            if task and record["task"] != task:
                continue
            record_task = record.get("task")
            if record_task not in TASK_CATALOG:
                continue
            if record.get("benchmark_version") != TASK_CATALOG[record_task]["benchmark_version"]:
                continue
            detail = self.detail(record["id"])
            metrics = detail["metrics"]
            if detail["status"] not in {"completed", "failed"} or metrics["wall_time_ms"] is None:
                continue
            if metrics["action_space"] == "legacy_evaluation":
                continue
            # A fallback run is useful evidence, but is not a pure Jev benchmark sample.
            agent = self._agent_label(detail, metrics)
            groups[(agent, metrics["action_space"])].append(metrics)
        rows = []
        for (agent, action_space), samples in sorted(groups.items()):
            successful = [item for item in samples if item["success"]]
            wall = [item["wall_time_ms"] for item in successful]
            decisions = [
                item["decision_time_ms"] for item in successful if item["decision_time_ms"] is not None
            ]
            executions = [
                item["execution_time_ms"] for item in successful if item["execution_time_ms"] is not None
            ]
            rows.append(
                {
                    "agent": agent,
                    "action_space": action_space,
                    "samples": len(samples),
                    "successful_samples": len(successful),
                    "success_rate": mean(float(item["success"]) for item in samples),
                    "median_wall_time_ms": median(wall) if wall else None,
                    "mean_wall_time_ms": mean(wall) if wall else None,
                    "median_decision_time_ms": median(decisions) if decisions else None,
                    "median_execution_time_ms": median(executions) if executions else None,
                    "mean_actions": mean(item["actions"] for item in successful) if successful else None,
                    "mean_gui_ratio": (
                        mean(item["gui_ratio"] for item in successful) if successful else None
                    ),
                    "mean_route_diversity": (
                        mean(item["route_diversity"] for item in successful) if successful else None
                    ),
                }
            )
        return {"task": task, "rows": rows}

    def _events(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        if record.get("execution_profile") == "external":
            return []
        base = Path(record["trace_base"])
        names = SUITE_NAMES if record["task"] == "all" else (record["task"],)
        events: list[dict[str, Any]] = []
        for name in names:
            path = base.with_name(f"{base.stem}-{name}{base.suffix}")
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                item["suite"] = name
                events.append(item)
        return sorted(events, key=lambda item: item.get("timestamp", 0))[-100:]

    def _metrics(self, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("external_metrics"):
            external = record["external_metrics"]
            channels = external["channels"]
            actions = external["actions"]
            return {
                **external,
                "action_space": record["action_space"],
                "gui_ratio": channels.get("gui", 0) / actions if actions else 0.0,
                "route_diversity": len([name for name, count in channels.items() if count]),
                "route_switches": None,
                "fallback_count": 0,
            }
        events = record.get("events", [])
        receipts = [
            event["payload"]
            for event in events
            if event["kind"] == "receipt" and event["payload"].get("channel") != "control"
        ]
        decisions = [event["payload"] for event in events if event["kind"] == "decision"]
        episodes = [event["payload"] for event in events if event["kind"] == "episode"]
        channels = Counter(str(item.get("channel", "unknown")) for item in receipts)
        sequence = [str(item.get("channel", "unknown")) for item in receipts]
        decision_latencies = [float(item.get("latency_ms", 0)) for item in decisions]
        execution_latencies = [float(item.get("duration_ms", 0)) for item in receipts]
        fallback_count = sum(
            1 for event in events if event["kind"] == "policy_exchange" and event["payload"].get("fallback")
        )
        wall_time = sum(float(item.get("duration_ms", 0)) for item in episodes) if episodes else None
        success = bool(episodes) and all(item.get("status") == "success" for item in episodes)
        actions = len(receipts)
        profile = record.get("execution_profile")
        action_space = {
            "adaptive": "hybrid",
            "visible": "gui_only",
            "hybrid": "legacy_evaluation",
        }.get(profile, "legacy_evaluation")
        return {
            "success": success,
            "wall_time_ms": wall_time,
            "decision_time_ms": sum(decision_latencies) if decision_latencies else None,
            "median_decision_latency_ms": median(decision_latencies) if decision_latencies else None,
            "execution_time_ms": sum(execution_latencies) if execution_latencies else None,
            "actions": actions,
            "channels": dict(channels),
            "gui_ratio": channels.get("gui", 0) / actions if actions else 0.0,
            "route_diversity": len(channels),
            "route_switches": sum(a != b for a, b in zip(sequence, sequence[1:], strict=False)),
            "fallback_count": fallback_count,
            "action_space": action_space,
        }

    @staticmethod
    def _agent_label(record: dict[str, Any], metrics: dict[str, Any]) -> str:
        if record.get("agent"):
            return str(record["agent"])
        if record.get("policy") == "jev" and metrics["fallback_count"]:
            return "jev_with_fallback"
        return str(record.get("policy", "unknown"))

    @staticmethod
    def _optional_nonnegative(value: Any) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("可选时间指标必须是数值") from exc
        if parsed < 0:
            raise ValueError("可选时间指标不能为负数")
        return parsed

    def _refresh_active(self) -> None:
        with self._lock:
            if self._process is None or self._active_id is None:
                return
            returncode = self._process.poll()
            if returncode is None:
                return
            record = self._load(self._active_id)
            record.update(
                status="completed" if returncode == 0 else "failed",
                updated_at=time.time(),
                returncode=returncode,
            )
            self._save(record)
            self._finish_process()

    def _finish_process(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
        self._log_handle = None
        self._process = None
        self._active_id = None

    def _record_path(self, run_id: str) -> Path:
        path = (self.data / run_id / "run.json").resolve()
        if self.data not in path.parents:
            raise KeyError(run_id)
        return path

    def _load(self, run_id: str) -> dict[str, Any]:
        path = self._record_path(run_id)
        if not path.is_file():
            raise KeyError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, record: dict[str, Any]) -> None:
        path = self._record_path(record["id"])
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
