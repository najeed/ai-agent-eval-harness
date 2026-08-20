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
def console_jail(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    tmp_root = Path(tempfile.gettempdir()) / f"aes_console_sys_jail_extra_{worker_id}"
    root = tmp_root / "root"
    runs = root / "runs"
    docs = root / "docs-v1-deprecated-reference"

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
    from eval_runner.console.routes.scenarios import scenario_bp

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(scenario_bp, url_prefix="/api")

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
    # Force scenarios to empty list to trigger index load
    catalog.scenarios = []

    try:
        with (
            patch("eval_runner.config.GOOGLE_API_KEY", None),
            patch("eval_runner.config.ANTHROPIC_API_KEY", None),
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
        catalog.scenarios = [{"id": "dummy"}]
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
    finally:
        catalog.scenarios = []

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


# --- Coverage booster for system.py ---


def test_debugger_state_store_post_event_no_dict_data():
    from eval_runner.console.routes.system import DebuggerStateStore

    DebuggerStateStore.reset()
    # 1. No data key
    DebuggerStateStore.post_event({"event": "test"})
    # 2. data key is not a dict
    DebuggerStateStore.post_event({"event": "test", "data": "string_not_dict"})
    assert len(DebuggerStateStore._events) == 2


def test_system_route_list_docs_dir_missing(client):
    from eval_runner import config

    # Temporarily point PROJECT_ROOT to somewhere where docs directory does not exist
    with patch.object(config, "PROJECT_ROOT", Path("non_existent_folder_xyz")):
        res = client.get("/api/docs")
        assert res.status_code == 200
        assert res.get_json()["docs"] == []


def test_system_route_read_doc_no_extension_fallback(client, console_jail):
    docs_dir = console_jail["docs"]
    doc = docs_dir / "my_guide.md"
    doc.write_text("my guide content", encoding="utf-8")

    # Access filename without .md extension, should fallback to my_guide.md (Lines 167-169)
    res = client.get("/api/docs/my_guide")
    assert res.status_code == 200
    assert res.get_json()["content"] == "my guide content"


def test_system_route_cleanup_runs_files_and_plugins(client, console_jail):
    runs_dir = console_jail["runs"]
    # 1. Create a directory (should be deleted)
    (runs_dir / "run_dir_1").mkdir(parents=True, exist_ok=True)
    # 2. Create a jsonl file (should be link/deleted)
    (runs_dir / "run_1.jsonl").write_text("{}", encoding="utf-8")
    # 3. Create a non-json/jsonl file (should be skipped)
    (runs_dir / "run_2.txt").write_text("{}", encoding="utf-8")

    class CrashingCleanupPlugin:
        def on_cleanup_runs(self):
            raise ValueError("Plugin cleanup failed")

    from eval_runner.plugins import manager

    plugin = CrashingCleanupPlugin()
    manager.plugins.append(plugin)

    try:
        res = client.post("/api/cleanup-runs")
        assert res.status_code == 200
        assert res.get_json()["count"] >= 2
        assert not (runs_dir / "run_dir_1").exists()
        assert not (runs_dir / "run_1.jsonl").exists()
        assert (runs_dir / "run_2.txt").exists()
    finally:
        manager.plugins.remove(plugin)


def test_system_route_debugger_state_glob_fallback_and_empty_line(client, console_jail):
    runs_dir = console_jail["runs"]
    # Place trace file inside a nested sub-directory to force glob fallback (Line 349)
    nested_dir = runs_dir / "nested_folder" / "glob_run_id"
    nested_dir.mkdir(parents=True, exist_ok=True)

    # Write empty lines along with a valid trace event to cover empty line checks (Line 356->355)
    (nested_dir / "run.jsonl").write_text(
        '\n\n{"event": "run_start", "data": {}}\n\n', encoding="utf-8"
    )

    res = client.get("/api/debugger/state?run_id=glob_run_id")
    assert res.status_code == 200
    assert len(res.get_json()["data"]["timeline"]) == 1


# ---------------------------------------------------------------------------
# Missing-branch coverage additions for system.py
# ---------------------------------------------------------------------------


def test_system_route_debugger_loan_narrative(client):
    """Cover line 73->74: run_end event with run_id starting with 'run-loan'."""
    from eval_runner.events import CoreEvents

    res = client.post(
        "/api/debugger/state",
        json={
            "event": CoreEvents.RUN_END,
            "data": {"status": "COMPLETED", "run_id": "run-loan-demo-001"},
        },
    )
    assert res.status_code == 200
    state = client.get("/api/debugger/state").get_json()
    msg = state["data"]["summary"]["message"]
    assert "(Industrial Demo Narrative)" in msg


def test_system_route_cleanup_runs_dir_absent(client, monkeypatch):
    """Cover line 274->286: cleanup_runs when RUN_LOG_DIR does not exist."""
    from pathlib import Path

    from eval_runner import config

    monkeypatch.setattr(config, "RUN_LOG_DIR", Path("/nonexistent_dir_xyz_aes"))
    res = client.post("/api/cleanup-runs")
    assert res.status_code == 200
    assert res.get_json()["count"] == 0


def test_system_route_cleanup_runs_plugin_without_method(client, console_jail):
    """Cover line 290->288 false branch: plugin with no on_cleanup_runs attribute."""
    from eval_runner.plugins import manager

    class NoCleanupPlugin:
        pass

    plugin = NoCleanupPlugin()
    manager.plugins.append(plugin)
    try:
        res = client.post("/api/cleanup-runs")
        assert res.status_code == 200
    finally:
        manager.plugins.remove(plugin)


def test_system_route_debugger_state_demo_trace_hydration(client):
    """Cover 336->363 false branch: get_demo_trace returns a trace, skipping file scan."""
    demo_events = [{"event": "run_start", "data": {}}]
    with patch("eval_runner.console.demo_traces.get_demo_trace", return_value=demo_events):
        res = client.get("/api/debugger/state?run_id=run-loan-demo-hydrate")
    assert res.status_code == 200
    body = res.get_json()
    assert "data" in body
    assert "timeline" in body["data"]


def test_system_route_ollama_status_all_paths(client):
    """Cover lines 394-410: all three ollama-status sub-paths."""

    # 1. Valid HTTP endpoint — server responds 200
    class FakeResponse:
        status = 200

        def read(self):
            return b'{"models": [{"name": "llama3:latest"}, {"name": "mistral"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        res = client.get("/api/system/ollama-status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["available"] is True
    assert data["models"] == ["llama3:latest", "mistral"]

    # 2. urlopen raises (server unreachable)
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        res = client.get("/api/system/ollama-status")
    assert res.status_code == 200
    assert res.get_json()["available"] is False
    assert res.get_json()["models"] == []

    # 3. Endpoint that doesn't start with http/https
    from eval_runner import config

    with patch.object(config, "OLLAMA_BASE_URL", "grpc://localhost:9000", create=True):
        res = client.get("/api/system/ollama-status")
    assert res.status_code == 200
    assert res.get_json()["available"] is False
    assert res.get_json()["models"] == []


def test_system_route_read_doc_fallback_not_found(client, console_jail):
    """Cover 168->171 false branch: no-extension request and .md file doesn't exist."""
    # Request a filename without extension where no .md file exists either
    res = client.get("/api/docs/nonexistent_guide_xyz")
    assert res.status_code == 404


def test_system_route_auto_translate_success(client):
    """Test POST /api/v1/auto-translate succeeds."""
    mock_scenario = {"id": "scenario-1", "title": "Mock Title"}

    async def mock_translate(*args, **kwargs):
        return mock_scenario

    with patch("eval_runner.auto_translate.translate_to_scenario", side_effect=mock_translate):
        res = client.post("/api/v1/auto-translate", json={"text": "raw specs", "model": "m1"})
        assert res.status_code == 200
        assert res.get_json() == mock_scenario


def test_system_route_auto_translate_missing_text(client):
    """Test POST /api/v1/auto-translate fails with 400 when text is missing."""
    res = client.post("/api/v1/auto-translate", json={"model": "m1"})
    assert res.status_code == 400
    assert "Missing required field: text" in res.get_json()["error"]


def test_system_route_auto_translate_failure(client):
    """Test POST /api/v1/auto-translate fails with 500 when translate_to_scenario raises."""

    async def mock_translate_fail(*args, **kwargs):
        raise RuntimeError("Ollama crashed")

    with patch("eval_runner.auto_translate.translate_to_scenario", side_effect=mock_translate_fail):
        res = client.post("/api/v1/auto-translate", json={"text": "raw specs"})
        assert res.status_code == 500
        assert "Ollama crashed" in res.get_json()["error"]


def test_scenarios_evaluate_by_id(client, console_jail):
    """Cover lines 108-109 in scenarios.py evaluate_scenario route."""
    from eval_runner.catalog import ScenarioCatalog

    cat = ScenarioCatalog.get_instance()
    scen_dir = console_jail["root"] / "industries" / "generic" / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "scen_evaluate_id.json"
    scen_file.write_text('{"id": "scen_evaluate_id", "title": "Scen Title"}', encoding="utf-8")

    cat.scenarios = [
        {"id": "scen_evaluate_id", "path": "industries/generic/scenarios/scen_evaluate_id.json"}
    ]

    with patch("eval_runner.loader.load_scenario") as mock_load:
        mock_load.return_value = {"id": "scen_evaluate_id"}
        with patch("threading.Thread.start"):  # Don't actually run thread
            res = client.post("/api/v1/evaluate", json={"path": "scen_evaluate_id"})
            assert res.status_code == 200
            assert res.get_json()["status"] == "started"


def test_scenarios_evaluate_async_eval_fails(client, console_jail):
    """Cover lines 144-145: async evaluation failure thread logger error."""
    from eval_runner.catalog import ScenarioCatalog

    ScenarioCatalog.get_instance()
    scen_dir = console_jail["root"] / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "scen_eval_fail.json"
    scen_file.write_text('{"id": "scen_eval_fail"}', encoding="utf-8")

    import time

    # Mock engine.run_evaluation to raise exception
    with patch("eval_runner.engine.run_evaluation", side_effect=ValueError("Async engine crash")):
        with patch("eval_runner.loader.load_scenario", return_value={"id": "scen_eval_fail"}):
            res = client.post("/api/v1/evaluate", json={"path": str(scen_file)})
            assert res.status_code == 200
            # Wait for thread to finish
            time.sleep(0.5)


def test_scenarios_mutate_by_id_success(client, console_jail):
    """Cover mutate_scenario with scenario_id lookup (lines 182-187)."""
    from eval_runner.catalog import ScenarioCatalog

    cat = ScenarioCatalog.get_instance()
    scen_dir = console_jail["root"] / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "scen_mutate_id.json"
    scen_file.write_text('{"id": "scen_mutate_id", "title": "Original"}', encoding="utf-8")

    cat.scenarios = [{"id": "scen_mutate_id", "path": "scenarios/scen_mutate_id.json"}]

    with patch(
        "eval_runner.mutator.mutate_scenario",
        return_value={"id": "scen_mutate_id", "title": "Mutated"},
    ):
        res = client.post("/api/v1/mutate", json={"scenario_id": "scen_mutate_id", "type": "typo"})
        assert res.status_code == 200
        assert res.get_json()["mutated"]["title"] == "Mutated"


def test_scenarios_mutate_by_id_not_found(client):
    """Cover mutate_scenario scenario_id 404 (line 185)."""
    res = client.post("/api/v1/mutate", json={"scenario_id": "nonexistent_mutate_id"})
    assert res.status_code == 404
    assert "not found" in res.get_json()["error"]
