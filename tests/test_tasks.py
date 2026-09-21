import json

from cua_jev.tasks import load_task


def test_task_substitution_preserves_windows_paths(tmp_path):
    task_path = tmp_path / "task.json"
    task_path.write_text(
        json.dumps(
            {
                "name": "windows",
                "description": "test",
                "subgoal": "read",
                "state": {"path": "${PATH}"},
                "candidates": [
                    {
                        "id": "read",
                        "channel": "api",
                        "capability": "filesystem.read_text",
                        "description": "read",
                        "arguments": {"path": "${PATH}"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    windows_path = r"C:\Users\example\report.txt"
    task = load_task(task_path, {"PATH": windows_path})
    assert task.observation.state["path"] == windows_path
    assert task.candidates[0].arguments["path"] == windows_path
