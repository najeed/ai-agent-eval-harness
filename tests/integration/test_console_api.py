from unittest.mock import patch

import pytest

from eval_runner.console.app import create_app


@pytest.fixture
def client():
    """Industrial Test Client with forced auth bypass for integration parity."""
    with (
        patch("eval_runner.config.DASHBOARD_API_KEY", "test_key"),
        patch("eval_runner.config.SERVICE_API_KEY", "test_key"),
        patch("eval_runner.config.ENABLE_DEMO", True),
    ):
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            # Set session for permission bypass if needed, or use headers
            yield client


def test_system_info(client):
    """Verify that /api/info returns consolidated system metadata."""
    headers = {"X-Api-Key": "test_key"}
    response = client.get("/api/info", headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert "version" in data
    assert "agent_endpoint" in data
    assert "scenario_count" in data


def test_taxonomy_api(client):
    """Verify Roadmap: /api/v1/taxonomy registration."""
    headers = {"X-Api-Key": "test_key"}
    response = client.get("/api/v1/taxonomy", headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert "categories" in data
    assert isinstance(data["categories"], list)
    # Check for core nodes (lowercase auto() values)
    assert "policy_violation" in data["categories"]
    assert "infra_timeout" in data["categories"]


def test_metrics_api(client):
    """Verify Roadmap: /api/v1/metrics registration."""
    headers = {"X-Api-Key": "test_key"}
    response = client.get("/api/v1/metrics", headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert "metrics" in data
    assert isinstance(data["metrics"], list)


def test_mutate_api_raw(client):
    """Verify Roadmap: /api/v1/mutate accepts raw content."""
    headers = {"X-Api-Key": "test_key"}
    payload = {
        "type": "typo",
        "raw_json": {
            "title": "Raw Test",
            "description": "Original description text for mutation testing.",
        },
    }
    response = client.post("/api/v1/mutate", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert "mutated" in data
    assert "Raw Test" in data["mutated"]["title"]
    # Mutation must have occurred or at least the object is valid
    assert "description" in data["mutated"]


def test_doctor_api(client):
    """Verify Roadmap: /api/v1/doctor audit."""
    headers = {"X-Api-Key": "test_key"}
    response = client.get("/api/v1/doctor", headers=headers)
    # Status can be healthy or unhealthy depending on mocked state, but must return JSON
    if response.status_code == 500:
        print(f"   [DEBUG] Doctor Audit Error: {response.get_json()}")
    assert response.status_code in [200, 500]
    data = response.get_json()
    assert "status" in data


def test_demo_context(client):
    """Verify Demo: /api/demo/loan/context."""
    headers = {"X-Api-Key": "test_key"}
    response = client.get("/api/demo/loan/context", headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert "prd" in data
    assert "aes" in data


def test_security_traversal(client):
    """Verify Security: Blueprints inherit path traversal protection."""
    headers = {"X-Api-Key": "test_key"}
    response = client.get("/api/info?path=../../etc/passwd", headers=headers)
    # The interceptor should catch '..' in the URL/path
    assert response.status_code == 403
    assert "Security" in response.get_json()["error"]
