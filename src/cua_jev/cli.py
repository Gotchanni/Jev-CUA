from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from .demo import filesystem_routing_demo
from .doctor import doctor
from .policy import JevPolicy, RulePolicy


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        print(json.dumps(doctor(), indent=2, ensure_ascii=False))
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
