import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

# SUT
import eval_runner.config
from eval_runner.console.routes import DebuggerStateStore, core_bp
from eval_runner.utils import rmtree_resilient


@pytest.fixture(scope="module")
def console_jail():
    """
    Creates a dedicated, isolated jail for console route testing.
    This fixture avoids global os.environ pollution.
    """
    tmp_root = Path(tempfile.gettempdir()) / "aes_console_test_jail"
    root = tmp_root / "root"
    runs = root / "runs"
    docs = root / "docs-old"
    demo = root / "sample_agent" / "loan_agent_demo"

    # Cleanup any previous leaks
    if tmp_root.exists():
        rmtree_resilient(tmp_root)

    os.makedirs(docs, exist_ok=True)
    os.makedirs(runs, exist_ok=True)
    os.makedirs(demo, exist_ok=True)
    os.makedirs(root / "industries" / "healthcare" / "scenarios", exist_ok=True)
    os.makedirs(root / "reports" / "trajectories", exist_ok=True)

    yield {
        "root": root,
        "runs": runs,
        "docs": docs,
        "demo": demo,
    }

    # Teardown
    if tmp_root.exists():
        rmtree_resilient(tmp_root)


@pytest.fixture
def client(console_jail, monkeypatch):
    """Provides a Flask test client with localized config patching."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    from eval_runner.console.routes import demo_bp, run_bp, scenario_bp, system_bp, trust_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(scenario_bp, url_prefix="/api")
    app.register_blueprint(run_bp, url_prefix="/api")
    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(trust_bp)
    app.register_blueprint(demo_bp)

    # Isolated monkeypatching of the config module attributes
    monkeypatch.setattr(eval_runner.config, "PROJECT_ROOT", console_jail["root"])
    monkeypatch.setattr(eval_runner.config, "RUN_LOG_DIR", console_jail["runs"])
    monkeypatch.setattr(
        eval_runner.config, "TRAJECTORIES_DIR", console_jail["root"] / "reports" / "trajectories"
    )
    monkeypatch.setattr(eval_runner.config, "DASHBOARD_API_KEY", "test-key-123")
    monkeypatch.setattr(eval_runner.config, "SERVICE_API_KEY", "test-key-123")

    # Bypass auth decorators globally for unit tests
    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


@pytest.fixture(autouse=True)
def clean_state():
    """Ensures stateful stores are reset between tests."""
    DebuggerStateStore.reset()
    from eval_runner.catalog import ScenarioCatalog

    ScenarioCatalog.clear_instance()
    yield


def test_get_loan_demo_context(client, console_jail):
    demo = console_jail["demo"]
    (demo / "loan_prd.md").write_text("prd content", encoding="utf-8")
    (demo / "loan_approval.aes.yaml").write_text("aes content", encoding="utf-8")
    (demo / "loan_approval_scenario.json").write_text('{"scenario": "data"}', encoding="utf-8")

    response = client.get("/api/demo/loan/context", headers={"X-AES-API-KEY": "test-key-123"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["prd"] == "prd content"
    assert "updated_at" in data


@patch("subprocess.run")
def test_execute_demo_command_whitelist(mock_run, client):
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    res = client.post(
        "/api/demo/execute",
        json={"command": "cat loan_prd.md"},
        headers={"X-AES-API-KEY": "test-key-123"},
    )
    assert res.status_code == 200


@patch("eval_runner.console.routes.ScenarioCatalog")
def test_list_scenarios(mock_catalog_cls, client):
    mock_cat = mock_catalog_cls.return_value
    mock_catalog_cls.get_instance.return_value = mock_cat
    mock_cat.search.return_value = [{"id": "s1"}]
    res = client.get("/api/scenarios?q=test", headers={"X-AES-API-KEY": "test-key-123"})
    assert res.status_code == 200


def test_list_runs(client, console_jail):
    runs_dir = console_jail["runs"]
    log_file = runs_dir / "test_run.jsonl"
    log_file.write_text(
        '{"event": "run_start", "run_id": "run_123", "scenario": "Test", '
        '"timestamp": "1970-01-01T00:00:00"}\n',
        encoding="utf-8",
    )
    res = client.get("/api/runs", headers={"X-AES-API-KEY": "test-key-123"})
    data = res.get_json()
    assert len(data["runs"]) > 0
    log_file.unlink()


@patch("eval_runner.loader.load_scenario")
@patch("eval_runner.engine.run_evaluation")
@patch("threading.Thread")
def test_evaluate_scenario(mock_thread, mock_run_eval, mock_load, client, console_jail):
    mock_load.return_value = {"id": "scen_1"}
    root = console_jail["root"]
    scen_file = root / "scenarios" / "test.json"
    scen_file.parent.mkdir(parents=True, exist_ok=True)
    scen_file.write_text("{}", encoding="utf-8")
    res = client.post(
        "/api/v1/evaluate",
        json={"path": "scenarios/test.json"},
        headers={"X-AES-API-KEY": "test-key-123"},
    )
    assert res.status_code == 200


def test_save_scenario(client, console_jail):
    root = console_jail["root"]
    payload = {
        "id": "new-scen",
        "industry": "healthcare",
        "title": "New",
        "tasks": [{"task_id": "t1", "description": "desc", "expected_outcome": "win"}],
    }
    res = client.post("/api/scenarios", json=payload, headers={"X-AES-API-KEY": "test-key-123"})
    assert res.status_code == 200
    expected = root / "industries" / "healthcare" / "scenarios" / "new-scen.json"
    assert expected.exists()


def test_debugger_state_lifecycle(client):
    res = client.post(
        "/api/debugger/state",
        json={"event": "world_state_change", "data": {"state": {"hp": 100}}},
        headers={"X-AES-API-KEY": "test-key-123"},
    )
    assert res.status_code == 200

    res = client.get("/api/debugger/state", headers={"X-AES-API-KEY": "test-key-123"})
    data = res.get_json()
    assert data.get("data") is not None
    assert "summary" in data["data"]


def test_get_debugger_state_historical(client, console_jail):
    runs_dir = console_jail["runs"]
    log_file = runs_dir / "run_456.jsonl"
    log_file.write_text('{"event": "world_state_change", "state": {"val": 1}}\n', encoding="utf-8")
    res = client.get(
        "/api/debugger/state?run_id=run_456", headers={"X-AES-API-KEY": "test-key-123"}
    )
    assert res.status_code == 200
    log_file.unlink()


def test_docs_api(client, console_jail):
    docs_dir = console_jail["docs"]
    doc_file = docs_dir / "g1.md"
    doc_file.write_text("# Doc", encoding="utf-8")
    mock_file = MagicMock()
    mock_file.stem = "g1"
    mock_file.relative_to.return_value = "g1.md"
    with patch("pathlib.Path.rglob", return_value=[mock_file]):
        res = client.get("/api/docs", headers={"X-AES-API-KEY": "test-key-123"})
        assert len(res.get_json()["docs"]) == 1
    res = client.get("/api/docs/g1.md", headers={"X-AES-API-KEY": "test-key-123"})
    assert res.status_code == 200
    assert res.get_json()["content"] == "# Doc"


def test_read_doc_unauthorized(client):
    res = client.get("/api/docs/../../../etc/passwd", headers={"X-AES-API-KEY": "test-key-123"})
    assert res.status_code == 403
