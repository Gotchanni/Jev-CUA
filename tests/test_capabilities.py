import pytest

from cua_jev.capabilities import CapabilityRegistry, FunctionCapabilityPack
from cua_jev.models import ActionCandidate, Channel, Observation


def test_capability_registry_builds_dynamic_frontier():
    registry = CapabilityRegistry()
    registry.register(
        FunctionCapabilityPack(
            "files",
            lambda observation, history: [
                ActionCandidate(
                    "read", Channel.API, "filesystem.read_text", f"Read {observation.state['path']}"
                )
            ],
        )
    )
    result = registry.build(Observation("task", "read", {"path": "report.txt"}), [])
    assert result[0].description == "Read report.txt"


def test_capability_registry_rejects_duplicate_candidate_ids():
    registry = CapabilityRegistry()
    for name in ("one", "two"):
        registry.register(
            FunctionCapabilityPack(
                name,
                lambda observation, history: [
                    ActionCandidate("same", Channel.CONTROL, "control.wait", "wait")
                ],
            )
        )
    with pytest.raises(ValueError, match="duplicate"):
        registry.build(Observation("task", "wait", {}), [])
