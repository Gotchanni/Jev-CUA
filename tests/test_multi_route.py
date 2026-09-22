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
    assert len({candidate.intent for candidate in candidates}) == 6


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
        "find_maximum",
        "count_products",
        "mark_reviewed",
        "visualize_revenue",
    }


def test_adaptive_edge_offers_physical_and_dom_routes(tmp_path: Path) -> None:
    task = EdgeProductTask(tmp_path, demo_mode=True, adaptive_mode=True)
    observation = Observation(
        "task",
        "login",
        {
            "url": "https://www.saucedemo.com/",
            "logged_in": False,
            "username": "",
            "password_entered": False,
            "sort": "",
            "cart_count": "0",
            "cart_open": False,
        },
    )

    candidates = task.candidates(observation, ())
    assert channels(candidates) == {Channel.GUI, Channel.SCRIPT}
    assert {candidate.intent for candidate in candidates} == {"enter_username"}


def test_adaptive_edge_exposes_complete_long_horizon_checkout(tmp_path: Path) -> None:
    task = EdgeProductTask(tmp_path, demo_mode=True, adaptive_mode=True)
    base = {
        "url": "https://www.saucedemo.com/inventory.html",
        "logged_in": True,
        "username": "standard_user",
        "password_entered": True,
        "sort": "lohi",
        "cart_count": "1",
        "cart_open": False,
        "checkout_form": False,
        "checkout_review": False,
        "checkout_complete": False,
        "backpack_present": False,
        "bike_light_present": False,
        "first_name": "",
        "last_name": "",
        "postal_code": "",
    }

    observation = Observation("task", "cart", base)
    assert {item.intent for item in task.candidates(observation, ())} == {"add_second_product"}

    cart = {**base, "url": "https://www.saucedemo.com/cart.html", "cart_count": "2"}
    cart.update(cart_open=True, backpack_present=True, bike_light_present=True)
    assert {item.intent for item in task.candidates(Observation("task", "cart", cart), ())} == {
        "begin_checkout"
    }

    form = {**base, "url": "https://www.saucedemo.com/checkout-step-one.html"}
    form.update(checkout_form=True, cart_count="2")
    assert {item.intent for item in task.candidates(Observation("task", "form", form), ())} == {
        "enter_first_name"
    }
    form.update(first_name="Ada", last_name="Lovelace", postal_code="310027")
    assert {item.intent for item in task.candidates(Observation("task", "form", form), ())} == {
        "continue_checkout"
    }

    review = {**base, "url": "https://www.saucedemo.com/checkout-step-two.html"}
    review.update(checkout_review=True, cart_count="2")
    assert {item.intent for item in task.candidates(Observation("task", "review", review), ())} == {
        "finish_checkout"
    }

    complete = {**base, "url": "https://www.saucedemo.com/checkout-complete.html"}
    complete.update(checkout_complete=True, cart_count="0")
    candidates = task.candidates(Observation("task", "complete", complete), ())
    assert len(candidates) == 1
    assert candidates[0].capability == "control.done"


def test_adaptive_excel_offers_physical_and_live_com_routes(tmp_path: Path) -> None:
    task = ExcelSalesTask(tmp_path, visible=True, demo_mode=True, adaptive_mode=True)
    observation = Observation(
        "task",
        "edit",
        {"summary_value": None, "average_value": None, "review_status": None, "chart_count": 0},
    )

    assert channels(task.candidates(observation, ())) == {Channel.GUI, Channel.SCRIPT}
