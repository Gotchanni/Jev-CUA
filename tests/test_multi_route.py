from pathlib import Path

from cua_jev.models import Channel, Observation
from cua_jev.sandbox import FileOrganizationTask
from cua_jev.suites import EdgeProductTask, ExcelSalesTask, VSCodeTerminalTask


def channels(candidates) -> set[Channel]:
    return {candidate.channel for candidate in candidates}


def test_edge_offers_gui_and_script_routes_for_same_subgoal(tmp_path: Path) -> None:
    task = EdgeProductTask(tmp_path)
    observation = Observation(
        "task",
        "fill",
        {"query": "", "max_price": "", "in_stock": False, "status": "idle", "download_exists": False},
    )

    candidates = task.candidates(observation, ())
    assert channels(candidates) == {Channel.GUI, Channel.SCRIPT}
    assert {candidate.intent for candidate in candidates} == {
        "set_category",
        "set_budget",
        "require_availability",
    }


def test_excel_offers_com_and_file_api_routes(tmp_path: Path) -> None:
    task = ExcelSalesTask(tmp_path, visible=True)
    observation = Observation(
        "task",
        "formula",
        {"summary_value": None, "average_value": None, "review_status": None, "chart_count": 0},
    )

    candidates = task.candidates(observation, ())
    assert channels(candidates) == {Channel.GUI, Channel.SCRIPT, Channel.API}
    assert len({candidate.intent for candidate in candidates}) == 4


def test_vscode_offers_three_repair_routes(tmp_path: Path) -> None:
    task = VSCodeTerminalTask(tmp_path)
    observation = Observation(
        "task",
        "repair",
        {
            "vscode_opened": True,
            "test_returncode": 1,
            "source": (
                "def add(left, right):\n    return left - right\n\n\n"
                "def multiply(left, right):\n    return left + right\n"
            ),
            "add_fixed": False,
            "multiply_fixed": False,
        },
    )

    candidates = task.candidates(observation, ())
    assert channels(candidates) == {Channel.MCP, Channel.API, Channel.CLI}
    assert {candidate.intent for candidate in candidates} == {"repair_addition", "repair_multiplication"}


def test_explorer_offers_three_copy_routes(tmp_path: Path) -> None:
    task = FileOrganizationTask(tmp_path)
    task.reset()
    observation = task.observe(())

    assert channels(task.candidates(observation, ())) == {Channel.MCP, Channel.API, Channel.CLI}


def test_visible_profile_exposes_only_physical_edge_actions(tmp_path: Path) -> None:
    task = EdgeProductTask(tmp_path, demo_mode=True)
    observation = Observation(
        "task",
        "navigate",
        {
            "url": "about:blank",
            "logged_in": False,
            "username": "",
            "password_entered": False,
            "sort": "",
            "cart_count": "0",
            "cart_open": False,
        },
    )

    candidates = task.candidates(observation, ())
    assert channels(candidates) == {Channel.GUI}
    assert candidates[0].capability == "edge.navigate"


def test_visible_profile_keeps_parallel_excel_intents_but_only_gui(tmp_path: Path) -> None:
    task = ExcelSalesTask(tmp_path, visible=True, demo_mode=True)
    observation = Observation(
        "task",
        "edit",
        {"summary_value": None, "average_value": None, "review_status": None, "chart_count": 0},
    )

    candidates = task.candidates(observation, ())
    assert channels(candidates) == {Channel.GUI}
    assert {candidate.intent for candidate in candidates} == {
        "calculate_total",
        "calculate_average",
        "mark_reviewed",
        "visualize_revenue",
    }
