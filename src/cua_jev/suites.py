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
            task="Find in-stock laptops under 1200, review the result set, and export a verified CSV.",
            subgoal="Verify completion" if self.download.exists() else "Advance the browser workflow",
            state={
                "url": self._page.url,
                "query": self._page.locator("#query").input_value(),
                "max_price": self._page.locator("#max-price").input_value(),
                "in_stock": self._page.locator("#in-stock").is_checked(),
                "status": self._page.locator("#status").get_attribute("data-state"),
                "result_count": self._page.locator("#results tbody tr").count()
                if self._page.locator("#results").is_visible()
                else 0,
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
        pending: list[ActionCandidate] = []
        if state["query"] != "laptop":
            pending.extend(
                (
                    ActionCandidate(
                        "gui_fill_category",
                        Channel.GUI,
                        "edge.fill",
                        "Fill the category input through Playwright's user-facing input action.",
                        {"selector": "#query", "text": "laptop"},
                        Risk.LOCAL_WRITE,
                        intent="set_category",
                    ),
                    ActionCandidate(
                        "script_fill_category",
                        Channel.SCRIPT,
                        "edge.dom_set_value",
                        "Set the DOM value and dispatch an input event without pointer interaction.",
                        {"selector": "#query", "text": "laptop"},
                        Risk.LOCAL_WRITE,
                        intent="set_category",
                    ),
                )
            )
        if state["max_price"] != "1200":
            pending.extend(
                (
                    ActionCandidate(
                        "gui_fill_max_price",
                        Channel.GUI,
                        "edge.fill",
                        "Enter the maximum price through the visible input.",
                        {"selector": "#max-price", "text": "1200"},
                        Risk.LOCAL_WRITE,
                        intent="set_budget",
                    ),
                    ActionCandidate(
                        "script_fill_max_price",
                        Channel.SCRIPT,
                        "edge.dom_set_value",
                        "Set the maximum price and dispatch an input event.",
                        {"selector": "#max-price", "text": "1200"},
                        Risk.LOCAL_WRITE,
                        intent="set_budget",
                    ),
                )
            )
        if not state["in_stock"]:
            pending.extend(
                (
                    ActionCandidate(
                        "gui_enable_in_stock",
                        Channel.GUI,
                        "edge.check",
                        "Enable the in-stock filter through the visible checkbox.",
                        {"selector": "#in-stock"},
                        Risk.LOCAL_WRITE,
                        intent="require_availability",
                    ),
                    ActionCandidate(
                        "script_enable_in_stock",
                        Channel.SCRIPT,
                        "edge.dom_set_checked",
                        "Set the availability checkbox and dispatch a change event.",
                        {"selector": "#in-stock", "checked": True},
                        Risk.LOCAL_WRITE,
                        intent="require_availability",
                    ),
                )
            )
        if pending:
            return tuple(pending)
        if state["status"] not in {"review", "complete"}:
            return (
                ActionCandidate(
                    "gui_apply_filter",
                    Channel.GUI,
                    "edge.click",
                    "Click Filter through the visible Playwright pointer action.",
                    {"selector": "#filter"},
                    Risk.LOCAL_WRITE,
                    intent="search_catalog",
                ),
                ActionCandidate(
                    "script_apply_filter",
                    Channel.SCRIPT,
                    "edge.dom_dispatch_click",
                    "Dispatch the filter button click directly through the DOM.",
                    {"selector": "#filter"},
                    Risk.LOCAL_WRITE,
                    intent="search_catalog",
                ),
            )
        if state["status"] == "review":
            return (
                ActionCandidate(
                    "gui_confirm_results",
                    Channel.GUI,
                    "edge.click",
                    "Confirm the two visible matching products.",
                    {"selector": "#confirm"},
                    Risk.LOCAL_WRITE,
                    intent="review_results",
                ),
                ActionCandidate(
                    "script_confirm_results",
                    Channel.SCRIPT,
                    "edge.dom_dispatch_click",
                    "Confirm the reviewed result set through a DOM event.",
                    {"selector": "#confirm"},
                    Risk.LOCAL_WRITE,
                    intent="review_results",
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
                    intent="export_results",
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
                    intent="export_results",
                ),
            )
        return (
            ActionCandidate(
                "done",
                Channel.CONTROL,
                "control.done",
                "Declare completion after export verification.",
                intent="finish",
            ),
        )

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
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
            elif candidate.capability == "edge.check":
                self._page.locator(selector).check()
            elif candidate.capability == "edge.dom_set_checked":
                self._page.locator(selector).evaluate(
                    "(element, checked) => { element.checked = checked; "
                    "element.dispatchEvent(new Event('change', {bubbles: true})); }",
                    bool(candidate.arguments["checked"]),
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
        payload = self.download.read_text("utf-8") if self.download.is_file() else ""
        valid = "ThinkPad,laptop,999,true" in payload and "Surface,laptop,1099,true" in payload
        return Evaluation(valid, True, "edge_export_verified" if valid else "edge_export_invalid")


class ExcelSalesTask:
    """Create a formula and chart in a real workbook, then inspect it through a fresh COM process."""

    name = "excel-sales-summary"

    def __init__(self, workspace: str | Path, *, visible: bool = False) -> None:
        self.workspace = Path(workspace).resolve()
        self.workbook = self.workspace / "sales.xlsx"
        self.visible = visible

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.workspace,)

    def executor_bindings(self) -> dict[Channel, object]:
        bindings = {
            Channel.SCRIPT: ExcelComExecutor(visible=False),
            Channel.API: OpenPyxlExecutor(),
            Channel.CONTROL: ControlExecutor(),
        }
        if self.visible:
            bindings[Channel.GUI] = ExcelComExecutor(visible=True)
        return bindings

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
            summary.Range("A1:B4").Value = (
                ("Metric", "Value"),
                ("Total revenue", None),
                ("Average revenue", None),
                ("Review status", None),
            )
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
            average = summary.Range("B3").Value
            average_formula = summary.Range("B3").Formula
            review_status = summary.Range("B4").Value
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
            subgoal="Verify workbook"
            if value == 300 and average == 100 and charts and review_status == "Reviewed"
            else "Choose the next incomplete workbook operation",
            state={
                "workbook_path": str(self.workbook),
                "summary_value": value,
                "summary_formula": formula,
                "average_value": average,
                "average_formula": average_formula,
                "review_status": review_status,
                "chart_count": charts,
            },
            source=self.name,
        )

    def candidates(
        self, observation: Observation, history: Sequence[StepResult]
    ) -> Sequence[ActionCandidate]:
        state = observation.state
        pending: list[ActionCandidate] = []

        def add_cell_routes(intent: str, suffix: str, cell: str, *, formula=None, value=None) -> None:
            com_args = {"workbook_path": str(self.workbook), "sheet": "Summary", "range": cell}
            file_args = {"workbook_path": str(self.workbook), "sheet": "Summary", "cell": cell}
            if formula is not None:
                com_args["formula"] = formula
                file_args["formula"] = formula
                file_capability = "excel.file_write_formula"
            else:
                com_args["value"] = value
                file_args["value"] = value
                file_capability = "excel.file_write_value"
            if self.visible:
                pending.append(
                    ActionCandidate(
                        f"gui_{suffix}",
                        Channel.GUI,
                        "excel.write_range",
                        f"Complete {intent} in a visible Excel window.",
                        com_args,
                        Risk.LOCAL_WRITE,
                        intent=intent,
                    )
                )
            pending.extend(
                (
                    ActionCandidate(
                        f"com_{suffix}",
                        Channel.SCRIPT,
                        "excel.write_range",
                        f"Complete {intent} through background Excel COM.",
                        com_args,
                        Risk.LOCAL_WRITE,
                        intent=intent,
                    ),
                    ActionCandidate(
                        f"file_{suffix}",
                        Channel.API,
                        file_capability,
                        f"Complete {intent} through the workbook file API.",
                        file_args,
                        Risk.LOCAL_WRITE,
                        intent=intent,
                    ),
                )
            )

        if state["summary_value"] != 300:
            add_cell_routes("calculate_total", "write_total_formula", "B2", formula="=SUM(Data!B2:B4)")
        if state["average_value"] != 100:
            add_cell_routes(
                "calculate_average", "write_average_formula", "B3", formula="=AVERAGE(Data!B2:B4)"
            )
        if state["review_status"] != "Reviewed":
            add_cell_routes("mark_reviewed", "mark_reviewed", "B4", value="Reviewed")
        if state["chart_count"] < 1:
            com_args = {
                "workbook_path": str(self.workbook),
                "sheet": "Data",
                "range": "A1:B4",
                "title": "Revenue by product",
            }
            file_args = {
                "workbook_path": str(self.workbook),
                "sheet": "Data",
                "max_row": 4,
                "title": "Revenue by product",
                "x_axis_title": "Product",
                "y_axis_title": "Revenue",
                "anchor": "D2",
            }
            if self.visible:
                pending.append(
                    ActionCandidate(
                        "gui_create_revenue_chart",
                        Channel.GUI,
                        "excel.create_chart",
                        "Create the chart in a visible Excel window.",
                        com_args,
                        Risk.LOCAL_WRITE,
                        intent="visualize_revenue",
                    )
                )
            pending.extend(
                (
                    ActionCandidate(
                        "com_create_revenue_chart",
                        Channel.SCRIPT,
                        "excel.create_chart",
                        "Create the chart through background Excel COM.",
                        com_args,
                        Risk.LOCAL_WRITE,
                        intent="visualize_revenue",
                    ),
                    ActionCandidate(
                        "file_create_revenue_chart",
                        Channel.API,
                        "excel.file_create_chart",
                        "Create the chart through the workbook file API.",
                        file_args,
                        Risk.LOCAL_WRITE,
                        intent="visualize_revenue",
                    ),
                )
            )
        if pending:
            return tuple(pending)
        return (
            ActionCandidate(
                "done",
                Channel.CONTROL,
                "control.done",
                "Declare completion after workbook inspection.",
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
            return Evaluation(False, False, "excel_action_not_verified")
        if candidate.capability != "control.done":
            return Evaluation(False, False, "excel_step_completed; reobserve")
        state = self.observe(())
        formula = str(state.state["summary_formula"]).upper()
        valid = (
            state.state["summary_value"] == 300
            and "SUM(" in formula
            and state.state["average_value"] == 100
            and "AVERAGE(" in str(state.state["average_formula"]).upper()
            and state.state["review_status"] == "Reviewed"
            and state.state["chart_count"] >= 1
        )
        return Evaluation(valid, True, "excel_workbook_verified" if valid else "excel_workbook_invalid")


class VSCodeTerminalTask:
    """Diagnose and repair two independent defects, rerunning tests after each mutation."""

    name = "vscode-terminal-repair"
    corrected_source = (
        "def add(left, right):\n    return left + right\n\n\n"
        "def multiply(left, right):\n    return left * right\n"
    )

    def __init__(self, workspace: str | Path, *, open_vscode: bool = False) -> None:
        self.workspace = Path(workspace).resolve()
        self.source = self.workspace / "calc.py"
        self.test_file = self.workspace / "test_calc.py"
        self.open_vscode = open_vscode
        self.opened = False
        self.last_test: dict[str, Any] | None = None

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
            Channel.SCRIPT: self,
            Channel.CONTROL: ControlExecutor(),
        }
        if self.open_vscode:
            bindings[Channel.GUI] = VSCodeExecutor()
        return bindings

    def reset(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.source.write_text(
            "def add(left, right):\n    return left - right\n\n\n"
            "def multiply(left, right):\n    return left + right\n",
            encoding="utf-8",
        )
        self.test_file.write_text(
            "import unittest\n\nfrom calc import add, multiply\n\n\n"
            "class CalcTest(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n\n"
            "    def test_multiply(self):\n"
            "        self.assertEqual(multiply(3, 4), 12)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        self.opened = not self.open_vscode
        self.last_test = None

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
        source = self.source.read_text(encoding="utf-8")
        test = self.last_test or {"returncode": None, "stdout": "", "stderr": "not run"}
        return Observation(
            task=(
                "Diagnose two independent calculator defects, repair them through "
                "safe tools, and prove both tests pass."
            ),
            subgoal="Run the test suite"
            if test["returncode"] is None
            else "Choose a remaining defect and repair route"
            if test["returncode"]
            else "Verify completion",
            state={
                "workspace": str(self.workspace),
                "source_path": str(self.source),
                "source": source,
                "add_fixed": "return left + right" in source,
                "multiply_fixed": "return left * right" in source,
                "vscode_opened": self.opened,
                "test_returncode": test["returncode"],
                "test_stdout": test["stdout"][-2000:],
                "test_stderr": test["stderr"][-2000:],
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
        if observation.state["test_returncode"] is None:
            return (
                ActionCandidate(
                    "run_tests",
                    Channel.SCRIPT,
                    "tests.run",
                    "Run both unit tests in an isolated Python process and capture the failure evidence.",
                    {"cwd": str(self.workspace)},
                    intent="diagnose" if not history else "validate_repairs",
                ),
            )
        if observation.state["test_returncode"]:
            pending: list[ActionCandidate] = []

            def add_repair_routes(
                intent: str, suffix: str, old: str, new: str, replacement_line: str, line: int
            ) -> None:
                updated = observation.state["source"].replace(old, new)
                common = {"path": str(self.source), "text": updated}
                expected = {"path": str(self.source), "contains": replacement_line.strip()}
                pending.extend(
                    (
                        ActionCandidate(
                            f"mcp_{suffix}",
                            Channel.MCP,
                            "mcp.filesystem.write_text",
                            f"Repair {intent} through MCP.",
                            common,
                            Risk.LOCAL_WRITE,
                            verifier="file.contains",
                            expected=expected,
                            intent=intent,
                        ),
                        ActionCandidate(
                            f"api_{suffix}",
                            Channel.API,
                            "filesystem.write_text",
                            f"Repair {intent} through the typed filesystem API.",
                            common,
                            Risk.LOCAL_WRITE,
                            verifier="file.contains",
                            expected=expected,
                            intent=intent,
                        ),
                        ActionCandidate(
                            f"cli_{suffix}",
                            Channel.CLI,
                            "cli.replace_exact",
                            f"Repair {intent} through an argv-only exact patch.",
                            {"path": str(self.source), "old": old, "new": new},
                            Risk.LOCAL_WRITE,
                            verifier="file.contains",
                            expected=expected,
                            intent=intent,
                        ),
                    )
                )
                if self.open_vscode:
                    pending.append(
                        ActionCandidate(
                            f"gui_{suffix}",
                            Channel.GUI,
                            "vscode.uia_replace_line",
                            f"Repair {intent} visibly in the VS Code editor.",
                            {"path": str(self.source), "line": line, "text": replacement_line},
                            Risk.LOCAL_WRITE,
                            verifier="file.contains",
                            expected=expected,
                            intent=intent,
                        )
                    )

            if not observation.state["add_fixed"]:
                add_repair_routes(
                    "repair_addition",
                    "repair_add",
                    "def add(left, right):\n    return left - right",
                    "def add(left, right):\n    return left + right",
                    "    return left + right",
                    2,
                )
            if not observation.state["multiply_fixed"]:
                add_repair_routes(
                    "repair_multiplication",
                    "repair_multiply",
                    "def multiply(left, right):\n    return left + right",
                    "def multiply(left, right):\n    return left * right",
                    "    return left * right",
                    6,
                )
            return tuple(pending)
        return (
            ActionCandidate(
                "done",
                Channel.CONTROL,
                "control.done",
                "Declare completion only after both tests pass.",
                intent="finish",
            ),
        )

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict[str, Any]:
            if candidate.capability != "tests.run":
                raise ValueError(f"unsupported task capability: {candidate.capability}")
            completed = self._test()
            return {
                "returncode": completed.returncode,
                "stdout": completed.stdout[-20_000:],
                "stderr": completed.stderr[-5_000:],
            }

        return execute_with_receipt(candidate, observation_id, decision_id, operation)

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
        if candidate.capability == "tests.run":
            self.last_test = dict(receipt.output)
            reason = "test_suite_passed" if receipt.output["returncode"] == 0 else "test_failures_captured"
            return Evaluation(False, False, reason, {"returncode": receipt.output["returncode"]})
        if candidate.capability != "control.done":
            self.last_test = None
            return Evaluation(False, False, "repair_written; rerun_tests")
        passed = self._test().returncode == 0 and self.source.read_text("utf-8") == self.corrected_source
        return Evaluation(passed, True, "test_suite_verified" if passed else "test_suite_failed")


SUITE_NAMES = ("edge", "excel", "vscode", "explorer")


def make_suite(
    name: str,
    workspace: str | Path,
    *,
    headed_edge: bool = False,
    open_vscode: bool = False,
    visible_apps: bool = False,
):
    root = Path(workspace).resolve() / name
    if name == "edge":
        return EdgeProductTask(root, headless=not headed_edge)
    if name == "excel":
        return ExcelSalesTask(root, visible=visible_apps)
    if name == "vscode":
        return VSCodeTerminalTask(root, open_vscode=open_vscode)
    if name == "explorer":
        return FileOrganizationTask(root, visible=visible_apps)
    raise ValueError(f"unknown suite: {name}")
