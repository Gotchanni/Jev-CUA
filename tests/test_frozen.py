from cua_jev.frozen import builtin_task_specs


def test_four_representative_tasks_are_frozen():
    tasks = builtin_task_specs()
    assert {task.application for task in tasks} == {"edge", "excel", "explorer", "vscode"}
    assert all(len(task.digest) == 64 and task.max_steps > 0 for task in tasks)
