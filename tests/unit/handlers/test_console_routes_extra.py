import pytest
import json
from pathlib import Path
from flask import Flask
from eval_runner.console.routes import core_bp
from eval_runner import config

@pytest.fixture
def app(tmp_path, monkeypatch):
    """Fixture for local Flask app with isolated routes."""
    app = Flask(__name__)
    app.register_blueprint(core_bp)
    
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    (tmp_path / "runs").mkdir()
    
    return app

@pytest.fixture
def client(app):
    return app.test_client()

def test_list_runs_with_query(client, tmp_path):
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
    resp = client.get("/api/runs?q=alpha")
    data = resp.get_json()
    assert len(data["runs"]) == 1
    assert data["runs"][0]["run_id"] == "run-alpha"
    
    # Search for nothing
    resp = client.get("/api/runs?q=xyz")
    data = resp.get_json()
    assert len(data["runs"]) == 0

def test_get_debugger_state_invalid_run(client):
    """Verifies 404 error handling for missing trace lookups."""
    resp = client.get("/api/debugger/state?run_id=invalid-id")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "Trace file not found" in data["message"]

def test_list_scenarios_filtering(client, monkeypatch, tmp_path):
    """Verifies Console API scenarios filtering."""
    # Mock catalog search to avoid full indexing
    from eval_runner.catalog import ScenarioCatalog
    def mock_search(self, query=None, industry=None, difficulty=None):
        return [{"id": "s1", "industry": industry or "any"}]
    
    monkeypatch.setattr(ScenarioCatalog, "load_index", lambda x: None)
    monkeypatch.setattr(ScenarioCatalog, "search", mock_search)
    
    resp = client.get("/api/scenarios?industry=telecom")
    data = resp.get_json()
    assert data["scenarios"][0]["industry"] == "telecom"

def test_ping_endpoint(client):
    """Verifies basic system visibility check."""
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "pong"
