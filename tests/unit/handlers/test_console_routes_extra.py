import pytest
import json
from pathlib import Path
from flask import Flask
from eval_runner.console.routes import core_bp
from eval_runner import config

from eval_runner.console.app import create_app

@pytest.fixture
def app(tmp_path, monkeypatch):
    """Fixture for local Flask app with isolated routes."""
    app = create_app()
    app.config["TESTING"] = True
    
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    if not (tmp_path / "runs").exists():
        (tmp_path / "runs").mkdir()
    
    return app

@pytest.fixture
def client(app, monkeypatch):
    api_key = "test-key-123"
    monkeypatch.setattr(config, "DASHBOARD_API_KEY", api_key)
    with app.test_client() as client:
        client.environ_base["HTTP_X_AES_API_KEY"] = api_key
        yield client

@pytest.fixture
def auth_headers():
    return {"X-AES-API-KEY": "test-key-123"}

def test_list_runs_with_query(client, tmp_path, auth_headers):
    """Verifies 'runs' search filter logic in Console API."""
    run_log = tmp_path / "runs" / "run.jsonl"
    events = [
        {"event": "run_start", "run_id": "run-alpha", "scenario": "Scen A", "timestamp": "123"},
        {"event": "run_start", "run_id": "run-beta", "scenario": "Scen B", "timestamp": "456"}
    ]
    with open(run_log, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
            
    # Search for Alpha
    resp = client.get("/api/runs?q=alpha", headers=auth_headers)
    data = resp.get_json()
    assert len(data["runs"]) == 1
    assert data["runs"][0]["run_id"] == "run-alpha"
    
    # Search for nothing
    resp = client.get("/api/runs?q=xyz", headers=auth_headers)
    data = resp.get_json()
    assert len(data["runs"]) == 0

def test_get_debugger_state_invalid_run(client, auth_headers):
    """Verifies 404 error handling for missing trace lookups."""
    resp = client.get("/api/debugger/state?run_id=invalid-id", headers=auth_headers)
    assert resp.status_code == 404
    data = resp.get_json()
    assert "Trace file not found" in data["message"]

def test_list_scenarios_filtering(client, monkeypatch, tmp_path, auth_headers):
    """Verifies Console API scenarios filtering."""
    # Mock catalog search to avoid full indexing
    from eval_runner.catalog import ScenarioCatalog
    def mock_search(self, query=None, industry=None, difficulty=None, limit=50, offset=0):
        return [{"id": "s1", "industry": industry or "any"}]
    
    monkeypatch.setattr(ScenarioCatalog, "load_index", lambda x: None)
    monkeypatch.setattr(ScenarioCatalog, "search", mock_search)
    
    resp = client.get("/api/scenarios?industry=telecom", headers=auth_headers)
    data = resp.get_json()
    assert data["scenarios"][0]["industry"] == "telecom"

def test_ping_endpoint(client):
    """Verifies basic system visibility check."""
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "pong"
