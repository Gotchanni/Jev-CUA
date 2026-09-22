import os
import sys
from pathlib import Path

import pytest

from cua_jev.cli import _suite_runner
from cua_jev.episode import EpisodeStatus
from cua_jev.suites import EdgeProductTask, ExcelSalesTask, VSCodeTerminalTask


def test_vscode_terminal_task_completes_real_test_cycle(tmp_path: Path) -> None:
    task = VSCodeTerminalTask(tmp_path / "vscode")
    result = _suite_runner("rule", tmp_path / "vscode.jsonl").run(task)

    assert result.status == EpisodeStatus.SUCCESS
    assert len(result.steps) == 18
    assert task._test().returncode == 0
    assert "return left + right" in task.source.read_text(encoding="utf-8")
    assert "return left * right" in task.source.read_text(encoding="utf-8")
    assert "return left - right" in task.source.read_text(encoding="utf-8")
    assert "return left / right" in task.source.read_text(encoding="utf-8")
    assert "return max(low, min(value, high))" in task.source.read_text(encoding="utf-8")
    assert "return (part / whole) * 100" in task.source.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="the system Edge channel is a Windows demo dependency")
def test_edge_task_completes_real_dom_and_download_cycle(tmp_path: Path) -> None:
    pytest.importorskip("playwright.sync_api")
    task = EdgeProductTask(tmp_path / "edge")
    try:
        result = _suite_runner("rule", tmp_path / "edge.jsonl").run(task)
    except Exception as exc:
        pytest.skip(f"system Edge is unavailable: {exc}")

    assert result.status == EpisodeStatus.SUCCESS
    assert len(result.steps) == 7
    assert "ThinkPad,laptop,999" in task.download.read_text(encoding="utf-8")


@pytest.mark.skipif(
    sys.platform != "win32" or os.getenv("CUA_JEV_RUN_EXCEL_INTEGRATION") != "1",
    reason="set CUA_JEV_RUN_EXCEL_INTEGRATION=1 on a Windows host with desktop Excel",
)
def test_excel_task_completes_real_workbook_cycle(tmp_path: Path) -> None:
    pytest.importorskip("win32com.client")
    task = ExcelSalesTask(tmp_path / "excel")
    try:
        result = _suite_runner("rule", tmp_path / "excel.jsonl").run(task)
    except Exception as exc:
        pytest.skip(f"desktop Excel is unavailable: {exc}")

    assert result.status == EpisodeStatus.SUCCESS
    assert len(result.steps) == 11
