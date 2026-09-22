import pytest

from cua_jev.errors import GuardRejected
from cua_jev.guard import ActionGuard
from cua_jev.models import ActionCandidate, Channel, Decision, Observation, Risk


def decision(obs, candidate):
    return Decision(obs.observation_id, candidate.id, {candidate.id: 1.0}, 1.0, "test", 0)


def test_guard_rejects_path_outside_root(tmp_path):
    obs = Observation("test", "read", {})
    candidate = ActionCandidate(
        "read", Channel.API, "filesystem.read_text", "read", {"path": str(tmp_path.parent / "other")}
    )
    with pytest.raises(GuardRejected, match="outside allowed roots"):
        ActionGuard(allowed_roots=[tmp_path]).approve(obs, decision(obs, candidate), [candidate])


def test_guard_consumes_observation_once(tmp_path):
    path = tmp_path / "a.txt"
    candidate = ActionCandidate("read", Channel.API, "filesystem.read_text", "read", {"path": str(path)})
    obs = Observation("test", "read", {})
    guard = ActionGuard(allowed_roots=[tmp_path])
    guard.approve(obs, decision(obs, candidate), [candidate])
    with pytest.raises(GuardRejected, match="already consumed"):
        guard.approve(obs, decision(obs, candidate), [candidate])


def test_guard_blocks_write_by_default(tmp_path):
    candidate = ActionCandidate(
        "write",
        Channel.API,
        "filesystem.write_text",
        "write",
        {"path": str(tmp_path / "a")},
        Risk.LOCAL_WRITE,
    )
    obs = Observation("test", "write", {})
    with pytest.raises(GuardRejected, match="writes are disabled"):
        ActionGuard(allowed_roots=[tmp_path]).approve(obs, decision(obs, candidate), [candidate])


def test_guard_requires_deterministic_precondition_evaluator(tmp_path):
    candidate = ActionCandidate(
        "read",
        Channel.API,
        "filesystem.read_text",
        "read",
        {"path": str(tmp_path / "a")},
        preconditions=("file_exists",),
    )
    obs = Observation("test", "read", {})
    with pytest.raises(GuardRejected, match="unchecked preconditions"):
        ActionGuard(allowed_roots=[tmp_path]).approve(obs, decision(obs, candidate), [candidate])


def test_guard_checks_nested_mcp_paths(tmp_path):
    candidate = ActionCandidate(
        "mcp",
        Channel.MCP,
        "mcp.call_tool",
        "read",
        {"arguments": {"path": str(tmp_path.parent / "outside.txt")}},
    )
    obs = Observation("test", "read", {})
    with pytest.raises(GuardRejected, match="outside allowed roots"):
        ActionGuard(allowed_roots=[tmp_path]).approve(obs, decision(obs, candidate), [candidate])
