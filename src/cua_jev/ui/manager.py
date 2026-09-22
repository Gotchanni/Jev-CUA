from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..suites import SUITE_NAMES

TASK_CATALOG = {
    "edge": {
        "title": "Edge 商品筛选",
        "description": "筛选 laptop 商品并导出经过内容校验的 CSV。",
        "routes": ["GUI", "DOM Script", "Page API"],
        "steps": 4,
    },
    "excel": {
        "title": "Excel 销售汇总",
        "description": "写入公式、创建图表，并通过独立 Excel COM 会话复核。",
        "routes": ["Excel COM", "Workbook API"],
        "steps": 3,
    },
    "vscode": {
        "title": "VS Code 测试修复",
        "description": "运行真实测试，在三条修复通道中选择并重新验证。",
        "routes": ["MCP", "Filesystem API", "Allowlisted CLI"],
        "steps": 2,
    },
    "explorer": {
        "title": "文件整理",
        "description": "复制报告并进行字节级一致性检查。",
        "routes": ["MCP", "Filesystem API", "Allowlisted CLI"],
        "steps": 2,
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
            if bool(spec.get("headed_edge")):
                argv.append("--headed-edge")
            if bool(spec.get("open_vscode")):
                argv.append("--open-vscode")
            record = {
                "id": run_id,
                "task": task,
                "policy": policy,
                "headed_edge": bool(spec.get("headed_edge")),
                "open_vscode": bool(spec.get("open_vscode")),
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
        summary_path = Path(record["summary_path"])
        record["summary"] = self._read_json(summary_path) if summary_path.is_file() else None
        log_path = Path(record["log_path"])
        record["log"] = (
            log_path.read_text(encoding="utf-8", errors="replace")[-20_000:]
            if log_path.is_file()
            else ""
        )
        record["events"] = self._events(record)
        return record

    def _events(self, record: dict[str, Any]) -> list[dict[str, Any]]:
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
