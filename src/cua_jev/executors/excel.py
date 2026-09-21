from __future__ import annotations

from typing import Any

from ..errors import CapabilityUnavailable
from ..models import ActionCandidate, ActionReceipt
from .common import execute_with_receipt


class ExcelComExecutor:
    """Typed Excel COM operations. No macro or arbitrary VBA execution."""

    def __init__(self, visible: bool = True) -> None:
        self.visible = visible

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict[str, Any]:
            try:
                import pythoncom
                import win32com.client
            except ImportError:
                raise CapabilityUnavailable("install cua-jev[windows] for Excel COM") from None
            args = candidate.arguments
            owned_instance = "workbook_path" in args
            if owned_instance:
                excel = win32com.client.DispatchEx("Excel.Application")
            else:
                try:
                    excel = win32com.client.GetActiveObject("Excel.Application")
                except pythoncom.com_error:
                    raise CapabilityUnavailable("no running Excel instance is available") from None
            workbook = None
            try:
                excel.Visible = self.visible
                excel.DisplayAlerts = False
                if "workbook_path" in args:
                    workbook = excel.Workbooks.Open(args["workbook_path"])
                elif excel.Workbooks.Count:
                    workbook = excel.ActiveWorkbook
                if candidate.capability == "excel.snapshot":
                    books = [excel.Workbooks.Item(i).Name for i in range(1, excel.Workbooks.Count + 1)]
                    return {
                        "workbooks": books,
                        "active": excel.ActiveWorkbook.Name if excel.ActiveWorkbook else None,
                    }
                if workbook is None:
                    raise RuntimeError("no Excel workbook is open")
                sheet = workbook.Worksheets(args.get("sheet", 1))
                if candidate.capability == "excel.read_range":
                    value = sheet.Range(args["range"]).Value
                    return {
                        "workbook": workbook.Name,
                        "sheet": sheet.Name,
                        "range": args["range"],
                        "value": value,
                    }
                if candidate.capability == "excel.write_range":
                    sheet.Range(args["range"]).Value = args["value"]
                    if args.get("save", True):
                        workbook.Save()
                    return {"workbook": workbook.Name, "sheet": sheet.Name, "range": args["range"]}
                if candidate.capability == "excel.create_chart":
                    chart = sheet.Shapes.AddChart2(201, int(args.get("chart_type", 4))).Chart
                    chart.SetSourceData(sheet.Range(args["range"]))
                    if args.get("title"):
                        chart.HasTitle = True
                        chart.ChartTitle.Text = args["title"]
                    workbook.Save()
                    return {"workbook": workbook.Name, "sheet": sheet.Name, "range": args["range"]}
                raise ValueError(f"unsupported Excel capability: {candidate.capability}")
            finally:
                if owned_instance:
                    if workbook is not None:
                        workbook.Close(SaveChanges=False)
                    excel.Quit()

        return execute_with_receipt(candidate, observation_id, decision_id, operation)
