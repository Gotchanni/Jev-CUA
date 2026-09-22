from __future__ import annotations

from ..models import ActionCandidate, ActionReceipt
from .common import execute_with_receipt


class ControlExecutor:
    """Side-effect-free episode control actions interpreted by task evaluators."""

    capabilities = {
        "control.wait",
        "control.reobserve",
        "control.done",
        "control.fallback",
        "control.abort",
        "control.request_help",
    }

    def __call__(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        def operation() -> dict:
            if candidate.capability not in self.capabilities:
                raise ValueError(f"unsupported control capability: {candidate.capability}")
            return {"control": candidate.capability.removeprefix("control."), **candidate.arguments}

        return execute_with_receipt(candidate, observation_id, decision_id, operation)
