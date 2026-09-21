from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import ActionCandidate, ActionReceipt, Verification

Verifier = Callable[[ActionCandidate, ActionReceipt], Verification]


class VerifierRegistry:
    def __init__(self) -> None:
        self._verifiers: dict[str, Verifier] = {
            "receipt.success": self.receipt_success,
            "file.exists": self.file_exists,
            "file.contains": self.file_contains,
        }

    def register(self, name: str, verifier: Verifier) -> None:
        self._verifiers[name] = verifier

    def verify(self, candidate: ActionCandidate, receipt: ActionReceipt) -> Verification:
        name = candidate.verifier or "receipt.success"
        verifier = self._verifiers.get(name)
        if verifier is None:
            return Verification(False, name, {"error": "unknown verifier"})
        return verifier(candidate, receipt)

    @staticmethod
    def receipt_success(candidate: ActionCandidate, receipt: ActionReceipt) -> Verification:
        return Verification(receipt.success, "receipt.success", {"error": receipt.error})

    @staticmethod
    def file_exists(candidate: ActionCandidate, receipt: ActionReceipt) -> Verification:
        value = candidate.expected.get("path") or candidate.arguments.get("destination_path")
        exists = isinstance(value, str) and Path(value).exists()
        return Verification(bool(exists), "file.exists", {"path": value, "exists": bool(exists)})

    @staticmethod
    def file_contains(candidate: ActionCandidate, receipt: ActionReceipt) -> Verification:
        path_value = candidate.expected.get("path")
        needle: Any = candidate.expected.get("contains")
        if not isinstance(path_value, str) or not isinstance(needle, str) or not Path(path_value).is_file():
            return Verification(False, "file.contains", {"path": path_value, "error": "invalid expectation"})
        contains = needle in Path(path_value).read_text(encoding="utf-8")
        return Verification(contains, "file.contains", {"path": path_value, "contains": contains})
