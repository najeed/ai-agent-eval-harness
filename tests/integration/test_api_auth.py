import json
from unittest.mock import patch

import pytest

from eval_runner.console.app import create_app


@pytest.fixture
def client():
    # Force known API Keys by patching the config module directly
    # because these are set at import time from env vars.
    with patch("eval_runner.config.DASHBOARD_API_KEY", "test_dash_key_12345"), \
         patch("eval_runner.config.SERVICE_API_KEY", "test_service_key_67890"):
        
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

def test_evaluate_endpoint_security_no_key(client):
    """Verify that /api/evaluate rejects requests without an API key."""
    # We use a POST request to a protected endpoint
    response = client.post("/api/evaluate", json={"path": "scenarios/test.yaml"})
    # StaticKeyProvider returns 401 Unauthorized if key is missing or invalid
    assert response.status_code == 401

def test_evaluate_endpoint_security_wrong_key(client):
    """Verify that /api/evaluate rejects requests with an invalid API key."""
    headers = {"X-Api-Key": "wrong_key"}
    response = client.post(
        "/api/evaluate",
        json={"path": "scenarios/test.yaml"},
        headers=headers
    )
    assert response.status_code == 401

def test_evaluate_endpoint_security_service_key(client, tmp_path):
    """Verify that /api/evaluate accepts the dedicated SERVICE_API_KEY with valid AES files."""
    # 1. Setup a real physical schema-compliant AES 1.3 scenario file
    scenario_path = tmp_path / "it_test_scenario.json"
    scenario_path.write_text(json.dumps({
        "aes_version": 1.3,
        "metadata": {
            "name": "Integration Auth Test",
            "compliance_level": "Standard"
        },
        "workflow": {
            "nodes": [
                {
                    "id": "start",
                    "task_description": "Verify programmatic auth"
                }
            ],
            "edges": []
        }
    }), encoding="utf-8")
    
    headers = {"X-Api-Key": "test_service_key_67890"}
    
    # We must patch PROJECT_ROOT carefully before routes utilize it
    with patch("eval_runner.config.PROJECT_ROOT", tmp_path):
        # We still mock Thread to avoid side effects of actual execution
        with patch("threading.Thread") as mock_thread:
            response = client.post(
                "/api/evaluate",
                json={"path": str(scenario_path.name)},
                headers=headers
            )
            
            # Successfully authorized and resolved
            if response.status_code != 200:
                with open("api_auth_error.log", "w", encoding="utf-8") as f:
                    f.write(response.data.decode(errors="ignore"))
                print("DEBUG FAIL DATA WRITTEN TO api_auth_error.log")
            
            assert response.status_code == 200
            data = response.get_json()
            assert data["status"] == "started"
            assert mock_thread.called

def test_evaluate_endpoint_security_dash_key_fallback(client, tmp_path):
    """
    Verify fallback behavior using a schema-compliant physical file.
    """
    scenario_path = tmp_path / "fallback_test.json"
    scenario_path.write_text(json.dumps({
        "aes_version": 1.3,
        "metadata": {
            "name": "Fallback Auth Test",
            "compliance_level": "Standard"
        },
        "workflow": {
            "nodes": [
                {
                    "id": "start",
                    "task_description": "Verify fallback execution"
                }
            ],
            "edges": []
        }
    }), encoding="utf-8")

    # We need to ensure config.SERVICE_API_KEY is updated for this test
    # because it was set at module load time.
    with patch("eval_runner.config.SERVICE_API_KEY", "fallback_dash_key"), \
         patch("eval_runner.config.PROJECT_ROOT", tmp_path):
        
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            headers = {"X-Api-Key": "fallback_dash_key"}
            response = c.post(
                "/api/evaluate",
                json={"path": str(scenario_path.name)},
                headers=headers
            )
            assert response.status_code == 200
