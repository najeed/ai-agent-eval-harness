import pytest
from sample_agent import agent_app

app = agent_app.app


def test_agent_health_check():
    # Flask test client can check if the app loads
    client = app.test_client()
    response = client.post('/execute_task', json={"task_description": "identify the customer speed tier"})
    assert response.status_code == 200
    data = response.get_json()
    assert "tool_name" in data or "tool_names" in data or "instructions" in data


def test_agent_missing_task_description():
    client = app.test_client()
    response = client.post('/execute_task', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_agent_multiple_tools():
    client = app.test_client()
    response = client.post('/execute_task', json={"task_description": "run a remote line test and speed test"})
    assert response.status_code == 200
    data = response.get_json()
    assert "tool_names" in data or "tool_name" in data 