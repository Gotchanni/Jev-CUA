from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .errors import PolicyError
from .models import ActionCandidate, Decision, Observation
from .policy import DecisionPolicy


def decision_request_hash(observation: Observation, candidates: list[ActionCandidate]) -> str:
    payload = {
        "task": observation.task,
        "subgoal": observation.subgoal,
        "source": observation.source,
        "state": observation.state,
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


class CachedDecisionPolicy:
    """Content-addressed record/replay wrapper for any decision policy."""

    def __init__(
        self, policy: DecisionPolicy | None, cache_dir: str | Path, *, cache_only: bool = False
    ) -> None:
        self.policy = policy
        self.cache_dir = Path(cache_dir)
        self.cache_only = cache_only
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"calls": 0, "cache_hits": 0}
        self.last_exchange: dict = {}

    def choose(self, observation: Observation, candidates) -> Decision:
        items = list(candidates)
        key = decision_request_hash(observation, items)
        path = self.cache_dir / f"{key}.json"
        self.stats["calls"] += 1
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.stats["cache_hits"] += 1
            self.last_exchange = {"cache_hit": True, "request_hash": key}
            return Decision(
                observation_id=observation.observation_id,
                candidate_id=data["candidate_id"],
                probabilities=data["probabilities"],
                confidence=data["confidence"],
                model=data["model"],
                latency_ms=0.0,
            )
        if self.cache_only or self.policy is None:
            raise PolicyError(f"no cached decision for request {key}")
        decision = self.policy.choose(observation, items)
        self.last_exchange = {
            "cache_hit": False,
            "request_hash": key,
            "upstream": getattr(self.policy, "last_exchange", None),
        }
        record = decision.to_dict()
        record["request_hash"] = key
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
        return decision

    def close(self) -> None:
        close = getattr(self.policy, "close", None)
        if close:
            close()
