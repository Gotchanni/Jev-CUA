from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from .episode import Evaluation
from .executors import ControlExecutor, FileSystemExecutor, InProcessMcpExecutor
from .models import ActionCandidate, ActionReceipt, Channel, Observation, Risk, Verification
from .runtime import StepResult


def sandbox_mcp_executor() -> InProcessMcpExecutor:
    executor = InProcessMcpExecutor()

    def copy_file(arguments):
        source = Path(arguments["source_path"])
        destination = Path(arguments["destination_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {"source": str(source.resolve()), "destination": str(destination.resolve())}

    executor.register_tool("mcp.filesystem.copy", copy_file)

    def write_text(arguments):
        path = Path(arguments["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        text = str(arguments["text"])
        path.write_text(text, encoding=arguments.get("encoding", "utf-8"))
        return {"path": str(path.resolve()), "characters": len(text)}

    executor.register_tool("mcp.filesystem.write_text", write_text)
    return executor


class FileOrganizationTask:
    """A resettable two-step fixture: copy a report, then independently declare completion."""

    name = "explorer-organize-fixture"

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.inbox = self.workspace / "inbox"
        self.archive = self.workspace / "archive"
        self.source = self.inbox / "sales.txt"
        self.destination = self.archive / "sales.txt"

    def reset(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.archive.mkdir(parents=True, exist_ok=True)
        self.source.write_text("quarter=Q3\nrevenue=120\n", encoding="utf-8")
        if self.destination.exists():
            self.destination.unlink()

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.workspace,)

    def executor_bindings(self) -> dict[Channel, object]:
        return {
            Channel.API: FileSystemExecutor(),
            Channel.MCP: sandbox_mcp_executor(),
            Channel.CONTROL: ControlExecutor(),
        }

    def observe(self, history: Sequence[StepResult]) -> Observation:
        destination_exists = self.destination.exists()
        destination_text = self.destination.read_text(encoding="utf-8") if destination_exists else None
        return Observation(
            task="Archive the sales report without modifying its content.",
            subgoal="Confirm completion" if destination_exists else "Copy the report into archive",
            state={
                "source_path": str(self.source),
                "destination_path": str(self.destination),
                "source_exists": self.source.exists(),
                "destination_exists": destination_exists,
                "destination_text": destination_text,
            },
            source=self.name,
        )

    def candidates(
        self, observation: Observation, history: Sequence[StepResult]
    ) -> Sequence[ActionCandidate]:
        if observation.state["destination_exists"]:
            return (
                ActionCandidate(
                    "done",
                    Channel.CONTROL,
                    "control.done",
                    "Declare completion for independent task verification.",
                ),
            )
        return (
            ActionCandidate(
                "mcp_copy",
                Channel.MCP,
                "mcp.filesystem.copy",
                "Copy the report through the registered filesystem MCP tool.",
                {"source_path": str(self.source), "destination_path": str(self.destination)},
                Risk.LOCAL_WRITE,
                verifier="file.exists",
                expected={"path": str(self.destination)},
            ),
            ActionCandidate(
                "api_copy",
                Channel.API,
                "filesystem.copy",
                "Copy the report through the typed filesystem API.",
                {"source_path": str(self.source), "destination_path": str(self.destination)},
                Risk.LOCAL_WRITE,
                verifier="file.exists",
                expected={"path": str(self.destination)},
            ),
        )

    def evaluate(
        self,
        observation: Observation,
        candidate: ActionCandidate,
        receipt: ActionReceipt,
        verification: Verification,
    ) -> Evaluation:
        if not receipt.success or not verification.passed:
            return Evaluation(False, False, "action_not_verified")
        if candidate.capability != "control.done":
            return Evaluation(False, False, "copy_completed; reobserve")
        expected = self.source.read_bytes()
        valid = self.destination.exists() and self.destination.read_bytes() == expected
        return Evaluation(valid, True, "archive_verified" if valid else "archive_content_mismatch")
