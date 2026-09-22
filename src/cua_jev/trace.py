from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


class JsonlTrace:
    def __init__(self, path: str | Path | None = None, *, run_id: str | None = None) -> None:
        self.path = Path(path) if path else None
        self.run_id = run_id or uuid.uuid4().hex
        self.events: list[dict[str, Any]] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, kind: str, payload: dict[str, Any]) -> None:
        event = {
            "run_id": self.run_id,
            "sequence": len(self.events),
            "timestamp": time.time(),
            "kind": kind,
            "payload": payload,
        }
        self.events.append(event)
        if self.path:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
