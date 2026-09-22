from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .models import Observation
from .runtime import StepResult

Observer = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class ObserverFailure:
    observer: str
    error: str


class ObserverRegistry:
    """Combines structured sources without flattening their namespaces."""

    def __init__(self) -> None:
        self._observers: dict[str, Observer] = {}

    def register(self, name: str, observer: Observer) -> None:
        if not name or name in self._observers:
            raise ValueError("observer names must be unique and nonempty")
        self._observers[name] = observer

    def observe(
        self,
        *,
        task: str,
        subgoal: str,
        history: Sequence[StepResult] = (),
        required: Sequence[str] = (),
    ) -> Observation:
        state: dict[str, Any] = {}
        failures: list[dict[str, str]] = []
        for name, observer in self._observers.items():
            try:
                value = observer()
                if not isinstance(value, dict):
                    raise TypeError("observer must return a JSON object")
                state[name] = value
            except Exception as exc:
                failures.append({"observer": name, "error": type(exc).__name__})
        missing = sorted(set(required) - set(state))
        if missing:
            raise RuntimeError(f"required observers failed: {missing}")
        state["observer_failures"] = failures
        state["history_length"] = len(history)
        return Observation(task, subgoal, state, source="observer-registry")
