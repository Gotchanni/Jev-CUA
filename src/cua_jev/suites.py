from __future__ import annotations

import gc
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .episode import Evaluation
from .errors import CapabilityUnavailable
from .executors import (
    ControlExecutor,
    ExcelComExecutor,
    FileSystemExecutor,
    OpenPyxlExecutor,
    RegisteredCliExecutor,
    VSCodeExecutor,
)
from .executors.common import execute_with_receipt
from .models import ActionCandidate, ActionReceipt, Channel, Observation, Risk, Verification
from .runtime import StepResult
from .sandbox import FileOrganizationTask, sandbox_mcp_executor


class EdgeProductTask:
    """Filter a local product page and download a CSV through a real Edge DOM session."""

    name = "edge-product-filter"

    def __init__(self, workspace: str | Path, *, headless: bool = True) -> None:
        self.workspace = Path(workspace).resolve()
        self.download = self.workspace / "products.csv"
        self.headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.workspace,)

    def executor_bindings(self) -> dict[Channel, object]:
        return {
            Channel.GUI: self,
            Channel.SCRIPT: self,
            Channel.API: self,
            Channel.CONTROL: ControlExecutor(),
        }

    def reset(self) -> None:
        self.close()
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.download.exists():
            self.download.unlink()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise CapabilityUnavailable("install cua-jev[browser] to run the Edge suite") from None
        fixture = Path(__file__).with_name("fixtures") / "product_filter.html"
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(channel="msedge", headless=self.headless)
        except Exception:
            self.close()
            raise
        context = self._browser.new_context(accept_downloads=True)
        self._page = context.new_page()
        self._page.goto(fixture.as_uri(), wait_until="domcontentloaded")

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = self._browser = self._playwright = None

    def observe(self, history: Sequence[StepResult]) -> Observation:
        if self._page is None:
            raise RuntimeError("Edge task has not been reset")
        return Observation(
            task="Filter products to laptop and export the resulting CSV.",
            subgoal="Verify completion" if self.download.exists() else "Advance the browser workflow",
            state={
                "url": self._page.url,
                "query": self._page.locator("#query").input_value(),
                "status": self._page.locator("#status").get_attribute("data-state"),
                "download_visible": self._page.locator("#download").is_visible(),
                "download_path": str(self.download),
                "download_exists": self.download.exists(),
            },
            source=self.name,
        )

    def candidates(
        self, observation: Observation, history: Sequence[StepResult]
    ) -> Sequence[ActionCandidate]:
        state = observation.state
        if state["query"] != "laptop":
            return (
                ActionCandidate(
                    "gui_fill_category",
                    Channel.GUI,
                    "edge.fill",
                    "Fill the category input through Playwright's user-facing input action.",
                    {"selector": "#query", "text": "laptop"},
                    Risk.LOCAL_WRITE,
                ),
                ActionCandidate(
                    "script_fill_category",
                    Channel.SCRIPT,
                    "edge.dom_set_value",
                    "Set the DOM value and dispatch an input event without pointer interaction.",
                    {"selector": "#query", "text": "laptop"},
                    Risk.LOCAL_WRITE,
                ),
            )
        if state["status"] != "complete":
            return (
                ActionCandidate(
                    "gui_apply_filter",
                    Channel.GUI,
                    "edge.click",
                    "Click Filter through the visible Playwright pointer action.",
                    {"selector": "#filter"},
                    Risk.LOCAL_WRITE,
                ),
                ActionCandidate(
                    "script_apply_filter",
                    Channel.SCRIPT,
                    "edge.dom_dispatch_click",
                    "Dispatch the filter button click directly through the DOM.",
                    {"selector": "#filter"},
                    Risk.LOCAL_WRITE,
                ),
            )
        if not state["download_exists"]:
            return (
                ActionCandidate(
                    "gui_download_csv",
                    Channel.GUI,
                    "edge.download",
                    "Click the visible download link and save the browser download.",
                    {"selector": "#download", "destination_path": str(self.download)},
                    Risk.LOCAL_WRITE,
                    verifier="file.contains",
                    expected={"path": str(self.download), "contains": "ThinkPad,laptop,999"},
                ),
                ActionCandidate(
                    "api_download_csv",
                    Channel.API,
                    "edge.extract_download",
                    "Read the generated download resource through the page API and save it directly.",
                    {"selector": "#download", "destination_path": str(self.download)},
                    Risk.LOCAL_WRITE,
                    verifier="file.contains",
                    expected={"path": str(self.download), "contains": "ThinkPad,laptop,999"},
                ),
            )
        return (
            ActionCandidate(
                "done", Channel.CONTROL, "control.done", "Declare completion after export verification."
            ),
        )

    def __call__(
        self, candidate: ActionCandidate, observation_id: str, decision_id: str
    ) -> ActionReceipt:
        def operation() -> dict[str, Any]:
            if self._page is None:
                raise RuntimeError("Edge page is unavailable")
            selector = candidate.arguments.get("selector")
            if candidate.capability == "edge.fill":
                self._page.locator(selector).fill(candidate.arguments["text"])
            elif candidate.capability == "edge.dom_set_value":
                self._page.locator(selector).evaluate(
                    "(element, value) => { element.value = value; "
                    "element.dispatchEvent(new Event('input', {bubbles: true})); }",
                    candidate.arguments["text"],
                )
            elif candidate.capability == "edge.click":
                self._page.locator(selector).click()
            elif candidate.capability == "edge.dom_dispatch_click":
                self._page.locator(selector).dispatch_event("click")
            elif candidate.capability == "edge.download":
                with self._page.expect_download() as pending:
                    self._page.locator(selector).click()
                pending.value.save_as(candidate.arguments["destination_path"])
            elif candidate.capability == "edge.extract_download":
                payload = self._page.locator(selector).evaluate(
                    """async element => {
                      const bytes = new Uint8Array(await (await fetch(element.href)).arrayBuffer());
                      return Array.from(bytes);
                    }"""
                )
                Path(candidate.arguments["destination_path"]).write_bytes(bytes(payload))
            else:
                raise ValueError(f"unsupported task capability: {candidate.capability}")
            return {"selector": selector, "url": self._page.url}

        return execute_with_receipt(candidate, observation_id, decision_id, operation)

    def evaluate(
        self,
        observation: Observation,
        candidate: ActionCandidate,
        receipt: ActionReceipt,
        verification: Verification,
    ) -> Evaluation:
        if not receipt.success or not verification.passed:
            return Evaluation(False, False, "browser_action_not_verified")
        if candidate.capability != "control.done":
            return Evaluation(False, False, "browser_step_completed; reobserve")
        valid = self.download.is_file() and "ThinkPad,laptop,999" in self.download.read_text("utf-8")
        return Evaluation(valid, True, "edge_export_verified" if valid else "edge_export_invalid")


class ExcelSalesTask:
    """Create a formula and chart in a real workbook, then inspect it through a fresh COM process."""

    name = "excel-sales-summary"

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.workbook = self.workspace / "sales.xlsx"

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.workspace,)

    def executor_bindings(self) -> dict[Channel, object]:
        return {
            Channel.SCRIPT: ExcelComExecutor(visible=False),
            Channel.API: OpenPyxlExecutor(),
            Channel.CONTROL: ControlExecutor(),
        }

    @staticmethod
    def _excel_modules():
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            raise CapabilityUnavailable("install cua-jev[windows] to run the Excel suite") from None
        return pythoncom, win32com.client

    def reset(self) -> None:
        pythoncom, win32 = self._excel_modules()
        pythoncom.CoInitialize()
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.workbook.exists():
            self.workbook.unlink()
        excel = win32.DispatchEx("Excel.Application")
        book = None
        data = None
        summary = None
        try:
            excel.Visible = False
            excel.DisplayAlerts = False
            book = excel.Workbooks.Add()
            data = book.Worksheets(1)
            data.Name = "Data"
            summary = book.Worksheets.Add(After=data)
            summary.Name = "Summary"
            data.Range("A1:B4").Value = (
                ("Product", "Revenue"),
                ("Laptop", 120),
                ("Monitor", 80),
                ("Keyboard", 100),
            )
            summary.Range("A1:B2").Value = (("Metric", "Value"), ("Total revenue", None))
            book.SaveAs(str(self.workbook), 51)
        finally:
            del data, summary
            gc.collect()
            if book is not None:
                book.Close(SaveChanges=False)
            del book
            excel.Quit()
            del excel
            gc.collect()
            pythoncom.CoUninitialize()

    def observe(self, history: Sequence[StepResult]) -> Observation:
        pythoncom, win32 = self._excel_modules()
        pythoncom.CoInitialize()
        excel = win32.DispatchEx("Excel.Application")
        book = None
        summary = None
        try:
            excel.Visible = False
            excel.DisplayAlerts = False
            book = excel.Workbooks.Open(str(self.workbook))
            summary = book.Worksheets("Summary")
            value = summary.Range("B2").Value
            formula = summary.Range("B2").Formula
            charts = sum(book.Worksheets(i).ChartObjects().Count for i in range(1, book.Worksheets.Count + 1))
        finally:
            del summary
            gc.collect()
            if book is not None:
                book.Close(SaveChanges=False)
            del book
            excel.Quit()
            del excel
            gc.collect()
            pythoncom.CoUninitialize()
        return Observation(
            task="Calculate total sales revenue and create a product revenue chart.",
            subgoal="Verify workbook" if value == 300 and charts else "Complete the workbook",
            state={
                "workbook_path": str(self.workbook),
                "summary_value": value,
                "summary_formula": formula,
                "chart_count": charts,
            },
            source=self.name,
        )

    def candidates(
        self, observation: Observation, history: Sequence[StepResult]
    ) -> Sequence[ActionCandidate]:
        state = observation.state
        if state["summary_value"] != 300:
            return (
                ActionCandidate(
                    "com_write_summary_formula",
                    Channel.SCRIPT,
                    "excel.write_range",
                    "Write the SUM formula through a live Excel COM process.",
                    {
                        "workbook_path": str(self.workbook),
                        "sheet": "Summary",
                        "range": "B2",
                        "formula": "=SUM(Data!B2:B4)",
                    },
                    Risk.LOCAL_WRITE,
                ),
                ActionCandidate(
                    "file_write_summary_formula",
                    Channel.API,
                    "excel.file_write_formula",
                    "Write the SUM formula directly into the workbook file through openpyxl.",
                    {
                        "workbook_path": str(self.workbook),
                        "sheet": "Summary",
                        "cell": "B2",
                        "formula": "=SUM(Data!B2:B4)",
                    },
                    Risk.LOCAL_WRITE,
                ),
            )
        if state["chart_count"] < 1:
            return (
                ActionCandidate(
                    "com_create_revenue_chart",
                    Channel.SCRIPT,
                    "excel.create_chart",
                    "Create the chart through a live Excel COM process.",
                    {
                        "workbook_path": str(self.workbook),
                        "sheet": "Data",
                        "range": "A1:B4",
                        "title": "Revenue by product",
                    },
                    Risk.LOCAL_WRITE,
                ),
                ActionCandidate(
                    "file_create_revenue_chart",
                    Channel.API,
                    "excel.file_create_chart",
                    "Create the chart directly in the workbook file through openpyxl.",
                    {
                        "workbook_path": str(self.workbook),
                        "sheet": "Data",
                        "max_row": 4,
                        "title": "Revenue by product",
                        "x_axis_title": "Product",
                        "y_axis_title": "Revenue",
                        "anchor": "D2",
                    },
                    Risk.LOCAL_WRITE,
                ),
            )
        return (
            ActionCandidate(
                "done", Channel.CONTROL, "control.done", "Declare completion after workbook inspection."
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
            return Evaluation(False, False, "excel_action_not_verified")
        if candidate.capability != "control.done":
            return Evaluation(False, False, "excel_step_completed; reobserve")
        state = self.observe(())
        formula = str(state.state["summary_formula"]).upper()
        valid = state.state["summary_value"] == 300 and "SUM(" in formula and state.state["chart_count"] >= 1
        return Evaluation(valid, True, "excel_workbook_verified" if valid else "excel_workbook_invalid")


class VSCodeTerminalTask:
    """Open a tiny project, repair a failing function, and verify it with a real test process."""

    name = "vscode-terminal-repair"
    corrected_source = "def add(left, right):\n    return left + right\n"

    def __init__(self, workspace: str | Path, *, open_vscode: bool = False) -> None:
        self.workspace = Path(workspace).resolve()
        self.source = self.workspace / "calc.py"
        self.test_file = self.workspace / "test_calc.py"
        self.open_vscode = open_vscode
        self.opened = False

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.workspace,)

    def executor_bindings(self) -> dict[Channel, object]:
        cli = RegisteredCliExecutor()
        cli.register(
            "cli.replace_exact",
            lambda args: [
                sys.executable,
                "-m",
                "cua_jev.tools",
                "replace-exact",
                args["path"],
                args["old"],
                args["new"],
            ],
        )
        bindings: dict[Channel, object] = {
            Channel.API: FileSystemExecutor(),
            Channel.MCP: sandbox_mcp_executor(),
            Channel.CLI: cli,
            Channel.CONTROL: ControlExecutor(),
        }
        if self.open_vscode:
            bindings[Channel.GUI] = VSCodeExecutor()
        return bindings

    def reset(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.source.write_text("def add(left, right):\n    return left - right\n", encoding="utf-8")
        self.test_file.write_text(
            "import unittest\n\nfrom calc import add\n\n\n"
            "class CalcTest(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        self.opened = not self.open_vscode

    def _test(self) -> subprocess.CompletedProcess[str]:
        cache = self.workspace / "__pycache__"
        if cache.exists():
            shutil.rmtree(cache)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(self.workspace), "-q"],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            check=False,
        )

    def observe(self, history: Sequence[StepResult]) -> Observation:
        test = self._test()
        return Observation(
            task="Repair the calculator project until its test suite passes.",
            subgoal="Verify completion" if test.returncode == 0 else "Diagnose and repair the failing test",
            state={
                "workspace": str(self.workspace),
                "source_path": str(self.source),
                "source": self.source.read_text(encoding="utf-8"),
                "vscode_opened": self.opened,
                "test_returncode": test.returncode,
                "test_stdout": test.stdout[-2000:],
                "test_stderr": test.stderr[-2000:],
            },
            source=self.name,
        )

    def candidates(
        self, observation: Observation, history: Sequence[StepResult]
    ) -> Sequence[ActionCandidate]:
        if not observation.state["vscode_opened"]:
            return (
                ActionCandidate(
                    "open_project",
                    Channel.GUI,
                    "vscode.open",
                    "Open the failing project in VS Code.",
                    {"path": str(self.workspace)},
                ),
            )
        if observation.state["test_returncode"]:
            common = {
                "path": str(self.source),
                "text": self.corrected_source,
            }
            return (
                ActionCandidate(
                    "mcp_repair",
                    Channel.MCP,
                    "mcp.filesystem.write_text",
                    "Repair calc.py through the filesystem MCP tool.",
                    common,
                    Risk.LOCAL_WRITE,
                    verifier="file.contains",
                    expected={"path": str(self.source), "contains": "return left + right"},
                ),
                ActionCandidate(
                    "api_repair",
                    Channel.API,
                    "filesystem.write_text",
                    "Repair calc.py through the typed filesystem API.",
                    common,
                    Risk.LOCAL_WRITE,
                    verifier="file.contains",
                    expected={"path": str(self.source), "contains": "return left + right"},
                ),
                ActionCandidate(
                    "cli_repair",
                    Channel.CLI,
                    "cli.replace_exact",
                    "Repair only the faulty expression through an allowlisted CLI patch command.",
                    {
                        "path": str(self.source),
                        "old": "return left - right",
                        "new": "return left + right",
                    },
                    Risk.LOCAL_WRITE,
                    verifier="file.contains",
                    expected={"path": str(self.source), "contains": "return left + right"},
                ),
            )
        return (
            ActionCandidate(
                "done", Channel.CONTROL, "control.done", "Declare completion after tests pass."
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
            return Evaluation(False, False, "development_action_not_verified")
        if candidate.capability == "vscode.open":
            self.opened = True
            return Evaluation(False, False, "project_opened; reobserve")
        if candidate.capability != "control.done":
            return Evaluation(False, False, "repair_written; rerun_tests")
        passed = self._test().returncode == 0 and self.source.read_text("utf-8") == self.corrected_source
        return Evaluation(passed, True, "test_suite_verified" if passed else "test_suite_failed")


SUITE_NAMES = ("edge", "excel", "vscode", "explorer")


def make_suite(
    name: str, workspace: str | Path, *, headed_edge: bool = False, open_vscode: bool = False
):
    root = Path(workspace).resolve() / name
    if name == "edge":
        return EdgeProductTask(root, headless=not headed_edge)
    if name == "excel":
        return ExcelSalesTask(root)
    if name == "vscode":
        return VSCodeTerminalTask(root, open_vscode=open_vscode)
    if name == "explorer":
        return FileOrganizationTask(root)
    raise ValueError(f"unknown suite: {name}")
