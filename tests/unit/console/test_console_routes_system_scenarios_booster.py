import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.system import DebuggerStateStore, system_bp
from eval_runner.utils import rmtree_resilient


@pytest.fixture(scope="module")
def console_jail():
    tmp_root = Path(tempfile.gettempdir()) / "aes_console_sys_jail_extra"
    root = tmp_root / "root"
    runs = root / "runs"
    docs = root / "docs-old"

    if tmp_root.exists():
        rmtree_resilient(tmp_root)

    os.makedirs(runs, exist_ok=True)
    os.makedirs(docs / "guides", exist_ok=True)
    os.makedirs(docs / "api", exist_ok=True)
    os.makedirs(docs / "tutorials", exist_ok=True)
    yield {"root": root, "runs": runs, "docs": docs}

    if tmp_root.exists():
        rmtree_resilient(tmp_root)


@pytest.fixture
def client(console_jail, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(system_bp, url_prefix="/api")

    monkeypatch.setattr(config, "PROJECT_ROOT", console_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", console_jail["runs"])

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


@pytest.fixture(autouse=True)
def clean_state():
    DebuggerStateStore.reset()


def test_system_route_debugger_state_handle_event_non_dict_fallback():
    """Test DebuggerStateStore.handle_event with non-dict/mock attributes fallback (Lines 55-57)"""

    class MockEvent:
        def __init__(self):
            self.name = "mock_event"
            self.data = {"val": 123}
            self.timestamp = "time_stamp"

    DebuggerStateStore.handle_event(MockEvent())
    state = DebuggerStateStore.get_state()
    # Check fallback fields: 'data' dict is popped and its contents updated to the flat event
    assert state["timeline"][0]["event"] == "mock_event"
    assert state["timeline"][0]["val"] == 123


def test_system_route_debugger_state_handle_event_no_name_has_status():
    """Test DebuggerStateStore.handle_event when name is absent but status exists (Line 61)"""
    # event is a dict but has no 'event', 'name', or 'timestamp'. It has 'status' and some data keys
    e = {"status": "in_progress", "foo": "bar"}
    DebuggerStateStore.handle_event(e)
    state = DebuggerStateStore.get_state()
    assert state["timeline"][0]["event"] == "in_progress"


def test_system_route_debugger_state_get_state_root_cause():
    """Test DebuggerStateStore.get_state when root cause event is present (Lines 88-94)"""
    DebuggerStateStore.handle_event(
        {
            "event": "custom",
            "is_root_cause": True,
            "reason": "Failed health check",
            "confidence": 0.9,
        }
    )
    state = DebuggerStateStore.get_state()
    assert "root_cause" in state
    assert state["root_cause"]["reason"] == "Failed health check"
    assert state["root_cause"]["confidence"] == 0.9


def test_system_route_get_nav(client):
    """Test GET /api/nav (Lines 109-111)"""
    with patch.dict(client.application.config, {"NAV_REGISTRY": ["item1", "item2"]}):
        res = client.get("/api/nav")
        assert res.status_code == 200
        assert res.get_json()["nav"] == ["item1", "item2"]


def test_system_route_list_docs_github_skip_and_categories(client, console_jail):
    """Test github folder skip and categorization mapping in list_docs (Lines 124, 127, 138-146)"""
    docs_dir = console_jail["docs"]
    # github skip
    github_doc = docs_dir / ".github" / "workflows" / "ci.md"
    github_doc.parent.mkdir(parents=True, exist_ok=True)
    github_doc.write_text("ci", encoding="utf-8")

    # API docs
    api_doc = docs_dir / "api" / "ref.md"
    api_doc.write_text("ref", encoding="utf-8")

    # Tutorial docs
    tut_doc = docs_dir / "tutorials" / "learn.md"
    tut_doc.write_text("learn", encoding="utf-8")

    res = client.get("/api/docs")
    assert res.status_code == 200
    docs = res.get_json()["docs"]

    ids = [d["id"] for d in docs]
    assert "ci" not in ids

    cats = {d["id"]: d["category"] for d in docs}
    assert cats.get("ref") == "API Reference"
    assert cats.get("learn") == "Tutorial"


def test_system_route_read_doc_not_found(client):
    """Test read_doc 404 Not Found path (Line 166)"""
    res = client.get("/api/docs/nonexistent_doc_file_path.md")
    assert res.status_code == 404
    assert res.get_json()["error"] == "Not Found"


def test_system_route_security_intercept_traversal_attempts(client):
    """Test security_intercept_blueprint traversal interception (Line 187)"""
    # Pass '..' in REQUEST_URI / path to trigger traverse detection
    res = client.get("/api/nav?path=../../etc")
    # request path traversal intercept handles '..' in URI/path info
    res = client.get("/api/docs/..%2fetc/passwd")
    assert res.status_code == 403
    assert "Security: Unauthorized Path Traversal" in res.get_json()["error"]


def test_system_route_info_agent_providers(client):
    """Test info provider shims and load_index fallback (Lines 210-215, 235-240)"""
    from eval_runner.catalog import ScenarioCatalog

    # Empty scenario catalogs trigger load_index (Line 200)
    catalog = ScenarioCatalog.get_instance()
    catalog.clear_instance()
    catalog = ScenarioCatalog.get_instance()
    # Force scenarios to empty dict to trigger index load
    catalog.scenarios = {}

    with (
        patch("eval_runner.config.OPENAI_API_KEY", "key"),
        patch("eval_runner.config.AGENT_API_URLS", ["http://localhost:11434"]),
        patch("eval_runner.catalog.ScenarioCatalog.load_index") as mock_load_index,
        patch("eval_runner.plugins.manager.plugins", []),
    ):
        res = client.get("/api/info")
        assert res.status_code == 200
        mock_load_index.assert_called_once()
        assert res.get_json()["agent_endpoint"] == "GPT (OpenAI)"

    # Test Ollama specific block specifically (Lines 214-215)
    catalog.scenarios = {"dummy": {}}
    with (
        patch("eval_runner.config.GOOGLE_API_KEY", None),
        patch("eval_runner.config.ANTHROPIC_API_KEY", None),
        patch("eval_runner.config.OPENAI_API_KEY", None),
        patch("eval_runner.config.AGENT_API_URLS", ["http://127.0.0.1:11434"]),
        patch("eval_runner.plugins.manager.plugins", []),
    ):
        res2 = client.get("/api/info")
        assert res2.status_code == 200
        assert res2.get_json()["agent_endpoint"] == "Llama (Ollama)"

    # Test relpath ValueError branch (Lines 235-237) and general exception branch (Lines 239-240)
    with patch("os.path.relpath", side_effect=ValueError("Cannot resolve relative path")):
        res3 = client.get("/api/info")
        assert res3.status_code == 200
        assert res3.get_json()["runs_dir"] != "hidden"

    with patch("os.path.relpath", side_effect=Exception("Critical resolution error")):
        res4 = client.get("/api/info")
        assert res4.status_code == 200
        assert res4.get_json()["runs_dir"] == "hidden"


def test_system_route_cleanup_runs_exception(client):
    """Test cleanup_runs error branch (Lines 281-282)"""
    # Mock Path.exists globally on the class to avoid WindowsPath read-only attribute errors
    with patch.object(Path, "exists", side_effect=Exception("Disk locked")):
        res = client.post("/api/cleanup-runs")
        assert res.status_code == 500
        assert "Disk locked" in res.get_json()["message"]


def test_system_route_doctor_audit_exception(client):
    """Test doctor audit error branch (Lines 300-301)"""
    with patch(
        "eval_runner.console.routes.system.get_simulator_registry",
        side_effect=Exception("Doctor audit failed"),
    ):
        res = client.get("/api/v1/doctor")
        assert res.status_code == 500
        assert "Doctor audit failed" in res.get_json()["error"]


def test_system_route_list_docs_duplicate_stem(client, console_jail):
    """Test list_docs handles duplicate stems correctly by skipping them (Line 127)"""
    docs_dir = console_jail["docs"]
    doc1 = docs_dir / "dup.md"
    doc2 = docs_dir / "guides" / "dup.md"
    doc1.write_text("dup1", encoding="utf-8")
    doc2.write_text("dup2", encoding="utf-8")

    res = client.get("/api/docs")
    assert res.status_code == 200
    docs = res.get_json()["docs"]
    stems = [d["id"] for d in docs]
    # 'dup' should only appear once
    assert stems.count("dup") == 1


def test_system_route_read_doc_unsafe_path(client):
    """Test read_doc unsafe path interception (Line 163)"""
    with patch("eval_runner.utils.is_path_safe", return_value=False):
        res = client.get("/api/docs/any_doc_path_here.md")
        assert res.status_code == 403
        assert res.get_json()["error"] == "Unauthorized Access"


# Helper to mock PropertyMock


def test_system_route_debugger_state_parsing_exception(client, console_jail):
    """Test historical trace parsing exception in debugger_state (Lines 332-335)"""
    run_id = "broken_trace_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("invalid json lines here{", encoding="utf-8")

    res = client.get(f"/api/debugger/state?run_id={run_id}")
    assert res.status_code == 500
    assert "Failed to parse trace file" in res.get_json()["error"]


def test_system_route_debugger_state_not_found(client):
    """Test historical trace not found error response (Lines 349-350)"""
    res = client.get("/api/debugger/state?run_id=missing_run_id_for_debugger")
    assert res.status_code == 404
    assert "Trace file not found" in res.get_json()["error"]


def test_system_route_ping(client):
    """Test GET /api/ping (Line 358)"""
    res = client.get("/api/ping")
    assert res.status_code == 200
    assert res.get_json()["status"] == "pong"
