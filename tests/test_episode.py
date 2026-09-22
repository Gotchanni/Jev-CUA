from cua_jev.episode import EpisodeConfig, EpisodeRunner, EpisodeStatus, Evaluation
from cua_jev.executors import ControlExecutor, FileSystemExecutor
from cua_jev.guard import ActionGuard
from cua_jev.models import ActionCandidate, Channel, Observation
from cua_jev.policy import RulePolicy
from cua_jev.registry import ExecutorRegistry
from cua_jev.runtime import AgentRuntime
from cua_jev.sandbox import FileOrganizationTask, sandbox_mcp_executor


def runner(tmp_path):
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

    return EpisodeRunner(runtime_factory, EpisodeConfig(max_steps=5))


def test_episode_runs_closed_loop_to_independent_success(tmp_path):
    result = runner(tmp_path).run(FileOrganizationTask(tmp_path))
    assert result.status == EpisodeStatus.SUCCESS
    assert [step.decision.candidate_id for step in result.steps] == [
        "mcp_copy_inventory",
        "mcp_copy_sales",
        "mcp_write_manifest",
        "done",
    ]
    assert result.channel_counts == {"mcp": 3, "control": 1}


def test_episode_reset_makes_repeated_runs_reproducible(tmp_path):
    task = FileOrganizationTask(tmp_path)
    assert runner(tmp_path).run(task).success
    assert runner(tmp_path).run(task).success


class StagnantTask:
    name = "stagnant"

    def reset(self):
        pass

    def observe(self, history):
        return Observation("wait", "wait", {"unchanged": True})

    def candidates(self, observation, history):
        return [ActionCandidate("wait", Channel.CONTROL, "control.wait", "wait")]

    def evaluate(self, observation, candidate, receipt, verification):
        return Evaluation(False, False, "still_waiting")


def test_episode_detects_repeated_unchanged_action(tmp_path):
    result = runner(tmp_path).run(StagnantTask())
    assert result.status == EpisodeStatus.STUCK
    assert len(result.steps) == 3
