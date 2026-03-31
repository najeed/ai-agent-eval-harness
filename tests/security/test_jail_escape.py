import pytest
from flask import Flask
from eval_runner.console.routes import core_bp
from eval_runner import config
import json

@pytest.fixture
def app(monkeypatch, tmp_path):
    app = Flask(__name__)
    app.register_blueprint(core_bp)
    
    # Configure a dummy project root for testing
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "sample_agent" / "loan_agent_demo").mkdir(parents=True)
    
    monkeypatch.setattr(config, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(config, "DASHBOARD_API_KEY", "secure-test-key")
    
    return app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def auth_headers():
    return {"X-AES-API-KEY": "secure-test-key"}

def test_jail_escape_traversal_blocked(client, auth_headers):
    """Verify that path traversal in demo/execute is blocked."""
    payload = {
        "command": "cat ../../../eval_runner/config.py"
    }
    
    resp = client.post("/api/demo/execute", json=payload, headers=auth_headers)
    
    # Should be 403 Forbidden due to path traversal detection
    assert resp.status_code == 403
    assert "Access outside demo jail denied" in resp.get_json()["error"]

def test_jail_escape_unauthorized_file_blocked(client, auth_headers):
    """Verify that accessing non-whitelisted files in demo jail is blocked if they look like paths."""
    payload = {
        "command": "cat secret.txt"
    }
    # secret.txt is in the folder but not in the whitelist
    
    resp = client.post("/api/demo/execute", json=payload, headers=auth_headers)
    
    # Should be 403 Forbidden
    assert resp.status_code == 403
    assert "Access outside demo jail denied" in resp.get_json()["error"]

def test_jail_escape_legitimate_command_allowed(client, auth_headers):
    """Verify that legitimate whitelisted commands are allowed."""
    payload = {
        "command": "cat loan_agent.py"
    }
    
    # We need the file to exist for subprocess to not fail with 'not found' 
    # but the path check happens BEFORE execution.
    
    resp = client.post("/api/demo/execute", json=payload, headers=auth_headers)
    
    # Should NOT be 403 (might be 500 if file doesn't exist, but we check for 403 specifically)
    assert resp.status_code != 403
