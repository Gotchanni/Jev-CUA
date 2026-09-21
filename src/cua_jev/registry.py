from __future__ import annotations

from collections.abc import Callable

from .errors import CapabilityUnavailable
from .models import ActionCandidate, ActionReceipt, Channel

Executor = Callable[[ActionCandidate, str, str], ActionReceipt]


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[Channel, Executor] = {}

    def register(self, channel: Channel, executor: Executor) -> None:
        self._executors[channel] = executor

    def execute(self, candidate: ActionCandidate, observation_id: str, decision_id: str) -> ActionReceipt:
        executor = self._executors.get(candidate.channel)
        if executor is None:
            raise CapabilityUnavailable(f"no executor registered for channel {candidate.channel}")
        return executor(candidate, observation_id, decision_id)

    @property
    def channels(self) -> tuple[Channel, ...]:
        return tuple(self._executors)
