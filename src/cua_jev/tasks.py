from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ActionCandidate, Channel, Observation, Risk


@dataclass(frozen=True)
class PredefinedTask:
    name: str
    description: str
    observation: Observation
    candidates: tuple[ActionCandidate, ...]


def load_task(path: str | Path, variables: dict[str, str] | None = None) -> PredefinedTask:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))

    def substitute(value: Any) -> Any:
        if isinstance(value, str):
            for name, replacement in (variables or {}).items():
                value = value.replace("${" + name + "}", replacement)
            return value
        if isinstance(value, list):
            return [substitute(item) for item in value]
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        return value

    data = substitute(data)
    observation = Observation(
        task=data["description"],
        subgoal=data["subgoal"],
        state=data.get("state", {}),
        source=f"task:{data['name']}",
    )
    candidates = tuple(
        ActionCandidate(
            id=item["id"],
            channel=Channel(item["channel"]),
            capability=item["capability"],
            description=item["description"],
            arguments=item.get("arguments", {}),
            risk=Risk(item.get("risk", "read_only")),
            preconditions=tuple(item.get("preconditions", [])),
            verifier=item.get("verifier"),
            expected=item.get("expected", {}),
            requires_confirmation=bool(item.get("requires_confirmation", False)),
        )
        for item in data["candidates"]
    )
    return PredefinedTask(data["name"], data["description"], observation, candidates)
