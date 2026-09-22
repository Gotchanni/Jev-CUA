from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from ..errors import CapabilityUnavailable
from ..models import ActionCandidate, ActionReceipt
from .common import execute_with_receipt


class VSCodeExecutor:
    """Narrow adapter around the official `code` CLI."""

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict:
            executable = shutil.which("code") or shutil.which("code.cmd")
            if not executable:
                raise CapabilityUnavailable("VS Code 'code' CLI is not on PATH")
            if candidate.capability == "vscode.open":
                target = str(Path(candidate.arguments["path"]).resolve())
                argv = [executable, "--reuse-window", target]
            elif candidate.capability == "vscode.goto":
                target = str(Path(candidate.arguments["path"]).resolve())
                line = int(candidate.arguments.get("line", 1))
                column = int(candidate.arguments.get("column", 1))
                argv = [executable, "--reuse-window", "--goto", f"{target}:{line}:{column}"]
            elif candidate.capability == "vscode.uia_replace_line":
                try:
                    from pywinauto import Desktop
                    from pywinauto.keyboard import send_keys
                except ImportError:
                    raise CapabilityUnavailable(
                        "install cua-jev[windows] for VS Code UI Automation"
                    ) from None
                target = str(Path(candidate.arguments["path"]).resolve())
                line = int(candidate.arguments["line"])
                argv = [executable, "--reuse-window", "--goto", f"{target}:{line}:1"]
                completed = subprocess.run(
                    argv, capture_output=True, text=True, timeout=15, shell=False, check=False
                )
                if completed.returncode:
                    raise RuntimeError(completed.stderr[-1000:])
                window = Desktop(backend="uia").window(title_re=r".*Visual Studio Code.*|.*calc\.py.*")
                window.wait("exists enabled visible ready", timeout=15)
                window.set_focus()
                time.sleep(1)
                text = str(candidate.arguments["text"]).replace("+", "{+}")
                send_keys("{HOME}+{END}")
                send_keys(text, with_spaces=True, pause=0.01)
                send_keys("^s")
                time.sleep(0.5)
                return {"argv": argv, "window": window.window_text(), "line": line}
            else:
                raise ValueError(f"unsupported VS Code capability: {candidate.capability}")
            completed = subprocess.run(
                argv, capture_output=True, text=True, timeout=15, shell=False, check=False
            )
            if completed.returncode:
                raise RuntimeError(completed.stderr[-1000:])
            return {"argv": argv, "stdout": completed.stdout[-2000:]}

        return execute_with_receipt(candidate, observation_id, decision_id, operation)
