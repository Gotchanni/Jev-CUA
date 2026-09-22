from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from typing import Any


def doctor() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "jev": {
            "configured": bool(os.getenv("TYPESAFE_API_KEY")),
            "model": os.getenv("CUA_JEV_MODEL", "jev-1.13.0"),
        },
        "capabilities": {
            "filesystem": True,
            "cli": True,
            "windows_uia": importlib.util.find_spec("pywinauto") is not None,
            "screen_gui": importlib.util.find_spec("pyautogui") is not None,
            "excel_com": importlib.util.find_spec("win32com") is not None,
            "edge_dom": importlib.util.find_spec("playwright") is not None,
            "vscode": bool(shutil.which("code") or shutil.which("code.cmd")),
            "powershell": bool(shutil.which("powershell") or shutil.which("pwsh")),
        },
    }
