"""Local Windows integration smoke tests; no external actions or credentials."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cua_jev.doctor import doctor
from cua_jev.executors.excel import ExcelComExecutor
from cua_jev.executors.uia import snapshot_windows
from cua_jev.models import ActionCandidate, Channel


def excel_smoke(root: Path) -> dict:
    import win32com.client

    path = root / "cua-jev-smoke.xlsx"
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        workbook = excel.Workbooks.Add()
        workbook.Worksheets(1).Range("A1:B2").Value = (("name", "value"), ("demo", 42))
        workbook.SaveAs(str(path))
        workbook.Close(SaveChanges=False)
    finally:
        excel.Quit()
    candidate = ActionCandidate(
        id="excel_read",
        channel=Channel.SCRIPT,
        capability="excel.read_range",
        description="Read the controlled smoke-test workbook",
        arguments={"workbook_path": str(path), "sheet": 1, "range": "A1:B2"},
    )
    receipt = ExcelComExecutor(visible=False)(candidate, "smoke-observation", "smoke-decision")
    return {"success": receipt.success, "output": receipt.output, "error": receipt.error}


def main() -> int:
    report = {"doctor": doctor()}
    report["uia"] = {"top_level_windows": len(snapshot_windows(20)["windows"])}
    with tempfile.TemporaryDirectory(prefix="cua-jev-") as directory:
        report["excel"] = excel_smoke(Path(directory))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["excel"]["success"] and report["uia"]["top_level_windows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
