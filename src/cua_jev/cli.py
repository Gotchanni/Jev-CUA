from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from .demo import filesystem_routing_demo
from .doctor import doctor
from .episode import EpisodeConfig, EpisodeRunner
from .executors import ControlExecutor, FileSystemExecutor
from .experiment import ExperimentRunner
from .frozen import builtin_task_specs
from .guard import ActionGuard
from .models import Channel
from .policy import JevPolicy, RulePolicy
from .registry import ExecutorRegistry
from .runtime import AgentRuntime
from .sandbox import FileOrganizationTask, sandbox_mcp_executor
from .trace import JsonlTrace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cua-jev", description="Typed hybrid action routing with Jev")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Report optional Windows capability availability")
    demo = sub.add_parser("demo", help="Run the reproducible multi-channel routing demo")
    demo.add_argument("--policy", choices=("rule", "jev"), default="rule")
    demo.add_argument("--workspace", default="demo-workspace")
    demo.add_argument("--trace", default="runs/demo.jsonl")
    benchmark = sub.add_parser("benchmark", help="Repeat the frozen routing task and summarize outcomes")
    benchmark.add_argument("--policy", choices=("rule", "jev"), default="rule")
    benchmark.add_argument("--episodes", type=int, default=10)
    benchmark.add_argument("--workspace", default="demo-workspace")
    benchmark.add_argument("--trace", default="runs/benchmark.jsonl")
    sub.add_parser("jev-smoke", help="Make one read-only Jev decision without executing an action")
    sub.add_parser("tasks", help="List frozen representative task contracts")
    episode = sub.add_parser("episode-demo", help="Run the closed-loop sandbox episode")
    episode.add_argument("--policy", choices=("rule", "jev"), default="rule")
    episode.add_argument("--workspace", default="demo-workspace/episode")
    episode.add_argument("--trace", default="runs/episode.jsonl")
    experiment = sub.add_parser("experiment", help="Run repeated closed-loop sandbox episodes")
    experiment.add_argument("--policy", choices=("rule", "jev"), default="rule")
    experiment.add_argument("--episodes", type=int, default=10)
    experiment.add_argument("--workspace", default="demo-workspace/experiment")
    experiment.add_argument("--output", default="runs/experiment-summary.json")
    experiment.add_argument("--trace", default="runs/experiment.jsonl")
    return parser


def _episode_runner(policy_name: str, workspace: Path, trace: Path) -> EpisodeRunner:
    def runtime_factory() -> AgentRuntime:
        executors = ExecutorRegistry()
        executors.register(Channel.API, FileSystemExecutor())
        executors.register(Channel.MCP, sandbox_mcp_executor())
        executors.register(Channel.CONTROL, ControlExecutor())
        policy = JevPolicy() if policy_name == "jev" else RulePolicy()
        return AgentRuntime(
            policy=policy,
            guard=ActionGuard(allowed_roots=[workspace], allow_writes=True),
            executors=executors,
            trace=JsonlTrace(trace),
        )

    return EpisodeRunner(runtime_factory, EpisodeConfig(max_steps=5))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        print(json.dumps(doctor(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "tasks":
        print(
            json.dumps(
                [
                    {
                        "name": task.name,
                        "application": task.application,
                        "capability_packs": task.capability_packs,
                        "max_steps": task.max_steps,
                        "digest": task.digest,
                    }
                    for task in builtin_task_specs()
                ],
                indent=2,
            )
        )
        return 0
    if args.command == "jev-smoke":
        from .models import ActionCandidate, Channel, Observation

        policy = JevPolicy()
        try:
            decision = policy.choose(
                Observation("Connectivity test", "Select the direct health-check action", {"test": True}),
                [
                    ActionCandidate("health_check", Channel.CONTROL, "control.noop", "Complete health check"),
                    ActionCandidate("reobserve", Channel.CONTROL, "control.reobserve", "Request more state"),
                ],
            )
        finally:
            policy.close()
        print(json.dumps(decision.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.command in {"episode-demo", "experiment"}:
        workspace = Path(args.workspace).resolve()
        runner = _episode_runner(args.policy, workspace, Path(args.trace))
        if args.command == "episode-demo":
            result = runner.run(FileOrganizationTask(workspace))
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0 if result.success else 1
        experiment = ExperimentRunner(runner).run(
            lambda: FileOrganizationTask(workspace), args.episodes, output=args.output
        )
        summary = experiment.summary()
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if summary["successes"] == args.episodes else 1
    policy = JevPolicy() if args.policy == "jev" else RulePolicy()
    try:
        if args.command == "benchmark":
            if args.episodes < 1:
                raise SystemExit("--episodes must be positive")
            choices: Counter[str] = Counter()
            successes = 0
            latencies = []
            started = time.perf_counter()
            for _ in range(args.episodes):
                result = filesystem_routing_demo(policy, Path(args.workspace), Path(args.trace))
                choices[result.decision.candidate_id] += 1
                successes += int(result.verification.passed)
                latencies.append(result.decision.latency_ms)
            summary = {
                "policy": args.policy,
                "episodes": args.episodes,
                "verified": successes,
                "success_rate": successes / args.episodes,
                "choices": dict(choices),
                "mean_decision_latency_ms": sum(latencies) / len(latencies),
                "wall_ms": (time.perf_counter() - started) * 1000,
            }
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return 0 if successes == args.episodes else 1
        result = filesystem_routing_demo(policy, Path(args.workspace), Path(args.trace))
    finally:
        close = getattr(policy, "close", None)
        if close:
            close()
    print(
        json.dumps(
            {
                "decision": result.decision.to_dict(),
                "receipt": result.receipt.to_dict(),
                "verification": result.verification.to_dict(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if result.verification.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
