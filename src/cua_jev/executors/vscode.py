from __future__ import annotations

import shutil
import subprocess
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
            else:
                raise ValueError(f"unsupported VS Code capability: {candidate.capability}")
            completed = subprocess.run(
                argv, capture_output=True, text=True, timeout=15, shell=False, check=False
            )
            if completed.returncode:
                raise RuntimeError(completed.stderr[-1000:])
            return {"argv": argv, "stdout": completed.stdout[-2000:]}

        return execute_with_receipt(candidate, observation_id, decision_id, operation)
