from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .guard import ActionGuard
from .models import ActionCandidate, ActionReceipt, Decision, Observation, Verification
from .policy import DecisionPolicy
from .registry import ExecutorRegistry
from .trace import JsonlTrace
from .verify import VerifierRegistry


@dataclass(frozen=True)
class StepResult:
    decision: Decision
    receipt: ActionReceipt
    verification: Verification


class AgentRuntime:
    def __init__(
        self,
        *,
        policy: DecisionPolicy,
        guard: ActionGuard,
        executors: ExecutorRegistry,
        verifiers: VerifierRegistry | None = None,
        trace: JsonlTrace | None = None,
    ) -> None:
        self.policy = policy
        self.guard = guard
        self.executors = executors
        self.verifiers = verifiers or VerifierRegistry()
        self.trace = trace or JsonlTrace()

    def step(self, observation: Observation, candidates: Sequence[ActionCandidate]) -> StepResult:
        self.trace.append("observation", observation.to_dict())
        self.trace.append("candidates", {"items": [candidate.to_dict() for candidate in candidates]})
        decision = self.policy.choose(observation, candidates)
        self.trace.append("decision", decision.to_dict())
        candidate = self.guard.approve(observation, decision, candidates)
        receipt = self.executors.execute(candidate, observation.observation_id, decision.decision_id)
        self.trace.append("receipt", receipt.to_dict())
        verification = self.verifiers.verify(candidate, receipt)
        self.trace.append("verification", verification.to_dict())
        return StepResult(decision, receipt, verification)
