from cua_jev.executors import FileSystemExecutor
from cua_jev.guard import ActionGuard
from cua_jev.models import ActionCandidate, Channel, Observation
from cua_jev.policy import RulePolicy
from cua_jev.registry import ExecutorRegistry
from cua_jev.runtime import AgentRuntime


def test_runtime_reads_and_verifies_file(tmp_path):
    path = tmp_path / "report.txt"
    path.write_text("hello", encoding="utf-8")
    candidate = ActionCandidate(
        "read",
        Channel.API,
        "filesystem.read_text",
        "Read report",
        {"path": str(path)},
        verifier="receipt.success",
    )
    registry = ExecutorRegistry()
    registry.register(Channel.API, FileSystemExecutor())
    runtime = AgentRuntime(
        policy=RulePolicy(), guard=ActionGuard(allowed_roots=[tmp_path]), executors=registry
    )
    result = runtime.step(Observation("read", "read report", {}), [candidate])
    assert result.receipt.output["text"] == "hello"
    assert result.verification.passed
    assert [event["kind"] for event in runtime.trace.events] == [
        "observation",
        "candidates",
        "decision",
        "commitment",
        "guard",
        "receipt",
        "verification",
    ]
