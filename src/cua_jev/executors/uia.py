from __future__ import annotations

from typing import Any

from ..errors import CapabilityUnavailable
from ..models import ActionCandidate, ActionReceipt
from .common import execute_with_receipt


def snapshot_windows(limit: int = 50) -> dict[str, Any]:
    try:
        from pywinauto import Desktop
    except ImportError:
        raise CapabilityUnavailable("install cua-jev[windows] for Windows UI Automation") from None
    windows = []
    for window in Desktop(backend="uia").windows()[:limit]:
        rectangle = window.rectangle()
        windows.append(
            {
                "title": window.window_text(),
                "control_type": window.element_info.control_type,
                "automation_id": window.element_info.automation_id,
                "bounds": [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom],
            }
        )
    return {"windows": windows}


class WindowsUiaExecutor:
    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict[str, Any]:
            try:
                from pywinauto import Desktop
                from pywinauto.keyboard import send_keys
            except ImportError:
                raise CapabilityUnavailable("install cua-jev[windows] for Windows UI Automation") from None
            if candidate.capability == "uia.snapshot_windows":
                return snapshot_windows(int(candidate.arguments.get("limit", 50)))
            title = candidate.arguments.get("window_title_re", ".*")
            window = Desktop(backend="uia").window(title_re=title)
            window.wait(
                "exists enabled visible ready", timeout=float(candidate.arguments.get("timeout_s", 10))
            )
            if candidate.capability == "uia.invoke":
                control = window.child_window(
                    title=candidate.arguments.get("title"),
                    auto_id=candidate.arguments.get("automation_id"),
                    control_type=candidate.arguments.get("control_type"),
                )
                control.wait("exists enabled visible ready", timeout=10).invoke()
                return {"window": window.window_text(), "invoked": control.window_text()}
            if candidate.capability == "uia.set_text":
                control = window.child_window(
                    title=candidate.arguments.get("title"),
                    auto_id=candidate.arguments.get("automation_id"),
                    control_type=candidate.arguments.get("control_type"),
                )
                control.wait("exists enabled visible ready", timeout=10).set_edit_text(
                    candidate.arguments["text"]
                )
                return {"window": window.window_text(), "updated": control.window_text()}
            if candidate.capability == "uia.hotkey":
                window.set_focus()
                send_keys(candidate.arguments["keys"])
                return {"window": window.window_text(), "keys": candidate.arguments["keys"]}
            raise ValueError(f"unsupported UIA capability: {candidate.capability}")

        return execute_with_receipt(candidate, observation_id, decision_id, operation)
