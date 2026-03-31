import pytest
import json
from eval_runner.console.app import create_app
from eval_runner.console.routes import DebuggerStateStore


from unittest.mock import patch

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    # Reset store for each test
    DebuggerStateStore._events = []
    DebuggerStateStore._last_state = {"message": "Waiting for evaluation..."}
    
    # Mock API Key for integration tests
    api_key = "test-integration-key"
    from eval_runner import config
    with patch("eval_runner.console.routes.config.DASHBOARD_API_KEY", api_key):
        with app.test_client() as client:
            client.environ_base["HTTP_X_AES_API_KEY"] = api_key
            yield client


def test_debugger_state_post_and_get(client):
    """Test that posting to /debugger/state updates the store and history."""
    # 1. Post a Mock Event
    event_data = {
        "event": "run_start",
        "data": {"scenario": "test_scenario", "run_id": "123"},
    }
    response = client.post("/api/debugger/state", json=event_data)
    assert response.status_code == 200
    assert response.get_json()["status"] == "updated"

    # 2. Verify with GET
    response = client.get("/api/debugger/state")
    assert response.status_code == 200
    data = response.get_json()["data"]

    # Check summary
    assert data["summary"]["scenario"] == "test_scenario"

    # Check timeline
    assert len(data["timeline"]) == 1
    assert data["timeline"][0]["event"] == "run_start"
    assert data["timeline"][0]["scenario"] == "test_scenario"


def test_debugger_state_history_capping(client):
    """Test that DebuggerStateStore caps events at 50."""
    for i in range(60):
        client.post("/api/debugger/state", json={"event": "dummy_event", "data": {"idx": i}})

    response = client.get("/api/debugger/state")
    data = response.get_json()["data"]
    assert len(data["timeline"]) == 50
    # Last event should be idx 59
    assert data["timeline"][-1]["idx"] == 59
    # First event should be idx 10
    assert data["timeline"][0]["idx"] == 10
