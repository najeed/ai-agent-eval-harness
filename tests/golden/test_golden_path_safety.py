"""
tests/golden/test_golden_path_safety.py
Golden Verification Corpus: Path Traversal Guard Validation
"""

from unittest.mock import patch

import pytest

from eval_runner.console.app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AEH_STRICT_JAIL", "1")
    with (
        patch("eval_runner.config.DASHBOARD_API_KEY", "test_key"),
        patch("eval_runner.config.SERVICE_API_KEY", "test_key"),
        patch("eval_runner.config.ENABLE_DEMO", True),
    ):
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


def test_golden_mutate_scenario_path_traversal_blocked(client):
    # Attempt to read a file outside PROJECT_ROOT via absolute traversal
    escape_path = "C:/Windows/System32/drivers/etc/hosts"

    resp = client.post(
        "/api/v1/mutate",
        json={"input_path": escape_path, "type": "typo"},
        headers={"X-Api-Key": "test_key"},
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert "Access denied" in data.get("error", "")


def test_golden_mutate_scenario_output_path_traversal_blocked(client):
    escape_output = "C:/Windows/Temp/escape_output.json"

    resp = client.post(
        "/api/v1/mutate",
        json={
            "raw_json": {"id": "test_scen", "tasks": []},
            "type": "typo",
            "output_path": escape_output,
        },
        headers={"X-Api-Key": "test_key"},
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert "Access denied" in data.get("error", "")


def test_golden_spec_to_eval_path_traversal_blocked(client):
    escape_spec = "C:/Windows/System32/drivers/etc/hosts"

    resp = client.post(
        "/api/v1/spec-to-eval",
        json={"input_path": escape_spec},
        headers={"X-Api-Key": "test_key"},
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert "Access denied" in data.get("error", "")
