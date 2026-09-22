from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .models import ActionCandidate, Observation
from .runtime import StepResult


class CapabilityPack(Protocol):
    name: str

    def candidates(
        self, observation: Observation, history: Sequence[StepResult]
    ) -> Sequence[ActionCandidate]: ...


@dataclass(frozen=True)
class FunctionCapabilityPack:
    name: str
    builder: Callable[[Observation, Sequence[StepResult]], Sequence[ActionCandidate]]

    def candidates(
        self, observation: Observation, history: Sequence[StepResult]
    ) -> Sequence[ActionCandidate]:
        return self.builder(observation, history)


class CapabilityRegistry:
    """Builds a deterministic legal frontier from registered capability packs."""

    def __init__(self) -> None:
        self._packs: dict[str, CapabilityPack] = {}

    def register(self, pack: CapabilityPack) -> None:
        if not pack.name or pack.name in self._packs:
            raise ValueError("capability pack names must be unique and nonempty")
        self._packs[pack.name] = pack

    def build(
        self,
        observation: Observation,
        history: Sequence[StepResult],
        *,
        enabled: Sequence[str] | None = None,
    ) -> tuple[ActionCandidate, ...]:
        names = tuple(enabled) if enabled is not None else tuple(self._packs)
        candidates = [
            candidate for name in names for candidate in self._packs[name].candidates(observation, history)
        ]
        ids = [candidate.id for candidate in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("capability packs produced duplicate candidate ids")
        return tuple(candidates)
