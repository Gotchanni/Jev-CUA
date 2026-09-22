from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from cua_jev.ui.app import create_app


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
        assert "ZJU REAL Lab" in page.text
        assert client.get("/static/logo-mark.svg").status_code == 200
        assert client.get("/api/bootstrap").json()["demos"]["edge"] == {
            "hybrid": "/demos/edge-hybrid.mp4"
        }
        assert client.get("/demos/edge-hybrid.mp4").content == b"demo"
