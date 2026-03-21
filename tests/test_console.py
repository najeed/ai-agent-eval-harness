import pytest
from flask import Flask
from eval_runner.console.app import create_app
from eval_runner.plugins import manager, BaseEvalPlugin
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import threading
import json


# Create a mock plugin to test the lifecycle hook
class MockConsolePlugin(BaseEvalPlugin):
    def on_register_console_routes(self, app, nav_registry):
        nav_registry.append(
            {
                "id": "mock_plugin",
                "title": "Mock Tools",
                "path": "/mock/tools",
                "icon": "settings",
            }
        )

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


def test_list_runs_with_query(client, tmp_path):
    """Test filtering runs by query."""
    run_log = Path("runs") / "run.jsonl"
    run_log.parent.mkdir(exist_ok=True)
    with open(run_log, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({"event": "run_start", "run_id": "test-123", "scenario": "scen-A", "timestamp": "2026-01-01"})
            + "\n"
        )
        f.write(
            json.dumps({"event": "run_start", "run_id": "other-456", "scenario": "scen-B", "timestamp": "2026-01-02"})
            + "\n"
        )

    response = client.get("/api/runs?q=test")
    data = response.get_json()
    assert len(data["runs"]) == 1
    assert data["runs"][0]["run_id"] == "test-123"


def test_evaluate_error_cases(client):
    """Test error handling in evaluate endpoint."""
    # Scenario not found
    response = client.post("/api/evaluate", json={"path": "non_existent.json"})
    assert response.status_code == 404

    # Internal error (e.g., loader fails)
    with patch("eval_runner.loader.load_scenario", side_effect=Exception("Load error")):
        response = client.post("/api/evaluate", json={"path": "tests/mock_loop.jsonl"})
        assert response.status_code == 500


def test_save_scenario_success(client, tmp_path):
    """Test successful scenario saving."""
    payload = {"scenario_id": "new-scen", "title": "New", "industry": "test-ind", "description": "desc"}
    with patch("eval_runner.catalog.ScenarioCatalog.build_index") as mock_build:
        with patch("eval_runner.console.routes.open", create=True) as mock_open:
            with patch("eval_runner.console.routes.Path.mkdir"):
                response = client.post("/api/scenarios", json=payload)
                assert response.status_code == 200
                assert response.get_json()["status"] == "success"
                mock_build.assert_called_once()
                mock_open.assert_called_once()


def test_save_scenario_errors(client):
    """Test error cases for save_scenario."""
    # Missing ID
    assert client.post("/api/scenarios", json={}).status_code == 400
    # Invalid ID
    assert client.post("/api/scenarios", json={"scenario_id": "???"}).status_code == 400


def test_debugger_state_post(client):
    """Test posting state to debugger."""
    response = client.post("/api/debugger/state", json={"event": "test_event", "data": {"foo": "bar"}})
    assert response.status_code == 200

    # Verify it updated
    response = client.get("/api/debugger/state")
    data = response.get_json()
    assert data["data"]["timeline"][-1]["event"] == "test_event"


def test_debugger_load_run_id(client, tmp_path):
    """Test loading historical trace for debugger."""
    # Mock a trace file
    runs_dir = Path("runs")
    runs_dir.mkdir(exist_ok=True)
    trace_file = runs_dir / "trace-123.jsonl"
    with open(trace_file, "w") as f:
        f.write(json.dumps({"event": "world_state_change", "state": "done"}) + "\n")

    response = client.get("/api/debugger/state?run_id=trace-123")
    assert response.status_code == 200
    assert response.get_json()["data"]["summary"]["state"] == "done"


def test_debugger_demo_trace_dynamic(client):
    """Test dynamic generation of demo traces."""
    with patch("eval_runner.console.demo_traces.get_demo_trace") as mock_get:
        mock_get.return_value = [{"event": "start"}]
        response = client.get("/api/debugger/state?run_id=run-loan-risk-fail")
        assert response.status_code == 200
        assert "Demo Narrative" in response.get_json()["data"]["summary"]["message"]


def test_read_doc_errors(client):
    """Test read_doc error handling."""
    # Traversal attempt
    assert client.get("/api/docs/%2e%2e%2fconfig.py").status_code == 403
    # Non-existent
    assert client.get("/api/docs/void.md").status_code == 404


def test_get_info(client):
    """Test system info endpoint."""
    response = client.get("/api/info")
    assert response.status_code == 200
    assert "version" in response.get_json()


def test_refresh_index(client):
    """Test index refresh endpoint."""
    with patch("eval_runner.catalog.ScenarioCatalog.build_index") as mock_build:
        response = client.post("/api/scenarios/refresh")
        assert response.status_code == 200
        mock_build.assert_called_once()
