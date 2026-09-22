from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .episode import EpisodeResult, EpisodeRunner, TaskEnvironment


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


@dataclass(frozen=True)
class ExperimentResult:
    task: str
    episodes: tuple[EpisodeResult, ...]

    def summary(self) -> dict:
        successes = sum(result.success for result in self.episodes)
        total = len(self.episodes)
        low, high = wilson_interval(successes, total)
        statuses = Counter(str(result.status) for result in self.episodes)
        channels = Counter(
            channel
            for result in self.episodes
            for channel, count in result.channel_counts.items()
            for _ in range(count)
        )
        return {
            "task": self.task,
            "episodes": total,
            "successes": successes,
            "success_rate": successes / total if total else 0,
            "wilson_95": [low, high],
            "statuses": dict(statuses),
            "channels": dict(channels),
            "mean_duration_ms": (sum(result.duration_ms for result in self.episodes) / total if total else 0),
        }


class ExperimentRunner:
    def __init__(self, runner: EpisodeRunner) -> None:
        self.runner = runner

    def run(
        self,
        environment_factory: Callable[[], TaskEnvironment],
        episodes: int,
        *,
        output: str | Path | None = None,
    ) -> ExperimentResult:
        if episodes < 1:
            raise ValueError("episodes must be positive")
        results = tuple(self.runner.run(environment_factory()) for _ in range(episodes))
        experiment = ExperimentResult(results[0].task, results)
        if output:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(experiment.summary(), indent=2), encoding="utf-8")
        return experiment
