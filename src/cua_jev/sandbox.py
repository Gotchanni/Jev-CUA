from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from .episode import Evaluation
from .executors import (
    ControlExecutor,
    ExplorerUiaExecutor,
    FileSystemExecutor,
    InProcessMcpExecutor,
    RegisteredCliExecutor,
)
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
    """Select two publishable reports, archive them, then build and verify a manifest."""

    name = "explorer-organize-fixture"

    def __init__(self, workspace: str | Path, *, visible: bool = False) -> None:
        self.workspace = Path(workspace).resolve()
        self.inbox = self.workspace / "inbox"
        self.archive = self.workspace / "archive"
        self.visible = visible
        self.sources = {
            "sales": self.inbox / "sales-Q3.txt",
            "inventory": self.inbox / "inventory-Q3.txt",
        }
        self.destinations = {name: self.archive / path.name for name, path in self.sources.items()}
        self.manifest = self.archive / "manifest.txt"

    def reset(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.archive.mkdir(parents=True, exist_ok=True)
        fixtures = {
            "sales-Q3.txt": "quarter=Q3\nrevenue=120\nstatus=final\n",
            "inventory-Q3.txt": "quarter=Q3\nitems=42\nstatus=final\n",
            "draft-notes.txt": "status=draft\ndo_not_publish=true\n",
            "sales-Q2.txt": "quarter=Q2\nstatus=final\n",
        }
        for name, content in fixtures.items():
            (self.inbox / name).write_text(content, encoding="utf-8")
        for path in (*self.destinations.values(), self.manifest):
            if path.exists():
                path.unlink()

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.workspace,)

    def executor_bindings(self) -> dict[Channel, object]:
        cli = RegisteredCliExecutor()
        cli.register(
            "cli.copy_file",
            lambda args: [
                sys.executable,
                "-m",
                "cua_jev.tools",
                "copy-file",
                args["source_path"],
                args["destination_path"],
            ],
        )
        cli.register(
            "cli.write_text",
            lambda args: [
                sys.executable,
                "-m",
                "cua_jev.tools",
                "write-text",
                args["path"],
                args["text"],
            ],
        )
        bindings: dict[Channel, object] = {
            Channel.API: FileSystemExecutor(),
            Channel.MCP: sandbox_mcp_executor(),
            Channel.CLI: cli,
            Channel.CONTROL: ControlExecutor(),
        }
        if self.visible:
            bindings[Channel.GUI] = ExplorerUiaExecutor()
        return bindings

    def observe(self, history: Sequence[StepResult]) -> Observation:
        archived = {name: path.exists() for name, path in self.destinations.items()}
        manifest_text = self.manifest.read_text(encoding="utf-8") if self.manifest.exists() else None
        return Observation(
            task=(
                "Archive only the two final Q3 reports, exclude drafts and prior "
                "quarters, then write a manifest."
            ),
            subgoal=(
                "Confirm completion"
                if all(archived.values()) and manifest_text
                else "Choose the next eligible report or create the manifest"
            ),
            state={
                "inbox": {
                    path.name: path.read_text(encoding="utf-8") for path in sorted(self.inbox.iterdir())
                },
                "archived": archived,
                "manifest_path": str(self.manifest),
                "manifest_text": manifest_text,
            },
            source=self.name,
        )

    def candidates(
        self, observation: Observation, history: Sequence[StepResult]
    ) -> Sequence[ActionCandidate]:
        pending: list[ActionCandidate] = []
        for name, source in self.sources.items():
            if observation.state["archived"][name]:
                continue
            destination = self.destinations[name]
            args = {"source_path": str(source), "destination_path": str(destination)}
            expected = {"path": str(destination)}
            intent = f"archive_{name}_report"
            pending.extend(
                (
                    ActionCandidate(
                        f"mcp_copy_{name}",
                        Channel.MCP,
                        "mcp.filesystem.copy",
                        f"Archive the {name} report through MCP.",
                        args,
                        Risk.LOCAL_WRITE,
                        verifier="file.exists",
                        expected=expected,
                        intent=intent,
                    ),
                    ActionCandidate(
                        f"api_copy_{name}",
                        Channel.API,
                        "filesystem.copy",
                        f"Archive the {name} report through the filesystem API.",
                        args,
                        Risk.LOCAL_WRITE,
                        verifier="file.exists",
                        expected=expected,
                        intent=intent,
                    ),
                    ActionCandidate(
                        f"cli_copy_{name}",
                        Channel.CLI,
                        "cli.copy_file",
                        f"Archive the {name} report through an argv-only tool.",
                        args,
                        Risk.LOCAL_WRITE,
                        verifier="file.exists",
                        expected=expected,
                        intent=intent,
                    ),
                )
            )
            if self.visible:
                pending.append(
                    ActionCandidate(
                        f"gui_copy_{name}",
                        Channel.GUI,
                        "explorer.uia_copy",
                        f"Archive the {name} report visibly in Windows Explorer.",
                        args,
                        Risk.LOCAL_WRITE,
                        verifier="file.exists",
                        expected=expected,
                        intent=intent,
                    )
                )
        if pending:
            return tuple(pending)
        manifest_text = "sales-Q3.txt\ninventory-Q3.txt\n"
        if observation.state["manifest_text"] != manifest_text:
            args = {"path": str(self.manifest), "text": manifest_text}
            expected = {"path": str(self.manifest), "contains": "inventory-Q3.txt"}
            return (
                ActionCandidate(
                    "mcp_write_manifest",
                    Channel.MCP,
                    "mcp.filesystem.write_text",
                    "Write the archive manifest through MCP.",
                    args,
                    Risk.LOCAL_WRITE,
                    verifier="file.contains",
                    expected=expected,
                    intent="write_manifest",
                ),
                ActionCandidate(
                    "api_write_manifest",
                    Channel.API,
                    "filesystem.write_text",
                    "Write the archive manifest through the filesystem API.",
                    args,
                    Risk.LOCAL_WRITE,
                    verifier="file.contains",
                    expected=expected,
                    intent="write_manifest",
                ),
                ActionCandidate(
                    "cli_write_manifest",
                    Channel.CLI,
                    "cli.write_text",
                    "Write the archive manifest through an argv-only tool.",
                    args,
                    Risk.LOCAL_WRITE,
                    verifier="file.contains",
                    expected=expected,
                    intent="write_manifest",
                ),
            )
        return (
            ActionCandidate(
                "done",
                Channel.CONTROL,
                "control.done",
                "Declare completion after manifest and byte-level verification.",
                intent="finish",
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
            return Evaluation(False, False, "organization_step_completed; reobserve")
        valid = all(
            self.destinations[name].exists()
            and self.destinations[name].read_bytes() == self.sources[name].read_bytes()
            for name in self.sources
        )
        valid = valid and self.manifest.read_text(encoding="utf-8") == ("sales-Q3.txt\ninventory-Q3.txt\n")
        valid = (
            valid
            and not (self.archive / "draft-notes.txt").exists()
            and not (self.archive / "sales-Q2.txt").exists()
        )
        return Evaluation(valid, True, "archive_verified" if valid else "archive_content_mismatch")
