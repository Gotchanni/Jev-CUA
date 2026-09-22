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

from ..cost import (
    CODEX_MODEL,
    JEV_MODEL,
    codex_reference_usd,
    codex_standard_credits,
    jev_model_usd,
    token_count,
)
from ..suites import SUITE_NAMES

BENCHMARK_VERSION = "long-horizon-v2"


def _median_present(samples: list[dict[str, Any]], key: str) -> float | None:
    values = [item[key] for item in samples if item.get(key) is not None]
    return median(values) if values else None


def _baseline_steps(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("steps must be a list of at most 50 recorded tool batches")
    steps = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each step must be an object")
        title = item.get("title")
        channel = item.get("channel")
        verified = item.get("verified", False)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 180:
            raise ValueError("Each step needs a short title")
        if not isinstance(channel, str) or channel not in {
            "gui",
            "dom",
            "com",
            "cli",
            "mcp",
            "api",
            "script",
            "verification",
        }:
            raise ValueError("Each step needs a supported channel")
        if not isinstance(verified, bool):
            raise ValueError("Step verified must be a boolean")
        steps.append({"title": title.strip(), "channel": channel, "verified": verified})
    return steps


TASK_CATALOG = {
    "edge": {
        "title": "Edge checkout workflow",
        "description": (
            "Sign in to a public store, sort products, build a two-item cart, complete checkout, "
            "and verify the receipt."
        ),
        "gui_routes": ["PyAutoGUI · Edge", "DOM Observe", "DOM Verify"],
        "hybrid_routes": ["PyAutoGUI · Edge", "Playwright DOM", "DOM Verify"],
        "hybrid_channels": ["gui", "script"],
        "evaluation_routes": ["Visible Edge", "DOM Script", "Page API"],
        "steps": 15,
        "benchmark_version": BENCHMARK_VERSION,
    },
    "excel": {
        "title": "Excel analysis delivery",
        "description": (
            "Compute seven business metrics, mark review status, build two charts, and verify the "
            "workbook in an independent COM session."
        ),
        "gui_routes": ["PyAutoGUI · Excel", "COM Observe", "COM Verify"],
        "hybrid_routes": ["PyAutoGUI · Excel", "Live Excel COM", "COM Verify"],
        "hybrid_channels": ["gui", "script"],
        "evaluation_routes": ["Visible Excel", "Excel COM", "Workbook API"],
        "steps": 11,
        "benchmark_version": BENCHMARK_VERSION,
    },
    "vscode": {
        "title": "VS Code defect repair",
        "description": (
            "Diagnose eight independent defects, choose the repair order and action channel, and "
            "rerun regression tests after each change."
        ),
        "gui_routes": ["PyAutoGUI · VS Code", "Terminal", "Test Verify"],
        "hybrid_routes": ["PyAutoGUI", "MCP", "Filesystem API", "Allowlisted CLI"],
        "hybrid_channels": ["gui", "mcp", "api", "cli"],
        "evaluation_routes": ["Visible VS Code", "MCP", "Filesystem API", "Allowlisted CLI"],
        "steps": 18,
        "benchmark_version": BENCHMARK_VERSION,
    },
    "explorer": {
        "title": "Explorer release pipeline",
        "description": (
            "Select ten eligible reports from a mixed inbox, exclude sensitive material, and produce "
            "five verified release artifacts."
        ),
        "gui_routes": ["PyAutoGUI · Explorer", "PyAutoGUI · Notepad", "File Verify"],
        "hybrid_routes": ["PyAutoGUI", "MCP", "Filesystem API", "Allowlisted CLI"],
        "hybrid_channels": ["gui", "mcp", "api", "cli"],
        "evaluation_routes": ["Visible Explorer", "MCP", "Filesystem API", "Allowlisted CLI"],
        "steps": 16,
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
                raise ValueError("An experiment is already running. Wait for it to finish or stop it first.")
            task = str(spec.get("task", ""))
            policy = str(spec.get("policy", ""))
            if task not in (*SUITE_NAMES, "all") or policy not in {"rule", "jev"}:
                raise ValueError("Invalid task or policy")
            if policy == "jev" and not os.getenv("TYPESAFE_API_KEY"):
                raise ValueError("Set TYPESAFE_API_KEY in the server process before starting a Jev run")

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
                raise ValueError("Invalid execution profile")
            argv.extend(("--profile", execution_profile))
            if (
                policy == "jev"
                and execution_profile in {"visible", "adaptive"}
                and bool(spec.get("policy_fallback"))
            ):
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
                raise ValueError("This experiment has no active process")
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
        all_events = self._events(record, limit=None)
        record["events"] = all_events[-100:]
        record["event_counts"] = dict(Counter(event["kind"] for event in all_events))
        record["metrics"] = self._metrics({**record, "events": all_events})
        return record

    def steps(self, run_id: str) -> dict[str, Any]:
        """Return a bounded, display-safe step view, not raw prompts or tool arguments."""
        record = self._load(run_id)
        if record.get("execution_profile") == "external":
            external = record["external_metrics"]
            batches = external.get("steps", [])
            return {
                "run_id": run_id,
                "source": "recorded_tool_batches" if batches else "not_captured",
                "terminal_verified": bool(external.get("success")),
                "steps": [{"number": number, **item} for number, item in enumerate(batches, 1)],
            }
        steps: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        candidate_titles: dict[str, str] = {}
        terminal_verified = False
        for event in self._events(record, limit=None):
            kind = event.get("kind")
            payload = event.get("payload", {})
            if kind == "observation":
                if current is not None:
                    steps.append(current)
                candidate_titles = {}
                current = {
                    "number": len(steps) + 1,
                    "title": str(payload.get("subgoal") or "Next action")[:180],
                    "channel": None,
                    "capability": None,
                    "decision_ms": None,
                    "execution_ms": None,
                    "verified": None,
                }
            elif kind == "candidates" and current is not None:
                items = payload.get("items")
                candidate_titles = {
                    str(item["id"]): str(item["description"])
                    for item in (items if isinstance(items, list) else [])
                    if isinstance(item, dict) and item.get("id") and item.get("description")
                }
            elif kind == "decision" and current is not None:
                current["decision_ms"] = payload.get("latency_ms")
            elif kind == "commitment" and current is not None:
                current["title"] = candidate_titles.get(str(payload.get("candidate_id")), current["title"])[
                    :180
                ]
                current["channel"] = payload.get("channel")
                current["capability"] = payload.get("capability")
            elif kind == "receipt" and current is not None:
                current["execution_ms"] = payload.get("duration_ms")
            elif kind == "verification" and current is not None:
                current["verified"] = bool(payload.get("passed"))
            elif kind == "episode":
                terminal_verified = payload.get("status") == "success"
        if current is not None:
            steps.append(current)
        return {
            "run_id": run_id,
            "source": "jev_run_trace" if steps else "not_captured",
            "terminal_verified": terminal_verified,
            "steps": steps,
        }

    def import_baseline(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Import a measured external-agent result without inventing unavailable timings."""
        task = str(spec.get("task", ""))
        agent = str(spec.get("agent", ""))
        action_space = str(spec.get("action_space", ""))
        if task not in SUITE_NAMES:
            raise ValueError("Invalid baseline task")
        if agent != "codex_computer_use":
            raise ValueError("Only the codex_computer_use baseline is currently accepted")
        if action_space not in {"hybrid", "gui_only"}:
            raise ValueError("action_space must be hybrid or gui_only")
        try:
            duration_ms = float(spec["duration_ms"])
            actions = int(spec["actions"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("The baseline requires valid duration_ms and actions values") from exc
        if duration_ms <= 0 or actions < 0:
            raise ValueError("Baseline metrics must be non-negative and duration_ms must be positive")
        success = spec.get("success")
        if not isinstance(success, bool):
            raise ValueError("Baseline success must be a boolean")
        channels = spec.get("channels", {"gui": actions})
        if not isinstance(channels, dict) or any(
            not isinstance(key, str) or not isinstance(value, int) or value < 0
            for key, value in channels.items()
        ):
            raise ValueError("Baseline channels must map to non-negative integers")
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
                "steps": _baseline_steps(spec.get("steps", [])),
            },
        }
        run_dir = self.data / run_id
        run_dir.mkdir(parents=True)
        self._save(record)
        return self.detail(run_id)

    def attach_baseline_usage(self, run_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Attach measured local token counters to an existing external pilot."""
        with self._lock:
            record = self._load(run_id)
            if record.get("execution_profile") != "external" or record.get("agent") != "codex_computer_use":
                raise ValueError("Token usage can only be attached to a Codex baseline")
            model = spec.get("model")
            if model != CODEX_MODEL:
                raise ValueError(f"This credit conversion supports only {CODEX_MODEL}")
            usage = {
                name: token_count(spec.get(name), name)
                for name in ("input_tokens", "cached_input_tokens", "output_tokens")
            }
            if usage["cached_input_tokens"] > usage["input_tokens"]:
                raise ValueError("cached_input_tokens cannot exceed input_tokens")
            source = spec.get("source")
            if source != "local_session_token_count":
                raise ValueError("source must identify local_session_token_count")
            record["external_metrics"].update(model=model, token_source=source, **usage)
            self._save(record)
        return self.detail(run_id)

    def attach_baseline_steps(self, run_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Attach a curated trace of actual external tool batches to a pilot record."""
        steps = _baseline_steps(spec.get("steps"))
        if spec.get("source") != "local_session_tool_trace":
            raise ValueError("source must identify local_session_tool_trace")
        with self._lock:
            record = self._load(run_id)
            if record.get("execution_profile") != "external" or record.get("agent") != "codex_computer_use":
                raise ValueError("Tool batches can only be attached to a Codex baseline")
            record["external_metrics"]["steps"] = steps
            record["external_metrics"]["steps_source"] = spec["source"]
            self._save(record)
        return self.steps(run_id)

    def benchmarks(self, task: str | None = None) -> dict[str, Any]:
        if task is not None and task not in SUITE_NAMES:
            raise ValueError("Invalid benchmark task")
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
            metrics["run_id"] = detail["id"]
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
            midpoint = median(wall) if wall else None
            representative = (
                min(successful, key=lambda item: (abs(item["wall_time_ms"] - midpoint), item["run_id"]))[
                    "run_id"
                ]
                if midpoint is not None
                else None
            )
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
                    "representative_run_id": representative,
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
                    "median_input_tokens": _median_present(successful, "input_tokens"),
                    "median_cached_input_tokens": _median_present(successful, "cached_input_tokens"),
                    "median_output_tokens": _median_present(successful, "output_tokens"),
                    "median_model_cost_usd": _median_present(successful, "model_cost_usd"),
                    "median_reference_cost_usd": _median_present(successful, "reference_cost_usd"),
                    "median_standard_credits": _median_present(successful, "standard_credits"),
                    "token_samples": sum(item.get("input_tokens") is not None for item in successful),
                    "cost_samples": sum(
                        item.get("model_cost_usd") is not None or item.get("standard_credits") is not None
                        for item in successful
                    ),
                }
            )
        return {"task": task, "rows": rows}

    def _events(self, record: dict[str, Any], *, limit: int | None = 100) -> list[dict[str, Any]]:
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
        ordered = sorted(events, key=lambda item: item.get("timestamp", 0))
        return ordered if limit is None else ordered[-limit:]

    def _metrics(self, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("external_metrics"):
            external = record["external_metrics"]
            channels = external["channels"]
            actions = external["actions"]
            credits = None
            reference_cost = None
            if external.get("model") == CODEX_MODEL and all(
                external.get(key) is not None
                for key in ("input_tokens", "cached_input_tokens", "output_tokens")
            ):
                credits = codex_standard_credits(
                    external["input_tokens"], external["cached_input_tokens"], external["output_tokens"]
                )
                reference_cost = codex_reference_usd(
                    external["input_tokens"], external["cached_input_tokens"], external["output_tokens"]
                )
            return {
                **external,
                "standard_credits": credits,
                "model_cost_usd": None,
                "reference_cost_usd": reference_cost,
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
        exchanges = [event["payload"] for event in events if event["kind"] == "policy_exchange"]
        priced = bool(exchanges) and all(
            item.get("response", {}).get("model") == JEV_MODEL
            and type(item.get("usage", {}).get("input_tokens")) is int
            and item["usage"]["input_tokens"] >= 0
            and type(item.get("usage", {}).get("output_tokens")) is int
            and item["usage"]["output_tokens"] >= 0
            for item in exchanges
        )
        input_tokens = sum(item["usage"]["input_tokens"] for item in exchanges) if priced else None
        output_tokens = sum(item["usage"]["output_tokens"] for item in exchanges) if priced else None
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
            "input_tokens": input_tokens,
            "cached_input_tokens": None,
            "output_tokens": output_tokens,
            "model_cost_usd": jev_model_usd(input_tokens) if input_tokens is not None else None,
            "reference_cost_usd": None,
            "standard_credits": None,
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
            raise ValueError("Optional timing metrics must be numeric") from exc
        if parsed < 0:
            raise ValueError("Optional timing metrics cannot be negative")
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
