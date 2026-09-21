from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..models import ActionCandidate, ActionReceipt


def execute_with_receipt(
    candidate: ActionCandidate,
    observation_id: str,
    decision_id: str,
    operation: Callable[[], dict[str, Any]],
) -> ActionReceipt:
    started = time.time()
    try:
        output = operation()
        return ActionReceipt(
            observation_id=observation_id,
            decision_id=decision_id,
            candidate_id=candidate.id,
            channel=candidate.channel,
            capability=candidate.capability,
            success=True,
            started_at=started,
            ended_at=time.time(),
            output=output,
        )
    except Exception as exc:  # executor boundaries always become auditable receipts
        return ActionReceipt(
            observation_id=observation_id,
            decision_id=decision_id,
            candidate_id=candidate.id,
            channel=candidate.channel,
            capability=candidate.capability,
            success=False,
            started_at=started,
            ended_at=time.time(),
            error=f"{type(exc).__name__}: {exc}",
        )
