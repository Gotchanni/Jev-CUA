from pathlib import Path

from cua_jev.models import Channel, Observation
from cua_jev.sandbox import FileOrganizationTask
from cua_jev.suites import EdgeProductTask, ExcelSalesTask, VSCodeTerminalTask


def channels(candidates) -> set[Channel]:
    return {candidate.channel for candidate in candidates}


def test_edge_offers_gui_and_script_routes_for_same_subgoal(tmp_path: Path) -> None:
    task = EdgeProductTask(tmp_path)
    observation = Observation("task", "fill", {"query": "", "status": "idle", "download_exists": False})

    assert channels(task.candidates(observation, ())) == {Channel.GUI, Channel.SCRIPT}


def test_excel_offers_com_and_file_api_routes(tmp_path: Path) -> None:
    task = ExcelSalesTask(tmp_path)
    observation = Observation("task", "formula", {"summary_value": None, "chart_count": 0})

    assert channels(task.candidates(observation, ())) == {Channel.SCRIPT, Channel.API}


def test_vscode_offers_three_repair_routes(tmp_path: Path) -> None:
    task = VSCodeTerminalTask(tmp_path)
    observation = Observation(
        "task",
        "repair",
        {"vscode_opened": True, "test_returncode": 1},
    )

    assert channels(task.candidates(observation, ())) == {Channel.MCP, Channel.API, Channel.CLI}


def test_explorer_offers_three_copy_routes(tmp_path: Path) -> None:
    task = FileOrganizationTask(tmp_path)
    task.reset()
    observation = task.observe(())

    assert channels(task.candidates(observation, ())) == {Channel.MCP, Channel.API, Channel.CLI}
