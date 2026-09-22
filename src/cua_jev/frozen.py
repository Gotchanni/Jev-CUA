from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FrozenTaskSpec:
    name: str
    application: str
    description: str
    capability_packs: tuple[str, ...]
    reset: dict[str, Any]
    success: dict[str, Any]
    max_steps: int
    source_path: Path
    digest: str


def load_frozen_task(path: str | Path) -> FrozenTaskSpec:
    source = Path(path)
    raw = source.read_bytes()
    data = json.loads(raw)
    required = {"name", "application", "description", "capability_packs", "reset", "success", "max_steps"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"frozen task missing fields: {sorted(missing)}")
    if data["max_steps"] < 1:
        raise ValueError("max_steps must be positive")
    return FrozenTaskSpec(
        name=data["name"],
        application=data["application"],
        description=data["description"],
        capability_packs=tuple(data["capability_packs"]),
        reset=data["reset"],
        success=data["success"],
        max_steps=data["max_steps"],
        source_path=source.resolve(),
        digest=hashlib.sha256(raw).hexdigest(),
    )


def builtin_task_specs() -> tuple[FrozenTaskSpec, ...]:
    root = Path(__file__).with_name("frozen_tasks")
    return tuple(load_frozen_task(path) for path in sorted(root.glob("*.json")))
