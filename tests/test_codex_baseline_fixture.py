import json
import subprocess
import sys
from pathlib import Path


def test_external_fixture_only_prepares_and_verifies() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "codex_baseline_fixture.py"
    result = subprocess.run(
        [sys.executable, str(script), "explorer"],
        input="verify\nstop\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[0]["event"] == "ready"
    assert events[1] == {
        "event": "verification",
        "success": False,
        "terminal": True,
        "reason": "archive_content_mismatch",
    }
    assert not Path(events[0]["workspace"]).exists()
