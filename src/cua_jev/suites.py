from __future__ import annotations

import gc
import shutil
import subprocess
import sys
import time
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
    ScreenController,
    VSCodeExecutor,
)
from .executors.common import execute_with_receipt
from .models import ActionCandidate, ActionReceipt, Channel, Observation, Risk, Verification
from .runtime import StepResult
from .sandbox import FileOrganizationTask, sandbox_mcp_executor


class EdgeProductTask:
    """Filter a local product page and download a CSV through a real Edge DOM session."""

    name = "edge-product-filter"

    def __init__(
        self,
        workspace: str | Path,
        *,
        headless: bool = True,
        demo_mode: bool = False,
        adaptive_mode: bool = False,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.download = self.workspace / "products.csv"
        self.headless = headless
        self.demo_mode = demo_mode
        self.adaptive_mode = adaptive_mode
        self.screen = ScreenController()
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
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                channel="msedge",
                headless=self.headless,
                args=["--window-position=80,60", "--window-size=1280,900"],
            )
        except Exception:
            self.close()
            raise
        context = self._browser.new_context(
            accept_downloads=True,
            no_viewport=True if self.demo_mode else None,
        )
        self._page = context.new_page()
        if self.demo_mode:
            self._page.goto("about:blank")
            self._page.evaluate("document.title = 'CUA-JEV Live Edge Session'")
            self._page.bring_to_front()
            time.sleep(1)
        else:
            fixture = Path(__file__).with_name("fixtures") / "product_filter.html"
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
        if self.demo_mode:
            return self._observe_live_edge()
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

    def _observe_live_edge(self) -> Observation:
        url = self._page.url

        def value(selector: str) -> str:
            locator = self._page.locator(selector)
            return locator.input_value() if locator.count() else ""

        logged_in = any(
            path in url
            for path in (
                "/inventory.html",
                "/cart.html",
                "/checkout-step-one.html",
                "/checkout-step-two.html",
                "/checkout-complete.html",
            )
        )
        backpack_present = (
            self._page.locator(".inventory_item_name").filter(has_text="Sauce Labs Backpack").count() > 0
        )
        bike_light_present = (
            self._page.locator(".inventory_item_name").filter(has_text="Sauce Labs Bike Light").count() > 0
        )
        checkout_complete = "/checkout-complete.html" in url
        return Observation(
            task=(
                "Use the public SauceDemo store in Edge: sign in, sort products by price, "
                "build a two-item cart, complete checkout, and verify the receipt."
            ),
            subgoal="Verify checkout receipt" if checkout_complete else "Advance the live browser workflow",
            state={
                "url": url,
                "public_site": "saucedemo.com",
                "username": value("#user-name"),
                "password_entered": bool(value("#password")),
                "logged_in": logged_in,
                "sort": value(".product_sort_container") if logged_in else "",
                "cart_count": (
                    self._page.locator(".shopping_cart_badge").text_content()
                    if self._page.locator(".shopping_cart_badge").count()
                    else "0"
                ),
                "cart_open": "/cart.html" in url,
                "backpack_present": backpack_present,
                "bike_light_present": bike_light_present,
                "checkout_form": "/checkout-step-one.html" in url,
                "checkout_review": "/checkout-step-two.html" in url,
                "checkout_complete": checkout_complete,
                "first_name": value("#first-name"),
                "last_name": value("#last-name"),
                "postal_code": value("#postal-code"),
                "receipt_text": (
                    self._page.locator(".complete-header").text_content()
                    if self._page.locator(".complete-header").count()
                    else ""
                ),
            },
            source=self.name,
        )

    def candidates(
        self, observation: Observation, history: Sequence[StepResult]
    ) -> Sequence[ActionCandidate]:
        if self.demo_mode:
            return self._live_edge_candidates(observation)
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
            return self._profile_routes(pending)
        if state["status"] not in {"review", "complete"}:
            return self._profile_routes(
                (
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
            )
        if state["status"] == "review":
            return self._profile_routes(
                (
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
            )
        if not state["download_exists"]:
            return self._profile_routes(
                (
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

    def _live_edge_candidates(self, observation: Observation) -> tuple[ActionCandidate, ...]:
        state = observation.state
        if "saucedemo.com" not in state["url"]:
            return self._live_routes(
                ActionCandidate(
                    "gui_navigate_store",
                    Channel.GUI,
                    "edge.navigate",
                    "Navigate the visible Edge address bar to the public SauceDemo store.",
                    {"url": "https://www.saucedemo.com/"},
                    intent="open_public_store",
                ),
                ActionCandidate(
                    "dom_navigate_store",
                    Channel.SCRIPT,
                    "edge.page_navigate",
                    "Navigate the public store through the browser page API.",
                    {"url": "https://www.saucedemo.com/"},
                    intent="open_public_store",
                ),
            )
        if not state["logged_in"]:
            if state["username"] != "standard_user":
                return self._live_routes(
                    ActionCandidate(
                        "gui_enter_username",
                        Channel.GUI,
                        "edge.fill",
                        "Enter the public SauceDemo standard user through physical keyboard input.",
                        {"selector": "#user-name", "text": "standard_user"},
                        Risk.LOCAL_WRITE,
                        intent="enter_username",
                    ),
                    ActionCandidate(
                        "dom_enter_username",
                        Channel.SCRIPT,
                        "edge.fill",
                        "Fill the username through the live DOM route.",
                        {"selector": "#user-name", "text": "standard_user"},
                        Risk.LOCAL_WRITE,
                        intent="enter_username",
                    ),
                )
            if not state["password_entered"]:
                return self._live_routes(
                    ActionCandidate(
                        "gui_enter_password",
                        Channel.GUI,
                        "edge.fill",
                        "Enter the documented SauceDemo password through physical keyboard input.",
                        {"selector": "#password", "text": "secret_sauce"},
                        Risk.LOCAL_WRITE,
                        intent="enter_password",
                    ),
                    ActionCandidate(
                        "dom_enter_password",
                        Channel.SCRIPT,
                        "edge.fill",
                        "Fill the password through the live DOM route.",
                        {"selector": "#password", "text": "secret_sauce"},
                        Risk.LOCAL_WRITE,
                        intent="enter_password",
                    ),
                )
            return self._live_routes(
                ActionCandidate(
                    "gui_sign_in",
                    Channel.GUI,
                    "edge.click",
                    "Click the visible sign-in button with the physical mouse.",
                    {"selector": "#login-button"},
                    Risk.LOCAL_WRITE,
                    intent="sign_in",
                ),
                ActionCandidate(
                    "dom_sign_in",
                    Channel.SCRIPT,
                    "edge.click",
                    "Activate sign-in through the live DOM route.",
                    {"selector": "#login-button"},
                    Risk.LOCAL_WRITE,
                    intent="sign_in",
                ),
            )
        if state.get("checkout_complete"):
            return (
                ActionCandidate(
                    "done",
                    Channel.CONTROL,
                    "control.done",
                    "Declare completion only after the live checkout receipt is visible.",
                    intent="finish",
                ),
            )
        if state.get("checkout_form"):
            fields = (
                ("first_name", "Ada", "#first-name", "enter_first_name"),
                ("last_name", "Lovelace", "#last-name", "enter_last_name"),
                ("postal_code", "310027", "#postal-code", "enter_postal_code"),
            )
            for key, text, selector, intent in fields:
                if state[key] != text:
                    return self._live_routes(
                        ActionCandidate(
                            f"gui_{intent}",
                            Channel.GUI,
                            "edge.fill",
                            f"Enter checkout field {key} with physical keyboard input.",
                            {"selector": selector, "text": text},
                            Risk.LOCAL_WRITE,
                            intent=intent,
                        ),
                        ActionCandidate(
                            f"dom_{intent}",
                            Channel.SCRIPT,
                            "edge.fill",
                            f"Enter checkout field {key} through the live DOM route.",
                            {"selector": selector, "text": text},
                            Risk.LOCAL_WRITE,
                            intent=intent,
                        ),
                    )
            return self._live_routes(
                ActionCandidate(
                    "gui_continue_checkout",
                    Channel.GUI,
                    "edge.click",
                    "Continue from the checkout form with the physical mouse.",
                    {"selector": "#continue"},
                    Risk.LOCAL_WRITE,
                    intent="continue_checkout",
                ),
                ActionCandidate(
                    "dom_continue_checkout",
                    Channel.SCRIPT,
                    "edge.click",
                    "Continue from the checkout form through the live DOM route.",
                    {"selector": "#continue"},
                    Risk.LOCAL_WRITE,
                    intent="continue_checkout",
                ),
            )
        if state.get("checkout_review"):
            return self._live_routes(
                ActionCandidate(
                    "gui_finish_checkout",
                    Channel.GUI,
                    "edge.click",
                    "Finish the reviewed order with the physical mouse.",
                    {"selector": "#finish"},
                    Risk.LOCAL_WRITE,
                    intent="finish_checkout",
                ),
                ActionCandidate(
                    "dom_finish_checkout",
                    Channel.SCRIPT,
                    "edge.click",
                    "Finish the reviewed order through the live DOM route.",
                    {"selector": "#finish"},
                    Risk.LOCAL_WRITE,
                    intent="finish_checkout",
                ),
            )
        if state["cart_open"]:
            if not (state.get("backpack_present") and state.get("bike_light_present")):
                raise RuntimeError("live cart lost one of the required products")
            return self._live_routes(
                ActionCandidate(
                    "gui_begin_checkout",
                    Channel.GUI,
                    "edge.click",
                    "Start checkout from the validated cart with the physical mouse.",
                    {"selector": "#checkout"},
                    Risk.LOCAL_WRITE,
                    intent="begin_checkout",
                ),
                ActionCandidate(
                    "dom_begin_checkout",
                    Channel.SCRIPT,
                    "edge.click",
                    "Start checkout from the validated cart through the live DOM route.",
                    {"selector": "#checkout"},
                    Risk.LOCAL_WRITE,
                    intent="begin_checkout",
                ),
            )
        if state["sort"] != "lohi":
            return self._live_routes(
                ActionCandidate(
                    "gui_sort_low_to_high",
                    Channel.GUI,
                    "edge.select_low_to_high",
                    "Sort the live product list from low to high with mouse and keyboard.",
                    {"selector": ".product_sort_container"},
                    Risk.LOCAL_WRITE,
                    intent="sort_products",
                ),
                ActionCandidate(
                    "dom_sort_low_to_high",
                    Channel.SCRIPT,
                    "edge.dom_select",
                    "Select low-to-high sorting through the live DOM route.",
                    {"selector": ".product_sort_container", "value": "lohi"},
                    Risk.LOCAL_WRITE,
                    intent="sort_products",
                ),
            )
        if state["cart_count"] == "0":
            return self._live_routes(
                ActionCandidate(
                    "gui_add_backpack",
                    Channel.GUI,
                    "edge.click",
                    "Add Sauce Labs Backpack to the cart with the physical mouse.",
                    {"selector": "#add-to-cart-sauce-labs-backpack"},
                    Risk.LOCAL_WRITE,
                    intent="add_product",
                ),
                ActionCandidate(
                    "dom_add_backpack",
                    Channel.SCRIPT,
                    "edge.click",
                    "Add Sauce Labs Backpack through the live DOM route.",
                    {"selector": "#add-to-cart-sauce-labs-backpack"},
                    Risk.LOCAL_WRITE,
                    intent="add_product",
                ),
            )
        if state["cart_count"] == "1":
            return self._live_routes(
                ActionCandidate(
                    "gui_add_bike_light",
                    Channel.GUI,
                    "edge.click",
                    "Add Sauce Labs Bike Light to the cart with the physical mouse.",
                    {"selector": "#add-to-cart-sauce-labs-bike-light"},
                    Risk.LOCAL_WRITE,
                    intent="add_second_product",
                ),
                ActionCandidate(
                    "dom_add_bike_light",
                    Channel.SCRIPT,
                    "edge.click",
                    "Add Sauce Labs Bike Light through the live DOM route.",
                    {"selector": "#add-to-cart-sauce-labs-bike-light"},
                    Risk.LOCAL_WRITE,
                    intent="add_second_product",
                ),
            )
        if not state["cart_open"]:
            return self._live_routes(
                ActionCandidate(
                    "gui_open_cart",
                    Channel.GUI,
                    "edge.click",
                    "Open the visible shopping cart with the physical mouse.",
                    {"selector": ".shopping_cart_link"},
                    Risk.READ_ONLY,
                    intent="review_cart",
                ),
                ActionCandidate(
                    "dom_open_cart",
                    Channel.SCRIPT,
                    "edge.click",
                    "Open the cart through the live DOM route.",
                    {"selector": ".shopping_cart_link"},
                    Risk.READ_ONLY,
                    intent="review_cart",
                ),
            )
        raise RuntimeError("live Edge state has no legal continuation")

    def _live_routes(self, gui: ActionCandidate, structured: ActionCandidate) -> tuple[ActionCandidate, ...]:
        return (gui, structured) if self.adaptive_mode else (gui,)

    def _profile_routes(self, candidates: Sequence[ActionCandidate]) -> tuple[ActionCandidate, ...]:
        if not self.demo_mode:
            return tuple(candidates)
        return tuple(candidate for candidate in candidates if candidate.channel == Channel.GUI)

    def _screen_point(self, selector: str, window) -> tuple[float, float]:
        if self._page is None:
            raise RuntimeError("Edge page is unavailable")
        point = self._page.locator(selector).evaluate(
            """element => {
              const rect = element.getBoundingClientRect();
              return {
                x: (window.outerWidth - window.innerWidth) / 2 + rect.left + rect.width / 2,
                y: window.outerHeight - window.innerHeight + rect.top + rect.height / 2,
                outerWidth: window.outerWidth,
                outerHeight: window.outerHeight
              };
            }"""
        )
        rectangle = window.rectangle()
        return (
            rectangle.left + float(point["x"]) * rectangle.width() / float(point["outerWidth"]),
            rectangle.top + float(point["y"]) * rectangle.height() / float(point["outerHeight"]),
        )

    def _screen_action(self, candidate: ActionCandidate) -> dict[str, Any]:
        if self._page is None:
            raise RuntimeError("Edge page is unavailable")
        self._page.bring_to_front()
        if candidate.capability == "edge.navigate":
            self.screen.focus(r".*CUA-JEV Live Edge Session.*")
            self.screen.hotkey("ctrl", "l")
            self.screen.paste_text(candidate.arguments["url"])
            self.screen.press("enter")
            time.sleep(0.5)
            if self._page.url == "about:blank":
                self.screen.press("enter")
            self._page.wait_for_url("**saucedemo.com/**", timeout=20_000)
            return {"backend": "pyautogui", "url": self._page.url, "target": "address_bar"}
        window = self.screen.focus(r".*Swag Labs.*")
        selector = candidate.arguments["selector"]
        locator = self._page.locator(selector)
        if selector == "#add-to-cart-sauce-labs-backpack":
            self.screen.hotkey("ctrl", "f")
            self.screen.write("Sauce Labs Backpack")
            self.screen.press("enter")
            self.screen.press("esc")
        rectangle = window.rectangle()
        self.screen.move_point(rectangle.mid_point().x, rectangle.mid_point().y)
        for _ in range(8):
            box = locator.bounding_box()
            viewport_height = self._page.evaluate("window.innerHeight")
            if box and 0 <= box["y"] and box["y"] + box["height"] <= viewport_height:
                break
            self.screen.scroll(5 if box and box["y"] < 0 else -5)
        x, y = self._screen_point(selector, window)
        if candidate.capability == "edge.download":
            with self._page.expect_download() as pending:
                self.screen.click_point(x, y)
            pending.value.save_as(candidate.arguments["destination_path"])
        else:
            self.screen.click_point(x, y)
            if candidate.capability == "edge.fill":
                self.screen.hotkey("ctrl", "a")
                self.screen.write(candidate.arguments["text"])
            elif candidate.capability == "edge.select_low_to_high":
                self.screen.press("home")
                self.screen.press("down")
                self.screen.press("down")
                self.screen.press("enter")
        self._page.wait_for_timeout(500)
        return {
            "backend": "pyautogui",
            "selector": selector,
            "point": [round(x), round(y)],
            "url": self._page.url,
        }

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict[str, Any]:
            if self._page is None:
                raise RuntimeError("Edge page is unavailable")
            if self.demo_mode and candidate.channel == Channel.GUI:
                return self._screen_action(candidate)
            selector = candidate.arguments.get("selector")
            if candidate.capability == "edge.page_navigate":
                self._page.goto(candidate.arguments["url"], wait_until="domcontentloaded")
            elif candidate.capability == "edge.fill":
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
            elif candidate.capability == "edge.dom_select":
                self._page.locator(selector).select_option(candidate.arguments["value"])
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
        if self.demo_mode:
            state = self._observe_live_edge().state
            valid = bool(state["checkout_complete"] and state["receipt_text"] == "Thank you for your order!")
            return Evaluation(
                valid,
                True,
                "live_edge_checkout_verified" if valid else "live_edge_checkout_invalid",
            )
        payload = self.download.read_text("utf-8") if self.download.is_file() else ""
        valid = "ThinkPad,laptop,999,true" in payload and "Surface,laptop,1099,true" in payload
        return Evaluation(valid, True, "edge_export_verified" if valid else "edge_export_invalid")


class ExcelSalesTask:
    """Create a formula and chart in a real workbook, then inspect it through a fresh COM process."""

    name = "excel-sales-summary"

    def __init__(
        self,
        workspace: str | Path,
        *,
        visible: bool = False,
        demo_mode: bool = False,
        adaptive_mode: bool = False,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workbook = self.workspace / "sales.xlsx"
        self.visible = visible
        self.demo_mode = demo_mode
        self.adaptive_mode = adaptive_mode
        self.screen = ScreenController()
        self._demo_pythoncom: Any = None
        self._demo_excel: Any = None
        self._demo_book: Any = None

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.workspace,)

    def executor_bindings(self) -> dict[Channel, object]:
        bindings = {
            Channel.SCRIPT: self
            if self.demo_mode and self.adaptive_mode
            else ExcelComExecutor(visible=False),
            Channel.API: OpenPyxlExecutor(),
            Channel.CONTROL: ControlExecutor(),
        }
        if self.visible:
            bindings[Channel.GUI] = self if self.demo_mode else ExcelComExecutor(visible=True)
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
            data.Range("A1:C7").Value = (
                ("Product", "Units", "Revenue"),
                ("Laptop", 2, 240),
                ("Monitor", 3, 240),
                ("Keyboard", 5, 500),
                ("Mouse", 4, 160),
                ("Dock", 2, 220),
                ("Headset", 3, 180),
            )
            summary.Range("A1:B6").Value = (
                ("Metric", "Value"),
                ("Total revenue", None),
                ("Average revenue", None),
                ("Maximum revenue", None),
                ("Product count", None),
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
        if self.demo_mode:
            pythoncom.CoInitialize()
            self._demo_pythoncom = pythoncom
            self._demo_excel = win32.DispatchEx("Excel.Application")
            self._demo_excel.Visible = True
            self._demo_excel.DisplayAlerts = False
            self._demo_book = self._demo_excel.Workbooks.Open(str(self.workbook))
            self._demo_book.Worksheets("Summary").Activate()
            self.screen.focus_handle(self._demo_excel.Hwnd)

    def close(self) -> None:
        if self._demo_book is not None:
            try:
                self._demo_book.Save()
                self._demo_book.Close(SaveChanges=True)
            except Exception:
                pass
            self._demo_book = None
        if self._demo_excel is not None:
            try:
                self._demo_excel.Quit()
            except Exception:
                pass
            self._demo_excel = None
        if self._demo_pythoncom is not None:
            self._demo_pythoncom.CoUninitialize()
            self._demo_pythoncom = None

    def observe(self, history: Sequence[StepResult]) -> Observation:
        if self.demo_mode and self._demo_book is not None:
            deadline = time.time() + 10
            while True:
                try:
                    summary = self._demo_book.Worksheets("Summary")
                    self._demo_excel.Calculate()
                    value = summary.Range("B2").Value
                    formula = summary.Range("B2").Formula
                    average = summary.Range("B3").Value
                    average_formula = summary.Range("B3").Formula
                    maximum = summary.Range("B4").Value
                    maximum_formula = summary.Range("B4").Formula
                    product_count = summary.Range("B5").Value
                    count_formula = summary.Range("B5").Formula
                    review_status = summary.Range("B6").Value
                    charts = sum(
                        self._demo_book.Worksheets(i).ChartObjects().Count
                        for i in range(1, self._demo_book.Worksheets.Count + 1)
                    )
                    break
                except Exception:
                    if time.time() >= deadline:
                        raise
                    time.sleep(0.25)
            return self._observation(
                value,
                formula,
                average,
                average_formula,
                maximum,
                maximum_formula,
                product_count,
                count_formula,
                review_status,
                charts,
            )
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
            maximum = summary.Range("B4").Value
            maximum_formula = summary.Range("B4").Formula
            product_count = summary.Range("B5").Value
            count_formula = summary.Range("B5").Formula
            review_status = summary.Range("B6").Value
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
        return self._observation(
            value,
            formula,
            average,
            average_formula,
            maximum,
            maximum_formula,
            product_count,
            count_formula,
            review_status,
            charts,
        )

    def _observation(
        self,
        value,
        formula,
        average,
        average_formula,
        maximum,
        maximum_formula,
        product_count,
        count_formula,
        review_status,
        charts,
    ) -> Observation:
        return Observation(
            task=(
                "Build a reviewed sales summary with four independent metrics and two charts, "
                "then verify the saved workbook through a fresh Excel process."
            ),
            subgoal="Verify workbook"
            if value == 1540
            and average is not None
            and abs(float(average) - (1540 / 6)) < 0.001
            and maximum == 500
            and product_count == 6
            and charts >= 2
            and review_status == "Reviewed"
            else "Choose the next incomplete workbook operation",
            state={
                "workbook_path": str(self.workbook),
                "summary_value": value,
                "summary_formula": formula,
                "average_value": average,
                "average_formula": average_formula,
                "maximum_value": maximum,
                "maximum_formula": maximum_formula,
                "product_count": product_count,
                "count_formula": count_formula,
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

        if state["summary_value"] != 1540:
            add_cell_routes("calculate_total", "write_total_formula", "B2", formula="=SUM(Data!C2:C7)")
        if state["average_value"] is None or abs(float(state["average_value"]) - (1540 / 6)) >= 0.001:
            add_cell_routes(
                "calculate_average", "write_average_formula", "B3", formula="=AVERAGE(Data!C2:C7)"
            )
        if state.get("maximum_value") != 500:
            add_cell_routes("find_maximum", "write_max_formula", "B4", formula="=MAX(Data!C2:C7)")
        if state.get("product_count") != 6:
            add_cell_routes("count_products", "write_count_formula", "B5", formula="=COUNTA(Data!A2:A7)")
        if state["review_status"] != "Reviewed":
            add_cell_routes("mark_reviewed", "mark_reviewed", "B6", value="Reviewed")
        if state["chart_count"] < 1:
            com_args = {
                "workbook_path": str(self.workbook),
                "sheet": "Data",
                "range": "A1:C7",
                "title": "Revenue by product",
            }
            file_args = {
                "workbook_path": str(self.workbook),
                "sheet": "Data",
                "max_row": 7,
                "title": "Revenue by product",
                "x_axis_title": "Product",
                "y_axis_title": "Revenue",
                "anchor": "D2",
                "value_column": 3,
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
        if state["chart_count"] == 1:
            com_args = {
                "workbook_path": str(self.workbook),
                "sheet": "Data",
                "range": "A1:B7",
                "title": "Units by product",
            }
            file_args = {
                "workbook_path": str(self.workbook),
                "sheet": "Data",
                "max_row": 7,
                "title": "Units by product",
                "x_axis_title": "Product",
                "y_axis_title": "Units",
                "anchor": "D18",
                "value_column": 2,
            }
            if self.visible:
                pending.append(
                    ActionCandidate(
                        "gui_create_units_chart",
                        Channel.GUI,
                        "excel.create_chart",
                        "Create the units chart in a visible Excel window.",
                        com_args,
                        Risk.LOCAL_WRITE,
                        intent="visualize_units",
                    )
                )
            pending.extend(
                (
                    ActionCandidate(
                        "com_create_units_chart",
                        Channel.SCRIPT,
                        "excel.create_chart",
                        "Create the units chart through background Excel COM.",
                        com_args,
                        Risk.LOCAL_WRITE,
                        intent="visualize_units",
                    ),
                    ActionCandidate(
                        "file_create_units_chart",
                        Channel.API,
                        "excel.file_create_chart",
                        "Create the units chart through the workbook file API.",
                        file_args,
                        Risk.LOCAL_WRITE,
                        intent="visualize_units",
                    ),
                )
            )
        if pending:
            if self.demo_mode and not self.adaptive_mode:
                return tuple(candidate for candidate in pending if candidate.channel == Channel.GUI)
            if self.adaptive_mode:
                return tuple(
                    candidate for candidate in pending if candidate.channel in {Channel.GUI, Channel.SCRIPT}
                )
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

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict[str, Any]:
            if not self.demo_mode or self._demo_book is None:
                raise RuntimeError("persistent Excel demo session is unavailable")
            if candidate.channel == Channel.SCRIPT:
                if candidate.capability == "excel.write_range":
                    cell = self._demo_book.Worksheets(candidate.arguments["sheet"]).Range(
                        candidate.arguments["range"]
                    )
                    if "formula" in candidate.arguments:
                        cell.Formula = candidate.arguments["formula"]
                    else:
                        cell.Value = candidate.arguments["value"]
                elif candidate.capability == "excel.create_chart":
                    sheet = self._demo_book.Worksheets(candidate.arguments["sheet"])
                    chart_object = sheet.ChartObjects().Add(360, 40, 420, 240)
                    chart_object.Chart.SetSourceData(sheet.Range(candidate.arguments["range"]))
                    chart_object.Chart.HasTitle = True
                    chart_object.Chart.ChartTitle.Text = candidate.arguments["title"]
                else:
                    raise ValueError(f"unsupported Excel COM capability: {candidate.capability}")
                self._demo_book.Save()
                return {
                    "backend": "excel-com-live",
                    "workbook": str(self.workbook),
                    "capability": candidate.capability,
                }
            self.screen.focus_handle(self._demo_excel.Hwnd)
            if candidate.capability == "excel.write_range":
                address = f"{candidate.arguments['sheet']}!{candidate.arguments['range']}"
                text = str(candidate.arguments.get("formula", candidate.arguments.get("value", "")))
                self.screen.hotkey("ctrl", "g")
                self.screen.paste_text(address)
                self.screen.press("enter")
                self.screen.paste_text(text)
                self.screen.press("enter")
            elif candidate.capability == "excel.create_chart":
                address = f"{candidate.arguments['sheet']}!{candidate.arguments['range']}"
                self.screen.hotkey("ctrl", "g")
                self.screen.paste_text(address)
                self.screen.press("enter")
                self.screen.press("alt")
                self.screen.press("n")
                self.screen.press("r")
                time.sleep(1)
                self.screen.press("enter")
            else:
                raise ValueError(f"unsupported Excel screen capability: {candidate.capability}")
            self.screen.hotkey("ctrl", "s")
            time.sleep(1.5)
            return {
                "backend": "pyautogui",
                "workbook": str(self.workbook),
                "capability": candidate.capability,
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
            return Evaluation(False, False, "excel_action_not_verified")
        if candidate.capability != "control.done":
            return Evaluation(False, False, "excel_step_completed; reobserve")
        state = self.observe(())
        formula = str(state.state["summary_formula"]).upper()
        valid = (
            state.state["summary_value"] == 1540
            and "SUM(" in formula
            and abs(float(state.state["average_value"]) - (1540 / 6)) < 0.001
            and "AVERAGE(" in str(state.state["average_formula"]).upper()
            and state.state["maximum_value"] == 500
            and "MAX(" in str(state.state["maximum_formula"]).upper()
            and state.state["product_count"] == 6
            and "COUNTA(" in str(state.state["count_formula"]).upper()
            and state.state["review_status"] == "Reviewed"
            and state.state["chart_count"] >= 2
        )
        return Evaluation(valid, True, "excel_workbook_verified" if valid else "excel_workbook_invalid")


class VSCodeTerminalTask:
    """Diagnose and repair four independent defects, rerunning tests after each mutation."""

    name = "vscode-terminal-repair"
    corrected_source = (
        "def add(left, right):\n    return left + right\n\n\n"
        "def multiply(left, right):\n    return left * right\n\n\n"
        "def subtract(left, right):\n    return left - right\n\n\n"
        "def safe_divide(left, right):\n"
        "    if right == 0:\n        raise ValueError('division by zero')\n"
        "    return left / right\n"
    )

    def __init__(
        self,
        workspace: str | Path,
        *,
        open_vscode: bool = False,
        demo_mode: bool = False,
        adaptive_mode: bool = False,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.source = self.workspace / "calc.py"
        self.test_file = self.workspace / "test_calc.py"
        self.open_vscode = open_vscode
        self.demo_mode = demo_mode
        self.adaptive_mode = adaptive_mode
        self.screen = ScreenController()
        self.opened = False
        self.last_test: dict[str, Any] | None = None
        self._vscode_handle: int | None = None

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
            bindings[Channel.GUI] = self if self.demo_mode else VSCodeExecutor()
        return bindings

    def reset(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.source.write_text(
            "def add(left, right):\n    return left - right\n\n\n"
            "def multiply(left, right):\n    return left + right\n\n\n"
            "def subtract(left, right):\n    return left + right\n\n\n"
            "def safe_divide(left, right):\n"
            "    if right == 0:\n        raise ValueError('division by zero')\n"
            "    return left * right\n",
            encoding="utf-8",
        )
        self.test_file.write_text(
            "import unittest\n\nfrom calc import add, multiply, safe_divide, subtract\n\n\n"
            "class CalcTest(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n\n"
            "    def test_multiply(self):\n"
            "        self.assertEqual(multiply(3, 4), 12)\n\n"
            "    def test_subtract(self):\n"
            "        self.assertEqual(subtract(9, 4), 5)\n\n"
            "    def test_safe_divide(self):\n"
            "        self.assertEqual(safe_divide(9, 3), 3)\n"
            "        with self.assertRaises(ValueError):\n"
            "            safe_divide(9, 0)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        self.opened = not self.open_vscode
        self.last_test = None
        if self.demo_mode:
            try:
                from pywinauto import Desktop
            except ImportError:
                raise CapabilityUnavailable("install cua-jev[windows] for VS Code demo mode") from None
            executable = shutil.which("code") or shutil.which("code.cmd")
            if not executable:
                raise CapabilityUnavailable("VS Code 'code' CLI is not on PATH")
            desktop = Desktop(backend="uia")
            before = {window.handle for window in desktop.windows(title_re=r".*Visual Studio Code.*")}
            subprocess.run(
                [executable, "--new-window", str(self.workspace)],
                capture_output=True,
                text=True,
                timeout=15,
                shell=False,
                check=False,
            )
            deadline = time.time() + 15
            matches = []
            while time.time() < deadline:
                matches = [
                    window
                    for window in desktop.windows(title_re=r".*Visual Studio Code.*")
                    if window.handle not in before
                ]
                if matches:
                    break
                time.sleep(0.25)
            if not matches:
                matches = desktop.windows(title_re=r".*Visual Studio Code.*")
            if not matches:
                raise RuntimeError("VS Code window did not become available")
            self._vscode_handle = matches[-1].handle
            self.screen.focus_handle(self._vscode_handle)
            self.opened = True

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
                "Diagnose four independent calculator defects, repair them through heterogeneous "
                "safe tools, rerun regression tests after every mutation, and prove the suite passes."
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
                "add_fixed": "def add(left, right):\n    return left + right" in source,
                "multiply_fixed": "def multiply(left, right):\n    return left * right" in source,
                "subtract_fixed": "def subtract(left, right):\n    return left - right" in source,
                "divide_fixed": "    return left / right" in source,
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
            if self.demo_mode:
                candidates = (
                    ActionCandidate(
                        "gui_run_tests",
                        Channel.GUI,
                        "vscode.screen_run_tests",
                        "Run the unit tests visibly in the VS Code integrated terminal.",
                        {"cwd": str(self.workspace)},
                        intent="diagnose" if not history else "validate_repairs",
                    ),
                    ActionCandidate(
                        "script_run_tests",
                        Channel.SCRIPT,
                        "tests.run",
                        "Run the unit tests through the allowlisted process executor.",
                        {"cwd": str(self.workspace)},
                        intent="diagnose" if not history else "validate_repairs",
                    ),
                )
                return candidates if self.adaptive_mode else candidates[:1]
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
                expected = {"path": str(self.source), "contains": new}
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
            if not observation.state.get("subtract_fixed", True):
                add_repair_routes(
                    "repair_subtraction",
                    "repair_subtract",
                    "def subtract(left, right):\n    return left + right",
                    "def subtract(left, right):\n    return left - right",
                    "    return left - right",
                    10,
                )
            if not observation.state.get("divide_fixed", True):
                add_repair_routes(
                    "repair_division",
                    "repair_divide",
                    "def safe_divide(left, right):\n"
                    "    if right == 0:\n        raise ValueError('division by zero')\n"
                    "    return left * right\n",
                    "def safe_divide(left, right):\n"
                    "    if right == 0:\n        raise ValueError('division by zero')\n"
                    "    return left / right\n",
                    "    return left / right",
                    16,
                )
            if self.demo_mode and not self.adaptive_mode:
                return tuple(candidate for candidate in pending if candidate.channel == Channel.GUI)
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
            if candidate.capability == "vscode.screen_run_tests":
                self.screen.focus_handle(self._vscode_handle)
                self.screen.hotkey("ctrl", "`")
                self.screen.paste_text("python -B -m unittest discover -s . -q")
                self.screen.press("enter")
                time.sleep(2)
                completed = self._test()
                return {
                    "backend": "pyautogui",
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-20_000:],
                    "stderr": completed.stderr[-5_000:],
                }
            if candidate.capability == "vscode.uia_replace_line" and self.demo_mode:
                self.screen.focus_handle(self._vscode_handle)
                self.screen.hotkey("ctrl", "p")
                self.screen.paste_text(f"calc.py:{int(candidate.arguments['line'])}")
                self.screen.press("enter")
                self.screen.hotkey("ctrl", "l")
                self.screen.paste_text(f"{candidate.arguments['text']}\n")
                self.screen.hotkey("ctrl", "s")
                return {
                    "backend": "pyautogui",
                    "path": str(self.source),
                    "line": int(candidate.arguments["line"]),
                }
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
        if candidate.capability in {"tests.run", "vscode.screen_run_tests"}:
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
    profile: str = "hybrid",
):
    root = Path(workspace).resolve() / name
    demo_mode = profile in {"visible", "adaptive"}
    adaptive_mode = profile == "adaptive"
    if name == "edge":
        return EdgeProductTask(
            root,
            headless=not headed_edge,
            demo_mode=demo_mode,
            adaptive_mode=adaptive_mode,
        )
    if name == "excel":
        return ExcelSalesTask(
            root,
            visible=visible_apps,
            demo_mode=demo_mode,
            adaptive_mode=adaptive_mode,
        )
    if name == "vscode":
        return VSCodeTerminalTask(
            root,
            open_vscode=open_vscode,
            demo_mode=demo_mode,
            adaptive_mode=adaptive_mode,
        )
    if name == "explorer":
        return FileOrganizationTask(
            root,
            visible=visible_apps,
            demo_mode=demo_mode,
            adaptive_mode=adaptive_mode,
        )
    raise ValueError(f"unknown suite: {name}")
