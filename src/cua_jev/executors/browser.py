from __future__ import annotations

from typing import Any

from ..errors import CapabilityUnavailable
from ..models import ActionCandidate, ActionReceipt
from .common import execute_with_receipt


class EdgeDomExecutor:
    """Playwright-over-CDP adapter for an explicitly launched Edge instance."""

    def __init__(self, cdp_url: str = "http://127.0.0.1:9222") -> None:
        self.cdp_url = cdp_url

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict[str, Any]:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise CapabilityUnavailable(
                    "install cua-jev[browser] and playwright chromium support"
                ) from None
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self.cdp_url)
                pages = [page for context in browser.contexts for page in context.pages]
                if not pages:
                    raise RuntimeError("no Edge page is connected")
                page_index = int(candidate.arguments.get("page_index", -1))
                page = pages[page_index]
                if candidate.capability == "edge.dom_snapshot":
                    elements = page.locator("a,button,input,select,textarea,[role]").evaluate_all(
                        """els => els.slice(0, 300).map((e, i) => ({
                          ref: i, tag: e.tagName.toLowerCase(), role: e.getAttribute('role'),
                          text: (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0, 300),
                          name: e.getAttribute('name'), type: e.getAttribute('type'),
                          disabled: !!e.disabled
                        }))"""
                    )
                    return {"url": page.url, "title": page.title(), "elements": elements}
                if candidate.capability == "edge.navigate":
                    page.goto(candidate.arguments["url"], wait_until="domcontentloaded")
                    return {"url": page.url, "title": page.title()}
                locator = page.locator(candidate.arguments["selector"])
                if candidate.capability == "edge.click":
                    locator.click(timeout=float(candidate.arguments.get("timeout_ms", 10_000)))
                    return {"url": page.url, "selector": candidate.arguments["selector"]}
                if candidate.capability == "edge.fill":
                    locator.fill(candidate.arguments["text"])
                    return {"url": page.url, "selector": candidate.arguments["selector"]}
                raise ValueError(f"unsupported Edge capability: {candidate.capability}")

        return execute_with_receipt(candidate, observation_id, decision_id, operation)
