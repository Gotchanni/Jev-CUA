from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .episode import Evaluation
from .executors import (
    ControlExecutor,
    ExplorerUiaExecutor,
    FileSystemExecutor,
    InProcessMcpExecutor,
    RegisteredCliExecutor,
    ScreenController,
)
from .executors.common import execute_with_receipt
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

    def __init__(
        self,
        workspace: str | Path,
        *,
        visible: bool = False,
        demo_mode: bool = False,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.inbox = self.workspace / "inbox"
        self.archive = self.workspace / "archive"
        self.visible = visible
        self.demo_mode = demo_mode
        self.screen = ScreenController()
        self._explorer_handle: int | None = None
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
        if self.demo_mode:
            # An empty manifest is part of the visible demo fixture. Opening a
            # known file avoids inheriting an unrelated tab from an existing
            # Windows 11 Notepad session.
            self.manifest.touch()
            try:
                from pywinauto import Desktop
            except ImportError:
                raise RuntimeError("pywinauto is required for Explorer demo mode") from None
            desktop = Desktop(backend="uia")
            before = {window.handle for window in desktop.windows(title_re=r".*inbox.*")}
            subprocess.Popen(
                ["explorer.exe", "/n,", str(self.inbox)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.time() + 15
            matches = []
            while time.time() < deadline:
                matches = [
                    window for window in desktop.windows(title_re=r".*inbox.*") if window.handle not in before
                ]
                if matches:
                    break
                time.sleep(0.25)
            if not matches:
                matches = desktop.windows(title_re=r".*inbox.*")
            if not matches:
                raise RuntimeError("Explorer window did not become available")
            self._explorer_handle = matches[-1].handle
            self.screen.focus_handle(self._explorer_handle)
            self.screen.hotkey("ctrl", "l")
            self.screen.paste_text(str(self.inbox))
            self.screen.press("enter")

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
            bindings[Channel.GUI] = self if self.demo_mode else ExplorerUiaExecutor()
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
            if self.demo_mode:
                return tuple(candidate for candidate in pending if candidate.channel == Channel.GUI)
            return tuple(pending)
        manifest_text = "sales-Q3.txt\ninventory-Q3.txt\n"
        if observation.state["manifest_text"] != manifest_text:
            args = {"path": str(self.manifest), "text": manifest_text}
            expected = {"path": str(self.manifest), "contains": "inventory-Q3.txt"}
            candidates = (
                ActionCandidate(
                    "gui_write_manifest",
                    Channel.GUI,
                    "notepad.screen_write_text",
                    "Create the archive manifest visibly in Notepad.",
                    args,
                    Risk.LOCAL_WRITE,
                    verifier="file.contains",
                    expected=expected,
                    intent="write_manifest",
                ),
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
            if self.demo_mode:
                return (candidates[0],)
            return candidates[1:]
        return (
            ActionCandidate(
                "done",
                Channel.CONTROL,
                "control.done",
                "Declare completion after manifest and byte-level verification.",
                intent="finish",
            ),
        )

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict:
            if candidate.capability == "explorer.uia_copy":
                source = Path(candidate.arguments["source_path"])
                destination = Path(candidate.arguments["destination_path"])
                window = self.screen.focus_handle(self._explorer_handle)
                self.screen.hotkey("ctrl", "l")
                self.screen.paste_text(str(source.parent))
                self.screen.press("enter")
                time.sleep(1)
                rectangle = window.rectangle()
                row = sorted(self.inbox.iterdir()).index(source)
                self.screen.click_point(
                    rectangle.left + rectangle.width() * 0.12,
                    rectangle.top + rectangle.height() * 0.128,
                )
                self.screen.press("home")
                for _ in range(row):
                    self.screen.press("down")
                self.screen.hotkey("ctrl", "c")
                self.screen.hotkey("ctrl", "l")
                # Keep the CF_HDROP payload placed on the clipboard by Ctrl+C.
                # paste_text() would replace it with plain text before Ctrl+V.
                self.screen.write(str(destination.parent), interval=0.002)
                self.screen.press("enter")
                time.sleep(1)
                self.screen.click_point(
                    rectangle.left + rectangle.width() * 0.5,
                    rectangle.top + rectangle.height() * 0.3,
                )
                self.screen.hotkey("ctrl", "v")
                deadline = time.time() + 10
                while time.time() < deadline and not destination.exists():
                    time.sleep(0.2)
                if not destination.exists():
                    raise RuntimeError("physical Explorer copy did not create the destination")
                return {"backend": "pyautogui", "window": window.window_text()}
            if candidate.capability == "notepad.screen_write_text":
                path = Path(candidate.arguments["path"])
                subprocess.Popen(
                    ["notepad.exe", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.screen.focus(rf".*{re.escape(path.name)}.*", maximize=False)
                self.screen.hotkey("ctrl", "a")
                self.screen.paste_text(candidate.arguments["text"])
                self.screen.hotkey("ctrl", "s")
                deadline = time.time() + 10
                while time.time() < deadline and not path.exists():
                    time.sleep(0.2)
                if not path.exists():
                    raise RuntimeError("physical Notepad save did not create the manifest")
                return {"backend": "pyautogui", "path": str(path)}
            raise ValueError(f"unsupported screen capability: {candidate.capability}")

        return execute_with_receipt(candidate, observation_id, decision_id, operation)

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
