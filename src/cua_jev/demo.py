from __future__ import annotations

from pathlib import Path

from .executors import FileSystemExecutor, InProcessMcpExecutor, RegisteredCliExecutor
from .guard import ActionGuard
from .models import Channel
from .policy import DecisionPolicy
from .registry import ExecutorRegistry
from .runtime import AgentRuntime, StepResult
from .tasks import load_task
from .trace import JsonlTrace


def filesystem_routing_demo(
    policy: DecisionPolicy,
    workspace: str | Path,
    trace_path: str | Path | None = None,
) -> StepResult:
    root = Path(workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)
    report = root / "sales-summary.txt"
    if not report.exists():
        report.write_text("region,revenue\nEast,120\nWest,95\n", encoding="utf-8")
    task_path = Path(__file__).with_name("predefined") / "inspect_report.json"
    task = load_task(task_path, {"WORKSPACE": str(root), "REPORT": str(report)})

    mcp = InProcessMcpExecutor()
    mcp.register_tool(
        "mcp.filesystem.read_text",
        lambda args: {
            "path": str(Path(args["path"]).resolve()),
            "text": Path(args["path"]).read_text(encoding="utf-8"),
        },
    )
    executors = ExecutorRegistry()
    executors.register(Channel.API, FileSystemExecutor())
    executors.register(Channel.CLI, RegisteredCliExecutor())
    executors.register(Channel.MCP, mcp)
    runtime = AgentRuntime(
        policy=policy,
        guard=ActionGuard(allowed_roots=[root]),
        executors=executors,
        trace=JsonlTrace(trace_path),
    )
    return runtime.step(task.observation, task.candidates)
