from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from ..errors import CapabilityUnavailable
from ..models import ActionCandidate, ActionReceipt
from .common import execute_with_receipt


class ExplorerUiaExecutor:
    """Visible, tightly scoped Explorer copy operation for demo workspaces."""

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict:
            try:
                from pywinauto import Desktop
                from pywinauto.keyboard import send_keys
            except ImportError:
                raise CapabilityUnavailable("install cua-jev[windows] for Explorer UI Automation") from None
            if candidate.capability != "explorer.uia_copy":
                raise ValueError(f"unsupported Explorer capability: {candidate.capability}")
            source = Path(candidate.arguments["source_path"]).resolve()
            destination = Path(candidate.arguments["destination_path"]).resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(
                ["explorer.exe", str(source.parent)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            desktop = Desktop(backend="uia")
            deadline = time.time() + 15
            windows = []
            while time.time() < deadline and not windows:
                windows = desktop.windows(title_re=rf".*{re.escape(source.parent.name)}.*")
                if not windows:
                    time.sleep(0.2)
            if not windows:
                raise RuntimeError("Explorer window did not become available")
            # Explorer titles are only the leaf folder name on Windows 11, so two
            # unrelated demo workspaces can legitimately have an ``inbox`` window.
            # Pick the most recently enumerated match and navigate it explicitly.
            window = desktop.window(handle=windows[-1].handle)
            window.wait("exists enabled visible ready", timeout=15)
            window.set_focus()
            send_keys("^l")
            send_keys(str(source.parent), with_spaces=True, pause=0.01)
            send_keys("{ENTER}")
            time.sleep(1)
            # Explorer may hide known file extensions in the visible item name.
            visible_names = {re.escape(source.name), re.escape(source.stem)}
            item = window.child_window(
                title_re=rf"^(?:{'|'.join(sorted(visible_names))})$",
                control_type="ListItem",
            )
            item.wait("exists enabled visible ready", timeout=10).click_input()
            send_keys("^c")
            send_keys("^l")
            send_keys(str(destination.parent), with_spaces=True, pause=0.01)
            send_keys("{ENTER}")
            time.sleep(1)
            send_keys("^v")
            deadline = time.time() + 10
            while time.time() < deadline and not destination.exists():
                time.sleep(0.2)
            if not destination.exists():
                raise RuntimeError("Explorer copy did not create the destination")
            return {
                "window": window.window_text(),
                "source": str(source),
                "destination": str(destination),
            }

        return execute_with_receipt(candidate, observation_id, decision_id, operation)
