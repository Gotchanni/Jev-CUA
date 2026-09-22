from cua_jev.episode import EpisodeConfig, EpisodeRunner
from cua_jev.executors import ControlExecutor, FileSystemExecutor
from cua_jev.experiment import ExperimentRunner, wilson_interval
from cua_jev.guard import ActionGuard
from cua_jev.models import Channel
from cua_jev.policy import RulePolicy
from cua_jev.registry import ExecutorRegistry
from cua_jev.runtime import AgentRuntime
from cua_jev.sandbox import FileOrganizationTask, sandbox_mcp_executor


def test_experiment_preserves_all_episode_results(tmp_path):
    def runtime_factory():
        executors = ExecutorRegistry()
        executors.register(Channel.API, FileSystemExecutor())
        executors.register(Channel.MCP, sandbox_mcp_executor())
        executors.register(Channel.CONTROL, ControlExecutor())
        return AgentRuntime(
            policy=RulePolicy(),
            guard=ActionGuard(allowed_roots=[tmp_path], allow_writes=True),
            executors=executors,
        )

    experiment = ExperimentRunner(EpisodeRunner(runtime_factory, EpisodeConfig(max_steps=5))).run(
        lambda: FileOrganizationTask(tmp_path), 3, output=tmp_path / "summary.json"
    )
    summary = experiment.summary()
    assert summary["episodes"] == summary["successes"] == 3
    assert summary["channels"] == {"mcp": 9, "control": 3}
    low, high = wilson_interval(3, 3)
    assert 0 < low < high == 1
