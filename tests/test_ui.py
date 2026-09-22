import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from cua_jev.ui.app import create_app
from cua_jev.ui.manager import RunManager


def test_console_bootstrap_and_local_security(tmp_path: Path) -> None:
    with TestClient(create_app(root=tmp_path, data=tmp_path / "runs")) as client:
        bootstrap = client.get("/api/bootstrap").json()
        assert set(bootstrap["tasks"]) == {"edge", "excel", "vscode", "explorer"}
        assert "PyAutoGUI · Edge" in bootstrap["tasks"]["edge"]["gui_routes"]
        assert "Playwright DOM" in bootstrap["tasks"]["edge"]["hybrid_routes"]
        assert bootstrap["tasks"]["edge"]["hybrid_channels"] == ["gui", "script"]
        assert bootstrap["tasks"]["edge"]["benchmark_version"] == "long-horizon-v2"
        assert "DOM Script" in bootstrap["tasks"]["edge"]["evaluation_routes"]
        assert client.post("/api/runs", json={"task": "bad", "policy": "rule"}).status_code == 403
        response = client.post(
            "/api/runs",
            json={"task": "bad", "policy": "rule"},
            headers={"X-CUA-JEV-CSRF": bootstrap["csrf"]},
        )
        assert response.status_code == 400


def test_external_codex_baseline_uses_shared_benchmark_contract(tmp_path: Path) -> None:
    with TestClient(create_app(root=tmp_path, data=tmp_path / "runs")) as client:
        bootstrap = client.get("/api/bootstrap").json()
        payload = {
            "agent": "codex_computer_use",
            "task": "edge",
            "action_space": "gui_only",
            "success": True,
            "duration_ms": 42000,
            "actions": 8,
            "channels": {"gui": 8},
            "verifier": "shared_terminal_verifier",
        }
        assert client.post("/api/baselines", json=payload).status_code == 403
        response = client.post(
            "/api/baselines",
            json=payload,
            headers={"X-CUA-JEV-CSRF": bootstrap["csrf"]},
        )
        assert response.status_code == 200
        assert response.json()["metrics"]["gui_ratio"] == 1.0
        rows = client.get("/api/benchmarks?task=edge").json()["rows"]
        assert rows == [
            {
                "agent": "codex_computer_use",
                "action_space": "gui_only",
                "samples": 1,
                "successful_samples": 1,
                "success_rate": 1.0,
                "median_wall_time_ms": 42000.0,
                "mean_wall_time_ms": 42000.0,
                "median_decision_time_ms": None,
                "median_execution_time_ms": None,
                "mean_actions": 8,
                "mean_gui_ratio": 1.0,
                "mean_route_diversity": 1,
            }
        ]


def test_console_serves_brand_assets(tmp_path: Path) -> None:
    demos = tmp_path / "artifacts" / "demos"
    demos.mkdir(parents=True)
    (demos / "edge-hybrid.mp4").write_bytes(b"demo")
    with TestClient(create_app(root=tmp_path, data=tmp_path / "runs")) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "REAL LAB" in page.text
        assert "qiushi-eagle" not in page.text
        assert client.get("/static/logo-mark.svg").status_code == 200
        assert client.get("/static/qiushi-eagle.svg").status_code == 404
        assert client.get("/api/bootstrap").json()["demos"]["edge"] == {
            "hybrid": "/demos/edge-hybrid.mp4"
        }
        assert client.get("/demos/edge-hybrid.mp4").content == b"demo"


def test_metrics_use_full_trace_while_detail_is_bounded(tmp_path: Path) -> None:
    manager = RunManager(tmp_path, tmp_path / "runs")
    run_id = "long-trace"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir()
    trace_base = run_dir / "trace.jsonl"
    events = [
        {"timestamp": index, "kind": "receipt", "payload": {"channel": "gui", "duration_ms": 1}}
        for index in range(115)
    ]
    events.extend(
        {"timestamp": 200 + index, "kind": "decision", "payload": {"latency_ms": 1}}
        for index in range(115)
    )
    events.append(
        {
            "timestamp": 400,
            "kind": "episode",
            "payload": {"duration_ms": 230, "status": "success"},
        }
    )
    trace_base.with_name("trace-edge.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events),
        encoding="utf-8",
    )
    record = {
        "id": run_id,
        "task": "edge",
        "benchmark_version": "long-horizon-v2",
        "policy": "jev",
        "execution_profile": "adaptive",
        "status": "completed",
        "created_at": 1,
        "updated_at": 2,
        "trace_base": str(trace_base),
    }
    (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")

    detail = manager.detail(run_id)

    assert len(detail["events"]) == 100
    assert detail["event_counts"]["decision"] == 115
    assert detail["metrics"]["actions"] == 115
