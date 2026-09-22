from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from cua_jev.ui.app import create_app


def test_console_bootstrap_and_local_security(tmp_path: Path) -> None:
    with TestClient(create_app(root=tmp_path, data=tmp_path / "runs")) as client:
        bootstrap = client.get("/api/bootstrap").json()
        assert set(bootstrap["tasks"]) == {"edge", "excel", "vscode", "explorer"}
        assert client.post("/api/runs", json={"task": "bad", "policy": "rule"}).status_code == 403
        response = client.post(
            "/api/runs",
            json={"task": "bad", "policy": "rule"},
            headers={"X-CUA-JEV-CSRF": bootstrap["csrf"]},
        )
        assert response.status_code == 400


def test_console_serves_brand_assets(tmp_path: Path) -> None:
    with TestClient(create_app(root=tmp_path, data=tmp_path / "runs")) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "ZJU REAL Lab" in page.text
        assert client.get("/static/logo-mark.svg").status_code == 200
