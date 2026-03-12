import pytest
from flask import Flask
from eval_runner.console.app import create_app
from eval_runner.plugins import manager, BaseEvalPlugin
from unittest.mock import patch, MagicMock, AsyncMock
import threading

# Create a mock plugin to test the lifecycle hook
class MockConsolePlugin(BaseEvalPlugin):
    def on_register_console_routes(self, app, nav_registry):
        nav_registry.append({
            "id": "mock_plugin",
            "title": "Mock Tools",
            "path": "/mock/tools",
            "icon": "settings"
        })
        
        from flask import Blueprint, jsonify
        bp = Blueprint("mock", __name__)
        @bp.route("/api/mock/status")
        def status():
            return jsonify({"status": "active"})
        app.register_blueprint(bp)

@pytest.fixture
def client():
    # Inject our mock plugin for testing
    mgr_plugins = list(manager.plugins)
    manager.plugins.append(MockConsolePlugin())
    
    app = create_app()
    app.config["TESTING"] = True
    
    yield app.test_client()
    
    # Clean up
    manager.plugins = mgr_plugins

@pytest.fixture(autouse=True)
def mock_background_threads(monkeypatch):
    """Prevent actual background threads from being spawned in tests."""
    original_thread = threading.Thread
    def mock_thread_start(self):
        # Instead of starting a thread, we just return
        # This prevents run_evaluation from ever executing in tests
        pass
    
    monkeypatch.setattr(threading.Thread, "start", mock_thread_start)
    yield

def test_nav_registry_loads_core_and_plugins(client):
    """Test that the /api/nav endpoint returns core plugins and dynamically registered plugins."""
    response = client.get("/api/nav")
    assert response.status_code == 200
    
    data = response.get_json()
    assert "nav" in data
    
    nav_ids = [item["id"] for item in data["nav"]]
    
    # Check core routes
    assert "dashboard" in nav_ids
    assert "scenarios" in nav_ids
    assert "docs" in nav_ids
    assert "community" in nav_ids
    
    # Check plugin route
    assert "mock_plugin" in nav_ids

def test_docs_with_categories(client):
    """Test that docs are categorized."""
    response = client.get("/api/docs")
    assert response.status_code == 200
    data = response.get_json()
    assert "docs" in data
    if data["docs"]:
        assert "category" in data["docs"][0]
        assert data["docs"][0]["category"] in ["Guide", "API Reference"]

def test_scenario_lists_exist(client):
    """Test that the scenarios endpoint does not crash and supports filtering."""
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    data = response.get_json()
    assert "scenarios" in data
    
    # Test faceted query
    response = client.get("/api/scenarios?industry=telecom")
    assert response.status_code == 200
    assert "scenarios" in response.get_json()

def test_runs_list_exists(client):
    """Test that the runs endpoint does not crash."""
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert "runs" in response.get_json()

def test_plugin_blueprint_registration(client):
    """Test that blueprints injected by plugins are actually reachable."""
    response = client.get("/api/mock/status")
    assert response.status_code == 200
    assert response.get_json()["status"] == "active"

def test_evaluate_endpoint(client):
    """Test that the evaluation endpoint is functional."""
    response = client.post("/api/evaluate", json={"path": "scenarios/research_verification.json"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "started"
    
    # Test error case
    response = client.post("/api/evaluate", json={})
    assert response.status_code == 400

def test_docs_uniqueness(client):
    """Ensure that the /api/docs endpoint does not contain duplicate entries."""
    response = client.get("/api/docs")
    assert response.status_code == 200
    data = response.get_json()
    doc_ids = [d["id"] for d in data["docs"]]
    assert len(doc_ids) == len(set(doc_ids))

def test_catchall_route(client):
    """Ensure that valid navigation paths serve the index.html (SPA)."""
    for path in ["/", "/scenarios", "/reports", "/editor", "/debugger", "/docs", "/docs/api"]:
        response = client.get(path)
        assert response.status_code == 200
        assert b"<!DOCTYPE html>" in response.data
