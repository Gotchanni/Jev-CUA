import pytest

from cua_jev.observers import ObserverRegistry


def test_observer_registry_namespaces_failures():
    registry = ObserverRegistry()
    registry.register("files", lambda: {"count": 2})
    registry.register("optional", lambda: 1 / 0)
    observation = registry.observe(task="task", subgoal="observe", required=["files"])
    assert observation.state["files"] == {"count": 2}
    assert observation.state["observer_failures"] == [{"observer": "optional", "error": "ZeroDivisionError"}]


def test_required_observer_failure_aborts():
    registry = ObserverRegistry()
    registry.register("required", lambda: 1 / 0)
    with pytest.raises(RuntimeError, match="required observers failed"):
        registry.observe(task="task", subgoal="observe", required=["required"])
